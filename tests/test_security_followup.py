"""Adversarial cases for the four follow-up findings with supplied evidence."""

import json
import os
import subprocess
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from init_agent.exporter import export_graph
from init_agent.git_reader import collect_git
from init_agent.graph_store import GraphStore
from init_agent.mcp_installer import _resolve_executable
from init_agent.read_budget import ReadBudget
from init_agent.scanner import INDEX_VERSION, index_file
from init_agent.signatures import MAX_SIGNATURE_BYTES, minimize_signature
from init_agent.symbol_extractor import extract_symbols_and_relations
from init_agent.trace import _trace_from
from init_agent.estimate import _character_count
from init_agent.utils import ensure_agent_dir, _git_indexable_paths


class FollowupSecurityTests(unittest.TestCase):
    def test_minified_source_is_minimized_before_storage_and_legacy_export(self):
        secret = 'DISTINCTIVE_BODY_LITERAL_' + 'x' * 1_999_800
        fixtures = {
            'sample.js': ('javascript', 'function process(user, token="DEFAULT_SECRET") { return "' + secret + '"; }'),
            'sample.ts': ('typescript', 'function process(user: string, token="DEFAULT_SECRET") { return "' + secret + '"; }'),
            'sample.php': ('php', '<?php function process($user, $token="DEFAULT_SECRET") { return "' + secret + '"; }'),
            'sample.go': ('go', 'func process(user string) string { return "' + secret + '" }'),
            'sample.rs': ('rust', 'fn process(user: String) { let secret = "' + secret + '"; }'),
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ensure_agent_dir(root)
            with GraphStore(root) as store:
                store.initialize()
                for name, (language, source) in fixtures.items():
                    with self.subTest(language=language):
                        self.assertLessEqual(len(source.encode()), 2_000_000)
                        path = root / name
                        path.write_text(source)
                        symbols, _ = extract_symbols_and_relations(source, language, name)
                        self.assertIn('process', [symbol.name for symbol in symbols])
                        self.assertTrue(all(len(symbol.signature.encode()) <= MAX_SIGNATURE_BYTES for symbol in symbols))
                        self.assertNotIn('DEFAULT_SECRET', str(symbols))
                        self.assertNotIn('DISTINCTIVE_BODY_LITERAL', str(symbols))
                        index_file(root, path, store)
                store.connection.commit()
                stored = [row['signature'] for row in store.connection.execute('SELECT signature FROM symbols')]
                self.assertNotIn('DISTINCTIVE_BODY_LITERAL', str(stored))
                self.assertTrue(all(len(item.encode()) <= MAX_SIGNATURE_BYTES for item in stored))
                # Simulate an existing database from before the index-version bump.
                with closing(sqlite3.connect(store.path)) as legacy:
                    legacy.execute('UPDATE symbols SET signature = ?', (fixtures['sample.js'][1],))
                    legacy.commit()
                exported = export_graph(root)
                self.assertNotIn('DISTINCTIVE_BODY_LITERAL', json.dumps(exported))
                self.assertNotIn('DEFAULT_SECRET', json.dumps(exported))
                for name in fixtures:
                    index_file(root, root / name, store)
                stored = [row['signature'] for row in store.connection.execute('SELECT signature FROM symbols')]
                self.assertNotIn('DISTINCTIVE_BODY_LITERAL', str(stored))
                self.assertEqual(INDEX_VERSION, '11')

    def test_signature_shapes_routes_and_literals(self):
        cases = [
            ('work', 'function', 'function work(user: string, token="SECRET") { return "BODY"; }', 'function work(user: string, token=...)'),
            ('work', 'function', 'func work(user string) string { return "BODY" }', 'func work(user string)'),
            ('work', 'function', 'fn work(user: String) { secret("BODY"); }', 'fn work(user: String)'),
            ('TOKEN', 'constant', 'const TOKEN = "SECRET";', 'TOKEN = ...'),
            ('/health', 'route', 'app.get("/health", () => secret("BODY"))', 'route /health'),
            ('Example', 'class', 'class Example { secret = "BODY"; }', 'class Example'),
        ]
        for name, kind, raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(minimize_signature(name, kind, raw), expected)
        self.assertLessEqual(len(minimize_signature('名' * 400, 'class', 'BODY').encode()), MAX_SIGNATURE_BYTES)
        symbols, _ = extract_symbols_and_relations('def broken(token="SECRET"): return "BODY"\n???', 'python')
        self.assertNotIn('SECRET', str(symbols))
        self.assertNotIn('BODY', str(symbols))

    def test_git_metadata_does_not_execute_repository_fsmonitor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            marker = root / 'EXECUTED'
            monitor = root / 'monitor.sh'
            monitor.write_text('#!/bin/sh\ntouch EXECUTED\n')
            monitor.chmod(0o700)
            subprocess.run(['git', '-C', str(root), 'config', 'core.fsmonitor', str(monitor)], check=True)
            (root / 'file.py').write_text('def main(): pass\n')
            collect_git(root)
            self.assertIsNone(_git_indexable_paths(root))
            self.assertFalse(marker.exists())

    def test_dense_trace_has_shared_state_and_byte_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = {i: {'path': f'{i}.py', 'role': 'source'} for i in range(70)}
            for item in files.values():
                (root / item['path']).write_text('querytoken ' * 500)
            graph = {i: [{'target': j, 'relation': 'imports', 'confidence': 1} for j in range(i + 1, min(i + 26, 70))] for i in files}
            budget = ReadBudget(max_states=30, max_bytes=1200, max_file_bytes=100)
            paths = []
            for start in range(8):
                paths += _trace_from(root, start, graph, files, {'querytoken'}, 6, budget)
            self.assertLessEqual(len(paths), 30)
            self.assertEqual(budget.states, 30)
            self.assertLessEqual(budget.bytes_read, 1200)
            self.assertTrue(budget.truncated)

    def test_estimate_reads_bounded_content_once_per_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'big.py').write_text('a' * 5000)
            (root / 'other.py').write_text('b' * 5000)
            budget = ReadBudget(max_bytes=150, max_file_bytes=100)
            self.assertEqual(_character_count(root, ['big.py'], budget), 100)
            (root / 'big.py').write_text('changed')
            self.assertEqual(_character_count(root, ['big.py', 'other.py'], budget), 150)
            self.assertEqual(budget.bytes_read, 150)
            self.assertTrue(budget.truncated)
            expired = ReadBudget(max_seconds=0)
            self.assertEqual(_character_count(root, ['big.py'], expired), 0)
            self.assertTrue(expired.truncated)

    def test_installer_ignores_path_lookalikes_and_requires_absolute_overrides(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'repo'
            root.mkdir()
            fake = root / 'codex'
            fake.write_text('#!/bin/sh\nexit 99\n')
            fake.chmod(0o700)
            with patch.dict(os.environ, {'PATH': str(root) + os.pathsep + '.'}):
                resolved = _resolve_executable('codex', root=root)
                self.assertNotEqual(resolved, str(fake))
                if resolved:
                    self.assertTrue(Path(resolved).is_absolute())
            with self.assertRaises(ValueError):
                _resolve_executable('codex', './codex', root)
            with self.assertRaises(ValueError):
                _resolve_executable('codex', str(fake), root)
            trusted = Path(temp) / 'chosen-codex'
            trusted.write_text('#!/bin/sh\nexit 0\n')
            trusted.chmod(0o700)
            self.assertEqual(_resolve_executable('codex', str(trusted), root), str(trusted.resolve()))

    @unittest.skipUnless(os.name == 'posix', 'POSIX executable permissions')
    def test_installer_requires_explicit_selection_in_shared_runtime_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'shared-runtime'
            directory.mkdir(mode=0o777)
            directory.chmod(0o777)
            executable = directory / 'test-init-agent-mcp'
            executable.write_text('#!/bin/sh\nexit 0\n')
            executable.chmod(0o700)
            with patch('init_agent.executables.sys.executable', str(directory / 'python')), \
                 patch('init_agent.executables.sysconfig.get_path', return_value=str(directory)):
                with self.assertRaisesRegex(ValueError, 'No trusted'):
                    _resolve_executable(executable.name, required=True)
                self.assertEqual(
                    _resolve_executable(executable.name, str(executable), required=True),
                    str(executable.resolve()),
                )
