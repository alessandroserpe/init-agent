"""Regression cases for the six Security Cloud findings."""

import io
import json
import os
import re
import subprocess
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from experiments.evaluate import _rebuild_index, case_command
from init_agent.agent_tools import _followup_commands
from init_agent.cli import main
from init_agent.context_builder import _verification_actions
from init_agent.estimate import _character_count, _indexed_textual_paths
from init_agent.graph_store import GraphStore
from init_agent.plan_feedback import _decode_file_manifest, _encode_file_manifest
from init_agent.reading_plan import _recommended_actions
from init_agent.run import _render_handoff_commands
from init_agent.trace import _file_score, _query_start_files, trace_query
from init_agent.utils import ensure_agent_dir, shell_quote, terminal_safe


class SecurityRegressionTests(unittest.TestCase):
    def test_trace_and_estimate_reject_external_index_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            root = parent / 'repo'
            root.mkdir()
            (parent / 'secret.txt').write_text('sensitiveuniquetoken')
            (root / 'main.py').write_text('safe')
            (root / 'escape.py').symlink_to(parent / 'secret.txt')
            (root / 'loop').symlink_to('loop')
            invalid = ['../secret.txt', str(parent / 'secret.txt'), 'escape.py', 'loop', 'missing.py']
            ensure_agent_dir(root)
            with GraphStore(root) as store:
                store.initialize()
                for path in ['main.py', *invalid]:
                    store.connection.execute("INSERT INTO files(path, language, role) VALUES (?, 'python', 'source')", (path,))
                store.connection.execute("INSERT INTO relations(source_type, source_id, relation, target_type, target_id) VALUES ('file', 2, 'include', 'file', 'main.py')")
                store.connection.commit()
            self.assertEqual(_character_count(root, ['main.py', *invalid]), 4)
            self.assertEqual(_indexed_textual_paths(root), ['main.py'])
            result = trace_query(root, 'sensitiveuniquetoken')
            self.assertTrue(result['paths'])
            self.assertEqual({p['target'] for p in result['paths']}, {'main.py'})
            for path in invalid:
                with self.subTest(path=path):
                    self.assertFalse(any('content contains' in reason for reason in _file_score(root, path, {'sensitiveuniquetoken'}, 0)[1]))
                    self.assertEqual(_query_start_files(root, {1: {'path': path}}, {'sensitiveuniquetoken'}), [])

    def test_emitted_commands_preserve_shell_arguments_without_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = "a'\" $(touch PWNED) `touch PWNED` ; $HOME \\ space.py"
            commands = [item['command'] for item in _followup_commands(value, [{'path': value}], [{'name': value, 'kind': 'function'}])]
            commands += [item['command'] for item in _verification_actions(value, [{'path': value}])]
            commands += [item['command'] for item in _recommended_actions(value, [{'path': value, 'read_priority': 'read_now', 'action': 'read', 'reason': 'test'}])]
            for line in _render_handoff_commands({'query': value, 'candidate_files': [{'path': value}], 'related_symbols': [{'name': value, 'kind': 'function'}]}):
                # Decode the Markdown code span, including variable-length fences.
                match = re.fullmatch(r"- (?P<fence>`+)(?P<command>.*?)(?P=fence)", line)
                self.assertIsNotNone(match)
                commands.append(match.group('command').strip())
            # Replace documented placeholders, then capture argv with a harmless shell function.
            for command in commands:
                with self.subTest(command=command):
                    command = command.replace('<path>', 'placeholder')
                    proc = subprocess.run(['/bin/sh', '-c', 'capture_args() { printf "%s\\000" "$@"; }; ' + command.replace('init-agent ', 'capture_args ', 1)], cwd=root, capture_output=True, check=True)
                    self.assertIn(value.encode(), proc.stdout.split(b'\0'))
                    self.assertFalse((root / 'PWNED').exists())
            for value in ['', 'line\nbreak', '$(touch PWNED)', '`touch PWNED`', 'a\\"$HOME']:
                proc = subprocess.run(['/bin/sh', '-c', 'printf %s ' + shell_quote(value)], cwd=root, capture_output=True, check=True)
                self.assertEqual(proc.stdout.decode(), value)
                self.assertFalse((root / 'PWNED').exists())

    def test_benchmark_ignores_repository_startup_and_shadow_modules(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = "from pathlib import Path; Path('PWNED').write_text('executed'); raise RuntimeError('untrusted import')\n"
            for filename in ['sitecustomize.py', 'usercustomize.py', 'json.py', 'sqlite3.py']:
                (root / filename).write_text(payload)
            (root / 'init_agent').mkdir()
            (root / 'init_agent' / '__init__.py').write_text(payload)
            with patch.dict(os.environ, {'PYTHONPATH': str(root)}):
                _rebuild_index(root)
                for case in [{'command': 'overview'}, {'query': 'startup'}]:
                    proc = subprocess.run(case_command(case), cwd=root, capture_output=True, text=True, check=True)
                    self.assertIsInstance(json.loads(proc.stdout), dict)
            self.assertFalse((root / 'PWNED').exists())

    def test_symlinked_metadata_cannot_write_outside_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            root = parent / 'repo'
            outside = parent / 'outside'
            root.mkdir()
            outside.mkdir()
            (root / '.agent').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(OSError):
                ensure_agent_dir(root)
            with self.assertRaises(OSError):
                GraphStore(root)
            self.assertEqual(list(outside.iterdir()), [])
            (root / '.agent').unlink()
            ensure_agent_dir(root)
            for filename in ['config.json', 'graph.sqlite', 'graph.sqlite-wal', 'graph.sqlite-journal']:
                link = root / '.agent' / filename
                link.symlink_to(outside / filename)
                with self.subTest(filename=filename), self.assertRaises(OSError):
                    GraphStore(root)
                self.assertFalse((outside / filename).exists())
                link.unlink()

    def test_cli_human_output_escapes_controls_and_json_roundtrips(self):
        query = 'unsafe\x1b]52;c;AAAA\x07\r\x9b2J\u202e'
        self.assertEqual(terminal_safe('hello\n\tworld'), 'hello\n\tworld')
        fake = [{'type': 'file', 'label': query, 'detail': query}]
        with patch('init_agent.cli.search', return_value=fake), patch('init_agent.cli._ensure_initialized', return_value=True):
            output = io.StringIO()
            with redirect_stdout(output):
                main(['query', 'test'])
            for control in ['\x1b', '\x07', '\r', '\x9b', '\u202e']:
                self.assertNotIn(control, output.getvalue())
        self.assertEqual(json.loads(json.dumps({'value': query}))['value'], query)

    def test_manifest_decompression_is_bounded_and_rejects_corruption(self):
        self.assertEqual(_decode_file_manifest(_encode_file_manifest(['a', 'b', 'a'])), {'a', 'b'})
        with patch('init_agent.plan_feedback.MAX_FILE_MANIFEST_BYTES', 1024):
            self.assertIsNone(_decode_file_manifest(zlib.compress(b' ' * 100000)))
            at_limit = b'["' + b'a' * 1020 + b'"]'
            self.assertIsNotNone(_decode_file_manifest(zlib.compress(at_limit)))
            self.assertIsNone(_decode_file_manifest(zlib.compress(at_limit + b' ')))
        valid = _encode_file_manifest(['a'])
        for data in [10**12, zlib.compress(b'[{}]'), b'bad zlib', valid[:-1], valid + b'junk', zlib.compress(b'not json')]:
            with self.subTest(data=data):
                self.assertIsNone(_decode_file_manifest(data))
