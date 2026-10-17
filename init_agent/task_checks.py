"""Optional executable checks and freshness evidence for local tasks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from .graph_store import GraphStore
from .repo_files import repo_snapshot
from .metadata_limits import bounded_metadata
from .utils import utc_now


_RUNNER = '''
import json, sys, unittest
suite = unittest.defaultTestLoader.loadTestsFromName(sys.argv[1])
result = unittest.TextTestRunner(verbosity=1).run(suite)
with open(sys.argv[2], 'w') as output:
    json.dump({'run': result.testsRun, 'skipped': len(result.skipped),
               'successful': result.wasSuccessful(),
               'expected_failures': len(result.expectedFailures)}, output)
sys.exit(0 if result.wasSuccessful() else 1)
'''


def fingerprints(root: Path, paths: list[str], cache: dict | None = None) -> dict[str, str | None]:
    if len(paths) > 100 or sum(len(name) for name in paths) > 12000:
        raise ValueError("Check scope exceeds file/path budget")
    result = {}
    for name in sorted(set(paths)):
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('File scope must use repository-relative paths')
        if cache is not None and name in cache:
            result[name] = cache[name]
            continue
        try:
            result[name] = repo_snapshot(root, name, max_text=0).sha256
        except (FileNotFoundError, IsADirectoryError):
            result[name] = None
        if cache is not None:
            cache[name] = result[name]
    return result


def check_status(root: Path, record: dict, cache: dict | None = None) -> dict:
    try:
        current = fingerprints(root, list(record['files']), cache)
    except (OSError, ValueError) as exc:
        return {**record, 'state': 'needs_rerun', 'changed_files': [], 'warning': str(exc)}
    changed = [name for name, digest in current.items() if digest != record['files'][name]]
    state = record['run_state']
    if changed or str(root.resolve()) != record['root']:
        state = 'needs_rerun'
    return {**record, 'state': state, 'changed_files': changed}


def run_check(root: Path, task_id: int, test: str, files: list[str], timeout: float = 60) -> dict:
    root = root.resolve()
    if not 0 < timeout <= 300:
        raise ValueError('Timeout must be between 0 and 300 seconds')
    if task_id <= 0 or len(test) > 500 or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+', test):
        raise ValueError('Positive task id and dotted unittest selector required')
    # Include the local test module automatically, never import it in this process.
    parts = test.split('.')
    module = next((Path(*parts[:i]).with_suffix('.py') for i in range(len(parts), 0, -1)
                   if (root / Path(*parts[:i]).with_suffix('.py')).is_file()), None)
    if module is None:
        raise ValueError('No local Python test module found')
    scope = sorted(set([*files, module.as_posix()]))
    before = fingerprints(root, scope)
    if any(digest is None for digest in before.values()):
        raise ValueError('All scoped files must exist before running')
    counts = {}
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / 'result.json'
        with tempfile.TemporaryFile() as log:
            try:
                completed = subprocess.run([sys.executable, '-c', _RUNNER, test, str(report)],
                                           cwd=root, stdout=log, stderr=log, timeout=timeout)
                code = completed.returncode
                if report.exists():
                    counts = json.loads(report.read_text())
                passed = (code == 0 and counts.get('successful') and counts.get('run', 0) > 0
                          and not counts.get('skipped') and not counts.get('expected_failures'))
                state = 'passed' if passed else 'not_verified'
            except subprocess.TimeoutExpired:
                code, state = None, 'timeout'
            log.seek(0)
            output = log.read(4000).decode('utf-8', errors='replace')
    after = fingerprints(root, scope)
    if before != after:
        state = 'needs_rerun'
    identity = json.dumps([str(root), task_id, test])
    return {'id': hashlib.sha256(identity.encode()).hexdigest()[:20], 'task_id': task_id,
            'root': str(root), 'test': test, 'files': before, 'run_state': state,
            'state': state, 'checked_at': utc_now(), 'counts': counts, 'exit_code': code, 'output': output,
            'task_closed': False, 'scope_limit': 'Only declared files and test module; not all dependencies'}


@bounded_metadata
def verify_task(root: Path, task_id: int, test: str, timeout: float = 60) -> dict:
    """Execute only the requested test, using the task's already-linked files."""
    from .tasks import get_task

    task = get_task(root, task_id)
    if task is None:
        raise ValueError('Task does not exist')
    if not task['files']:
        raise ValueError('Task has no linked files; link the relevant files before verification')
    record = run_check(root, task_id, test, task['files'], timeout=timeout)
    with GraphStore(root) as store:
        store.initialize()
        store.connection.execute(
            '''INSERT INTO agent_task_checks(task_id, test, evidence_json, checked_at)
               VALUES (?, ?, ?, ?) ON CONFLICT(task_id, test) DO UPDATE SET
               evidence_json=excluded.evidence_json, checked_at=excluded.checked_at''',
            (task_id, test, json.dumps(record), record['checked_at']),
        )
        store.connection.commit()
    return record


def attach_checks(root: Path, tasks: list[dict]) -> list[dict]:
    """Attach compact current evidence; retrieval never executes tests."""
    if not tasks:
        return tasks
    cache = {}
    with GraphStore(root) as store:
        store.initialize()
        for task in tasks:
            rows = store.connection.execute(
                'SELECT evidence_json FROM agent_task_checks WHERE task_id=? '
                'ORDER BY checked_at DESC, test LIMIT 6', (task['id'],),
            ).fetchall()
            checks = []
            for row in rows[:5]:
                record = check_status(root, json.loads(row['evidence_json']), cache)
                uncovered = sorted(set(task['files']) - set(record['files']))
                if uncovered:
                    record['state'] = 'needs_rerun'
                checks.append({key: record[key] for key in (
                    'id', 'test', 'state', 'run_state', 'checked_at', 'counts',
                    'changed_files', 'scope_limit')})
                checks[-1]['uncovered_files'] = uncovered
                if record.get('warning'):
                    checks[-1]['warning'] = record['warning']
            if rows:
                task['checks'] = checks
                task['checks_truncated'] = len(rows) > 5
    return tasks
