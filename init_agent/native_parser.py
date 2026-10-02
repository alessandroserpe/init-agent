"""Disposable native-parser worker with parent-owned runtime/output limits."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import sysconfig

from .bounded_process import run_bounded
from .parse_budget import MAX_PARSE_BYTES, MAX_PARSE_SECONDS, ParseFailure

NATIVE_MEMORY_BYTES = 512 * 1024 * 1024
NATIVE_OUTPUT_BYTES = 4 * 1024 * 1024


def _worker_command():
    trusted_paths = [str(Path(__file__).resolve().parents[1])]
    trusted_paths += list(dict.fromkeys(sysconfig.get_path(key) for key in ('purelib', 'platlib')))
    bootstrap = f'import sys; sys.path[:0] = {trusted_paths!r}; from init_agent.native_parser import worker_main; raise SystemExit(worker_main())'
    return [sys.executable, '-I', '-S', '-c', bootstrap]


def extract_php_isolated(content):
    if importlib.util.find_spec('tree_sitter') is None or importlib.util.find_spec('tree_sitter_php') is None:
        raise ImportError('optional PHP parser unavailable')
    data = content.encode('utf-8')
    if len(data) > MAX_PARSE_BYTES:
        raise ParseFailure('native parser input limit exceeded')
    try:
        result = run_bounded(_worker_command(), cwd=Path(__file__).resolve().parent,
                             input_bytes=data, timeout=MAX_PARSE_SECONDS,
                             max_bytes=NATIVE_OUTPUT_BYTES, check=False)
    except subprocess.CalledProcessError as exc:
        raise ParseFailure('native parser hard runtime/output limit exceeded') from exc
    if result.returncode == 75:
        raise ImportError('native parser or enforceable resource limits unavailable')
    if result.returncode != 0:
        raise ParseFailure('native parser worker failed or exceeded resource limits')
    try:
        value = json.loads(result.stdout)
        from .symbol_extractor import ExtractedSymbol, ExtractedRelation
        return ([ExtractedSymbol(**row) for row in value['symbols']],
                [ExtractedRelation(**row) for row in value['relations']])
    except (ValueError, KeyError, TypeError, RecursionError) as exc:
        raise ParseFailure('invalid bounded native parser result') from exc


def set_native_limits():
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (NATIVE_MEMORY_BYTES, NATIVE_MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def worker_main():
    # No native dependency or input parsing may precede these limits.
    try:
        set_native_limits()
    except (ImportError, AttributeError, ValueError, OSError):
        return 75  # Fail closed to bounded regex extraction on unsupported OSes.
    try:
        from dataclasses import asdict
        from .parse_budget import CURRENT_PARSE_BUDGET, ParseBudget, preflight
        from .symbol_extractor import _extract_php_tree_sitter
        raw = sys.stdin.buffer.read(MAX_PARSE_BYTES + 1)
        if len(raw) > MAX_PARSE_BYTES:
            return 1
        content = raw.decode('utf-8')
        token = CURRENT_PARSE_BUDGET.set(ParseBudget())
        try:
            preflight(content, 'php')
            symbols, relations = _extract_php_tree_sitter(content)
            payload = json.dumps({'symbols': [asdict(item) for item in symbols],
                                  'relations': [asdict(item) for item in relations]},
                                 separators=(',', ':'))
            if len(payload.encode('utf-8')) > NATIVE_OUTPUT_BYTES:
                return 1
            sys.stdout.write(payload)
        finally:
            CURRENT_PARSE_BUDGET.reset(token)
    except ImportError:
        return 75
    except (Exception, MemoryError):
        return 1
    return 0
