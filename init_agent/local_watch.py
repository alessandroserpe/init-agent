"""Experimental foreground index maintenance; no model or agent required."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import time

from .graph_store import GraphStore
from .local_search import update_search_index
from .private_files import MetadataDirectory
from .repo_budget import bounded_operation
from .repo_files import open_repo_file
from .run import prepare_repository
from .scanner import iter_project_files
from .utils import utc_now


@contextmanager
def maintenance_lock(root):
    # Advisory lock coordinates this prototype's workers, not legacy CLI writers.
    import fcntl
    with MetadataDirectory(root, create=True) as directory:
        with directory.open('maintenance.lock', 'a') as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('A maintenance worker already owns this repository') from None
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@bounded_operation
def fingerprint(root):
    result = {}
    for path in iter_project_files(root):
        name = path.relative_to(root).as_posix()
        with open_repo_file(root, name) as handle:
            s = os.fstat(handle.fileno())
        result[name] = (s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino)
    # Rules can change without changing any currently included file.
    with MetadataDirectory(root) as directory:
        try:
            with directory.open('config.json', 'rb') as handle:
                s = os.fstat(handle.fileno())
                # Metadata permission hardening changes ctime even on reads.
                result['.agent/config.json'] = (s.st_size, s.st_mtime_ns, s.st_ino)
        except FileNotFoundError:
            pass
    return result


@bounded_operation
def indexed_hashes(root):
    if not (root / '.agent/graph.sqlite').exists():
        return {}
    with GraphStore(root) as store:
        return store.file_hashes()


def journal(root, event):
    # Bounded log: current and previous segment, no source contents.
    line = json.dumps(event, sort_keys=True) + '\n'
    with MetadataDirectory(root) as directory:
        try:
            with directory.open('maintenance.jsonl', 'rb') as handle:
                rotate = os.fstat(handle.fileno()).st_size + len(line.encode()) > 1_000_000
                previous = handle.read(1_000_000) if rotate else b''
        except FileNotFoundError:
            rotate, previous = False, b''
        if rotate:
            with directory.open('maintenance.previous.jsonl', 'wb') as handle:
                handle.write(previous)
        with directory.open('maintenance.jsonl', 'w' if rotate else 'a') as handle:
            handle.write(line)


class Maintainer:
    def __init__(self, root: Path, reconcile_seconds=60.0):
        if not math.isfinite(reconcile_seconds) or reconcile_seconds <= 0:
            raise ValueError('reconcile_seconds must be finite and positive')
        self.root = root.resolve(strict=True)
        self.reconcile_seconds = reconcile_seconds
        self.previous = None
        self.last_reconcile = None

    def tick(self):
        started = time.monotonic()
        observed = fingerprint(self.root)
        due = self.last_reconcile is None or started - self.last_reconcile >= self.reconcile_seconds
        if observed == self.previous and not due and (self.root / '.agent/graph.sqlite').is_file():
            return None
        before = indexed_hashes(self.root)
        preparation = prepare_repository(self.root)
        after = indexed_hashes(self.root)
        failed = any(preparation.get(key) == 'failed' for key in ('init', 'map', 'refresh', 'git'))
        search_update = update_search_index(self.root) if not failed else None
        changes = {
            'added': sorted(after.keys() - before.keys()),
            'removed': sorted(before.keys() - after.keys()),
            'updated': sorted(p for p in before.keys() & after.keys() if before[p] != after[p]),
        }
        event = {'at': utc_now(), 'status': 'error' if failed else ('warning' if preparation['warnings'] or (search_update and search_update['skipped_count']) else 'ready'),
                 'reason': 'startup' if self.previous is None else ('reconcile' if due else 'files_changed'),
                 'counts': {k: len(v) for k, v in changes.items()},
                 'paths': {k: v[:50] for k, v in changes.items()},
                 'paths_truncated': any(len(v) > 50 for v in changes.values()),
                 'preparation': preparation, 'search_index': search_update, 'elapsed_seconds': time.monotonic() - started}
        journal(self.root, event)
        if not failed:
            # Keep the pre-update snapshot: edits during indexing trigger another pass.
            self.previous = observed
            self.last_reconcile = started
        return event


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--interval', type=float, default=2.0)
    parser.add_argument('--reconcile-seconds', type=float, default=60.0)
    parser.add_argument('--once', action='store_true', help='Reconcile once and exit')
    args = parser.parse_args(argv)
    for value in (args.interval, args.reconcile_seconds):
        if not math.isfinite(value) or value <= 0:
            parser.error('intervals must be finite and positive')
    try:
        worker = Maintainer(args.root, args.reconcile_seconds)
        with maintenance_lock(worker.root):
            while True:
                event = worker.tick()
                if event is not None:
                    print(json.dumps(event, sort_keys=True), flush=True)
                if args.once:
                    return int(event is not None and event['status'] == 'error')
                time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
