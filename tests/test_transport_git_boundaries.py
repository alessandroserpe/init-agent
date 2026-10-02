import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from init_agent.mcp_server import (_read_message, FramingError, InitAgentMcpServer,
                                   MAX_FRAME_BYTES, MAX_HEADER_LINE, MAX_HEADERS)
from init_agent.git_boundary import validated_git_dir
from init_agent.git_reader import has_git
from init_agent.utils import run_git_read, git_read_environment
from init_agent.web_ui import serve_web_ui
from http.server import ThreadingHTTPServer


class TransportGitBoundaryTests(unittest.TestCase):
    def test_oversized_jsonl_and_nested_json_are_rejected_before_decoding(self):
        for raw in (b'{' + b' ' * MAX_FRAME_BYTES,
                    b'{"x":' + b'[' * 40 + b'0' + b']' * 40 + b'}\n'):
            stream = io.BytesIO(raw)
            with patch('init_agent.mcp_server.json.loads') as decode:
                with self.assertRaises(FramingError):
                    _read_message(stream)
                decode.assert_not_called()
                self.assertLessEqual(stream.tell(), MAX_FRAME_BYTES + 1)

    def test_invalid_headers_never_read_advertised_body(self):
        class NoBody(io.BytesIO):
            def read(self, size=-1):
                raise AssertionError('must reject headers before reading body')
        for raw in (b'Content-Length: 999999999\r\n\r\n',
                    b'Content-Length: -1\r\n\r\n',
                    b'X: ' + b'x' * MAX_HEADER_LINE + b'\r\n\r\n',
                    b'X: x\r\n' * (MAX_HEADERS + 1) + b'\r\n',
                    b'Content-Length: 1\r\nContent-Length: 1\r\n\r\n'):
            with self.subTest(raw=raw[:60]), self.assertRaises(FramingError):
                _read_message(NoBody(raw))

    def test_envelope_names_and_eof_are_bounded(self):
        for request in ({'method': 'x' * 129}, {'method': 'tools/call', 'params': {'name': 'x' * 129}}, {'method': [], 'id': 1}):
            with self.assertRaises(FramingError):
                _read_message(io.BytesIO(json.dumps(request).encode() + b'\n'))
        with self.assertRaises(FramingError):
            _read_message(io.BytesIO(b'Content-Length: 10\r\n\r\n{}'))
        with self.assertRaises(FramingError):
            _read_message(io.BytesIO(b'\n' * 20))

    def test_fatal_frame_closes_without_dispatching_trailing_request(self):
        raw = b'Content-Length: 999999999\r\n\r\n{"method":"ping"}\n'
        with patch('init_agent.mcp_server.sys.stdin', SimpleNamespace(buffer=io.BytesIO(raw))), \
             patch('init_agent.mcp_server.sys.stdout', SimpleNamespace(buffer=io.BytesIO())), \
             patch.object(InitAgentMcpServer, 'handle') as handle:
            self.assertEqual(InitAgentMcpServer(Path('.')).serve(), 1)
            handle.assert_not_called()

    def test_git_rejects_external_admin_paths_and_alternates(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            root, other = parent / 'repo', parent / 'other'
            root.mkdir(); other.mkdir()
            (root / '.git').symlink_to(other, target_is_directory=True)
            self.assertFalse(has_git(root))
            with patch('init_agent.utils.run_bounded') as run:
                with self.assertRaises(OSError):
                    run_git_read(root, 'log')
                run.assert_not_called()
            (root / '.git').unlink()
            for target in (str(other), '../other'):
                (root / '.git').write_text('gitdir: ' + target + '\n')
                self.assertFalse(has_git(root))
            (root / '.git').unlink()
            admin = root / '.git'
            (admin / 'objects/info').mkdir(parents=True)
            (admin / 'objects/info/alternates').write_text(str(other))
            self.assertFalse(has_git(root))
            (admin / 'objects/info/alternates').unlink()
            (admin / 'refs').symlink_to(other, target_is_directory=True)
            self.assertFalse(has_git(root))

    def test_git_uses_explicit_internal_admin_and_clean_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(['/usr/bin/git', 'init', '-q', str(root)], check=True)
            (root / '.git').rename(root / 'admin')
            (root / '.git').write_text('gitdir: admin\n')
            self.assertEqual(validated_git_dir(root), root.resolve() / 'admin')
            with patch.dict(os.environ, {'GIT_DIR': '/outside', 'GIT_COMMON_DIR': '/outside', 'GIT_ALTERNATE_OBJECT_DIRECTORIES': '/outside', 'GIT_CONFIG_COUNT': '1'}):
                env = git_read_environment()
                self.assertNotIn('GIT_DIR', env)
                self.assertNotIn('GIT_ALTERNATE_OBJECT_DIRECTORIES', env)
                result = run_git_read(root, 'rev-parse', '--absolute-git-dir')
                self.assertEqual(result.returncode, 0)
                self.assertEqual(Path(result.stdout.strip()), root.resolve() / 'admin')

    def test_web_default_binds_ephemeral_port_and_prints_selected_origin(self):
        for requested in (None, 8765):
            addresses = []
            def initialize(server, address, handler):
                addresses.append(address)
                server.server_port = 54321 if address[1] == 0 else address[1]
            output = io.StringIO()
            with patch.object(ThreadingHTTPServer, '__init__', initialize), \
                 patch.object(ThreadingHTTPServer, 'serve_forever'), patch.object(ThreadingHTTPServer, 'server_close'), \
                 patch('sys.stdout', output):
                serve_web_ui(Path('.'), **({} if requested is None else {'port': requested}))
            self.assertEqual(addresses[0][1], 0 if requested is None else requested)
            self.assertIn('127.0.0.1:' + str(54321 if requested is None else requested), output.getvalue())

    def test_workflow_actions_are_immutable_and_read_only(self):
        text = (Path(__file__).resolve().parents[1] / '.github/workflows/ci.yml').read_text()
        references = re.findall(r'uses:\s+(\S+)', text)
        self.assertEqual(len(references), 2)
        for reference in references:
            self.assertRegex(reference, r'^[\w-]+/[\w-]+@[0-9a-f]{40}$')
        self.assertIn('permissions:\n  contents: read', text)
        self.assertIn('persist-credentials: false', text)
