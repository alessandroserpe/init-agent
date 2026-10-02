"""Local metadata permissions and bounded parser failure regressions."""

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from init_agent.graph_store import GraphStore
from init_agent.mcp_server import InitAgentMcpServer
from init_agent.mcp_installer import _backup_config
from init_agent.parse_budget import CURRENT_PARSE_BUDGET, ParseBudget, ParseFailure
from init_agent.private_files import harden_private_path, private_open
from init_agent.refresh import refresh_index
from init_agent.scanner import scan_project
from init_agent.symbol_extractor import extract_symbols_and_relations, _extract_php_tree_sitter
from init_agent.utils import config_path, ensure_agent_dir, write_json


class LocalMetadataSecurityTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'Unix permission modes')
    def test_metadata_and_sqlite_sidecars_are_private_under_permissive_umask(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous = os.umask(0)
            try:
                ensure_agent_dir(root)
                write_json(config_path(root), {'note': 'private'})
                with GraphStore(root) as store:
                    store.initialize()
                    store.connection.execute('PRAGMA journal_mode=WAL')
                    store.connection.execute("INSERT INTO project_meta VALUES ('private', 'value')")
                    store.connection.commit()
                    self.assertTrue((root / '.agent/graph.sqlite-wal').exists())
                    for path in (root / '.agent').iterdir():
                        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path)
                    self.assertEqual(stat.S_IMODE((root / '.agent').stat().st_mode), 0o700)
            finally:
                os.umask(previous)

    @unittest.skipUnless(os.name == 'posix', 'Unix permission modes')
    def test_existing_modes_debug_logs_and_backups_are_hardened(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ensure_agent_dir(root)
            with GraphStore(root) as store:
                store.initialize()
            (root / '.agent').chmod(0o755)
            (root / '.agent/graph.sqlite').chmod(0o644)
            write_json(config_path(root), {'private': 'note'})
            config_path(root).chmod(0o644)
            with GraphStore(root):
                pass
            self.assertEqual(stat.S_IMODE((root / '.agent').stat().st_mode), 0o700)
            for path in (root / '.agent').iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            config = root / 'config.toml'
            config.write_text('private = "value"')
            config.chmod(0o644)
            backup = _backup_config(config)
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
            log = root / 'debug.jsonl'
            log.write_text('old\n')
            log.chmod(0o644)
            server = InitAgentMcpServer(root)
            server.debug_log = log
            server._debug('test', {'private': 'value'})
            self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o600)
            self.assertIn('value', log.read_text())

    @unittest.skipUnless(os.name == 'posix', 'Unix links and permissions')
    def test_private_writer_rejects_links_before_chmod_or_truncation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / 'source'
            target.write_text('preserve me')
            target.chmod(0o644)
            symlink = root / 'symlink'
            symlink.symlink_to(target)
            hardlink = root / 'hardlink'
            os.link(target, hardlink)
            for link in [symlink, hardlink]:
                with self.subTest(link=link), self.assertRaises(OSError):
                    with private_open(link):
                        pass
            self.assertEqual(target.read_text(), 'preserve me')
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
            hardlink.unlink()
            with patch('init_agent.private_files._has_macos_acl', return_value=True):
                with self.assertWarnsRegex(RuntimeWarning, 'extended ACL'):
                    harden_private_path(target)

    @unittest.skipUnless(sys.platform == "darwin", "Darwin extended ACLs")
    def test_macos_extended_acl_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'metadata'
            path.write_text('private')
            subprocess.run(['/bin/chmod', '+a', 'everyone allow read', str(path)], check=True)
            try:
                with self.assertWarnsRegex(RuntimeWarning, 'extended ACL'):
                    harden_private_path(path)
            finally:
                subprocess.run(['/bin/chmod', '-N', str(path)], check=True)

    def test_deep_inputs_do_not_abort_mapping_or_retain_stale_symbols(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ensure_agent_dir(root)
            bad = root / 'bad.py'
            bad.write_text('def old_symbol(): pass\n')
            good = root / 'good.py'
            good.write_text('def healthy(): pass\n')
            with GraphStore(root) as store:
                store.initialize()
                scan_project(root, store)
            bad.write_text('value = ' + '[' * 100 + '0' + ']' * 100)
            (root / 'deep.json').write_text('[' * 100 + '0' + ']' * 100)
            result = refresh_index(root)
            self.assertEqual(len(result['errors']), 2)
            with GraphStore(root) as store:
                result = scan_project(root, store)
                self.assertEqual(result['error_count'], 2)
                names = [row['name'] for row in store.connection.execute('SELECT name FROM symbols')]
                self.assertIn('healthy', names)
                self.assertNotIn('old_symbol', names)

    def test_parser_failures_and_output_budgets_are_bounded(self):
        for error in [RecursionError('SOURCE_SECRET'), MemoryError('SOURCE_SECRET')]:
            with patch('init_agent.symbol_extractor._extract_json_config', side_effect=error):
                with self.assertRaises(ParseFailure) as caught:
                    extract_symbols_and_relations('{}', 'json')
                self.assertNotIn('SOURCE_SECRET', str(caught.exception))
        with patch('init_agent.parse_budget.MAX_PARSE_RECORDS', 5):
            with self.assertRaises(ParseFailure):
                extract_symbols_and_relations('\n'.join(f'def f{i}(): pass' for i in range(20)), 'python')
        with patch('init_agent.parse_budget.MAX_PARSE_SECONDS', 0):
            with self.assertRaises(ParseFailure):
                extract_symbols_and_relations('def f(): pass', 'python')
        with self.assertRaises(ParseFailure):
            extract_symbols_and_relations('x = ' + '+1' * 1000, 'python')
        # Braces inside strings should not be counted as syntax nesting.
        symbols, _ = extract_symbols_and_relations('{"data": "' + '[' * 1000 + '"}', 'json')
        self.assertEqual(symbols[0].name, 'data')

    def test_php_tree_walk_splits_lines_once_and_limits_nodes(self):
        class CountedSource(str):
            split_calls = 0
            def splitlines(self, *args, **kwargs):
                self.split_calls += 1
                return super().splitlines(*args, **kwargs)
        source = CountedSource(''.join(f'function f{i}() {{}}\n' for i in range(100)))
        children = []
        offset = 0
        for i, line in enumerate(str(source).splitlines(keepends=True)):
            name = SimpleNamespace(start_byte=offset + 9, end_byte=offset + 9 + len(f'f{i}'))
            node = SimpleNamespace(type='function_definition', start_point=(i, 0), end_point=(i, len(line)),
                                   start_byte=offset, end_byte=offset + len(line), named_children=[],
                                   child_by_field_name=lambda field, name=name: name if field == 'name' else None)
            children.append(node)
            offset += len(line)
        tree = SimpleNamespace(root_node=SimpleNamespace(type='program', start_point=(0, 0), named_children=children))
        parser = SimpleNamespace(parse=lambda _: tree)
        with patch('init_agent.symbol_extractor._php_tree_sitter_parser', return_value=(parser, object())):
            symbols, _ = _extract_php_tree_sitter(source)
            self.assertEqual(len(symbols), 100)
            self.assertEqual(source.split_calls, 1)
            token = CURRENT_PARSE_BUDGET.set(ParseBudget())
            try:
                with patch('init_agent.parse_budget.MAX_PARSE_NODES', 10), self.assertRaises(ParseFailure):
                    _extract_php_tree_sitter(source)
            finally:
                CURRENT_PARSE_BUDGET.reset(token)
