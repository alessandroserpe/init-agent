import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from init_agent.bounded_process import run_bounded
from init_agent.native_parser import extract_php_isolated
from init_agent.parse_budget import ParseFailure, preflight
from init_agent.symbol_extractor import extract_symbols_and_relations
from init_agent.git_reader import collect_git, status_short
from init_agent.utils import git_read_environment, _git_indexable_paths


class NativeIsolationTests(unittest.TestCase):
    def test_disappearing_sqlite_sidecar_is_not_an_unsafe_object(self):
        from init_agent import private_files
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with private_files.MetadataDirectory(root, create=True):
                pass
            sidecar = root / '.agent' / 'graph.sqlite-journal'
            sidecar.write_bytes(b'')
            check = private_files._check_descriptor
            def remove_after_open(fd, path, **kwargs):
                if path == sidecar:
                    sidecar.unlink()
                return check(fd, path, **kwargs)
            with patch.object(private_files, '_check_descriptor', side_effect=remove_after_open):
                with private_files.MetadataDirectory(root):
                    pass
            sidecar.mkdir()
            with self.assertRaises(PermissionError):
                private_files.MetadataDirectory(root)

    def test_identifier_and_error_tokens_are_counted_before_native_parse(self):
        for source in ('<?php ' + 'identifier ' * 100001, '<?php ' + '@ ' * 100001):
            with patch('init_agent.native_parser.run_bounded') as spawn:
                with self.assertRaises(ParseFailure):
                    extract_symbols_and_relations(source, 'php')
                spawn.assert_not_called()

    def test_native_worker_timeout_kills_child_and_parent_can_continue(self):
        command = [sys.executable, '-I', '-S', '-c', 'import os,time; print(os.getpid(), flush=True); time.sleep(60)']
        with patch('init_agent.native_parser.importlib.util.find_spec', return_value=object()), \
             patch('init_agent.native_parser._worker_command', return_value=command), \
             patch('init_agent.native_parser.MAX_PARSE_SECONDS', 0.8):
            with self.assertRaisesRegex(ParseFailure, 'hard runtime') as error:
                extract_php_isolated('<?php function safe() {}')
        pid = int(error.exception.__cause__.output.strip())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        symbols, _ = extract_symbols_and_relations('def healthy(): pass', 'python')
        self.assertEqual(symbols[0].name, 'healthy')

    @unittest.skipUnless(sys.platform.startswith('linux'), 'RLIMIT_AS enforcement test on Linux')
    def test_native_address_space_ceiling_blocks_allocation(self):
        package_root = str(Path(__file__).resolve().parents[1])
        code = f'import sys; sys.path.insert(0,{package_root!r}); from init_agent.native_parser import set_native_limits; set_native_limits(); bytearray(1024*1024*1024)'
        result = run_bounded([sys.executable, '-I', '-S', '-c', code], cwd=Path('/tmp'), timeout=3, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('MemoryError', result.stderr)

    def test_real_optional_native_parser_or_explicit_safe_fallback(self):
        available = all(importlib.util.find_spec(name) for name in ('tree_sitter', 'tree_sitter_php'))
        if not available:
            if os.environ.get('INIT_AGENT_REQUIRE_NATIVE_TEST'):
                self.fail('optional PHP parser dependencies missing from integration job')
            self.skipTest('optional tree-sitter packages not installed')
        try:
            symbols, _ = extract_php_isolated('<?php function isolated_function($value) { return $value; }')
        except ImportError:
            if sys.platform.startswith('linux'):
                self.fail('Linux native parser unexpectedly unavailable')
            # A platform without an enforceable native limit uses bounded regex.
            symbols, _ = extract_symbols_and_relations('<?php function isolated_function($value) { return $value; }', 'php')
        self.assertIn('isolated_function', [item.name for item in symbols])

    def test_real_git_filter_executes_only_without_inspection_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            env = git_read_environment()
            def git(*args):
                return subprocess.run(['/usr/bin/git', '-C', str(root), *args], env=env, capture_output=True, check=True)
            git('init', '-q')
            (root / 'file.py').write_text('original\n')
            (root / '.gitattributes').write_text('file.py filter=evil\n')
            git('add', '.')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
            git('config', 'filter.evil.clean', 'touch EXECUTED; cat')
            (root / 'file.py').write_text('modified\n')
            git('status', '--short')
            marker = root / 'EXECUTED'
            self.assertTrue(marker.exists(), 'positive control must exercise the actual Git filter')
            marker.unlink()
            self.assertEqual(status_short(root), [])
            self.assertFalse(collect_git(root)['git'])
            self.assertIsNone(_git_indexable_paths(root))
            self.assertFalse(marker.exists())

    def test_every_unapproved_config_namespace_is_rejected(self):
        from init_agent.git_boundary import validated_git_dir
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.git').mkdir()
            for section, key in [('filter "evil"', 'process'), ('include', 'path'),
                                 ('includeIf "gitdir:**"', 'path'), ('diff "evil"', 'textconv'),
                                 ('merge "evil"', 'driver'), ('alias', 'status'),
                                 ('credential', 'helper'), ('core', 'pager'),
                                 ('core', 'hooksPath'), ('core', 'fsmonitor')]:
                with self.subTest(section=section, key=key):
                    (root / '.git/config').write_text(f'[{section}]\n{key}=evil\n')
                    with self.assertRaises(OSError):
                        validated_git_dir(root)
