"""Regression checks for repository configuration and parent-owned work budgets."""
import io
import http.client
from contextlib import closing
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from http.server import ThreadingHTTPServer

from experiments.bounded_process import run_bounded
from experiments import evaluate
from init_agent.utils import load_ignore_rules, ensure_agent_dir, MAX_CONFIG_BYTES, MAX_CONFIG_ITEMS, MAX_CONFIG_STRING
from init_agent.web_budget import BoundedHTTPServer, LimitedHeaders, SnapshotCache, MAX_CONNECTIONS
from init_agent.web_ui import _table_count, _file_activity, _bounded_staleness, _snapshot_payloads, build_web_snapshot
from init_agent.graph_store import GraphStore


class ResourceBudgetTests(unittest.TestCase):
    def test_invalid_ignore_config_falls_back_atomically(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            baseline = load_ignore_rules(root)
            (root / '.agent').mkdir()
            config = root / '.agent' / 'config.json'
            invalid = ['[]', 'null', '3', '"text"', '{', '[' * 5000 + '0' + ']' * 5000,
                       ' ' * (MAX_CONFIG_BYTES + 1), '{"exclude_dirs": "bad"}',
                       json.dumps({'exclude_dirs': ['exclude-me'], 'exclude_files': [None]}),
                       json.dumps({'exclude_dirs': ['a'] * (MAX_CONFIG_ITEMS + 1)}),
                       json.dumps({'exclude_files': ['a' * (MAX_CONFIG_STRING + 1)]}),
                       '{"exclude_dirs": ["ok"]}'.encode() + b'\xff']
            for value in invalid:
                with self.subTest(kind=str(value)[:40]):
                    config.write_bytes(value if isinstance(value, bytes) else value.encode())
                    self.assertEqual(load_ignore_rules(root), baseline)
            config.write_text(json.dumps({'exclude_dirs': ['valid'], 'exclude_extensions': ['zzz']}))
            result = load_ignore_rules(root)
            self.assertIn('valid', result['exclude_dirs'])
            self.assertIn('.zzz', result['exclude_extensions'])
            config.write_text('[' * 5000 + '0' + ']' * 5000)
            with patch('init_agent.utils.json.loads', side_effect=AssertionError('must reject before decoding')):
                self.assertEqual(load_ignore_rules(root), baseline)

    def test_benchmark_output_and_deadline_are_parent_owned(self):
        with tempfile.TemporaryDirectory() as temp:
            started = time.monotonic()
            with self.assertRaises(subprocess.CalledProcessError) as failure:
                run_bounded([sys.executable, '-c', 'import time; time.sleep(60)'], cwd=temp, timeout=0.3)
            self.assertIn('deadline', failure.exception.stderr)
            self.assertLess(time.monotonic() - started, 4)
            with self.assertRaises(subprocess.CalledProcessError) as failure:
                run_bounded([sys.executable, '-c', 'import os; os.write(1,b"a"*4096); os.write(2,b"b"*4096)'],
                            cwd=temp, timeout=3, max_bytes=100)
            self.assertIn('output limit', failure.exception.stderr)
            self.assertLessEqual(len(failure.exception.output), 100)
            result = run_bounded([sys.executable, '-c', 'print("ok")'], cwd=temp, timeout=3)
            self.assertEqual(result.stdout, 'ok\n')

    @unittest.skipUnless(os.name == 'posix', 'process groups')
    def test_benchmark_kills_descendants_holding_output_pipes(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / 'escaped'
            child = f'import time; from pathlib import Path; time.sleep(1); Path({str(marker)!r}).touch()'
            parent = f'import subprocess,sys; subprocess.Popen([sys.executable,"-c",{child!r}])'
            with self.assertRaises(subprocess.CalledProcessError):
                run_bounded([sys.executable, '-c', parent], cwd=temp, timeout=0.3)
            time.sleep(1.1)
            self.assertFalse(marker.exists())

    def test_rebuild_budget_failures_become_bounded_case_results(self):
        case = {'name': 'fixture', 'repo': '$SELF'}
        output = io.StringIO()
        error = subprocess.CalledProcessError(-1, ['test'], stderr='x' * 10000)
        with patch.object(evaluate, 'load_cases', return_value=[case]), \
             patch.object(evaluate, '_rebuild_index', side_effect=error), \
             patch('sys.stdout', output):
            self.assertEqual(evaluate.main(['--rebuild-index']), 1)
        result = json.loads(output.getvalue())['results'][0]
        self.assertEqual(result['status'], 'error')
        self.assertLessEqual(len(result['error']), 2048)

    def test_connection_admission_precedes_thread_creation_and_times_out(self):
        with patch.object(ThreadingHTTPServer, '__init__'), \
             patch.object(ThreadingHTTPServer, 'process_request') as spawn, \
             patch.object(ThreadingHTTPServer, 'shutdown_request') as reject:
            server = BoundedHTTPServer(None, None)
            request = Mock()
            for _ in range(MAX_CONNECTIONS + 5):
                server.process_request(request, ('127.0.0.1', 1))
            self.assertEqual(spawn.call_count, MAX_CONNECTIONS)
            self.assertEqual(reject.call_count, 5)
            # A watchdog closes a connection even if bytes arrive before idle timeout.
            ended = threading.Event()
            request.shutdown.side_effect = lambda *_: ended.set()
            with patch('init_agent.web_budget.REQUEST_SECONDS', 0.05), \
                 patch.object(ThreadingHTTPServer, 'process_request_thread', side_effect=lambda *_: ended.wait(1)):
                server.process_request_thread(request, ('127.0.0.1', 1))
            self.assertTrue(ended.is_set())
            server.process_request(request, ('127.0.0.1', 1))
            self.assertEqual(spawn.call_count, MAX_CONNECTIONS + 1)

    def test_headers_cache_and_serialization_are_bounded(self):
        reader = LimitedHeaders(io.BytesIO(b'x' * 20000))
        with self.assertRaises(http.client.HTTPException):
            reader.readline(65537)
        calls = Mock(return_value={'ok': True})
        cache = SnapshotCache(calls)
        threads = [threading.Thread(target=cache.get) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        calls.assert_called_once()
        failing = Mock(side_effect=ValueError('budget exceeded'))
        cache = SnapshotCache(failing)
        for _ in range(3):
            with self.assertRaises(ValueError):
                cache.get()
        failing.assert_called_once()
        with patch('init_agent.web_ui.build_web_snapshot', return_value={'large': 'x' * 1000}), \
             patch('init_agent.web_ui.MAX_RESPONSE_BYTES', 100), \
             patch('init_agent.web_ui.render_dashboard_html') as render:
            with self.assertRaises(ValueError):
                _snapshot_payloads(Path('.'), 25)
            render.assert_not_called()

    def test_connection_rate_limit_applies_after_workers_finish(self):
        with patch.object(ThreadingHTTPServer, '__init__'), \
             patch.object(ThreadingHTTPServer, 'process_request') as spawn, \
             patch.object(ThreadingHTTPServer, 'shutdown_request') as reject, \
             patch('init_agent.web_budget.time.monotonic', return_value=1):
            server = BoundedHTTPServer(None, None)
            for index in range(25):
                server.process_request(Mock(), ('127.0.0.1', index))
                if index < 20:
                    server.slots.release()  # Completed request worker.
            self.assertEqual(spawn.call_count, 20)
            self.assertEqual(reject.call_count, 5)

    def test_activity_window_and_live_hash_budget(self):
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('CREATE TABLE agent_notes(id INTEGER PRIMARY KEY, path TEXT)')
            conn.executemany('INSERT INTO agent_notes(path) VALUES (?)', [('old',)] * 10000 + [('new',)] * 1000)
            self.assertEqual(_table_count(conn, "agent_notes"), 10000)
            activity = _file_activity(conn, 25)
            self.assertEqual([(item['path'], item['total']) for item in activity], [('new', 1000)])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'large').write_bytes(b'x' * 300000)
            notes = _bounded_staleness(root, [{'path': 'large', 'scope': 'file', 'file_sha256': 'abc'}])
            self.assertIsNone(notes[0]['stale'])
            self.assertIn('budget', notes[0]['stale_reason'])
            ensure_agent_dir(root)
            with GraphStore(root) as store:
                store.initialize()
                store.connection.executemany("INSERT INTO agent_notes(path,note,note_tokens_json,source,created_at,scope) VALUES ('','note','[]','test','now','repo')", [()] * 1000)
                store.connection.commit()
            with patch('init_agent.web_ui.SNAPSHOT_STEPS', 0), patch('init_agent.web_ui.SNAPSHOT_SECONDS', 0):
                with self.assertRaises(sqlite3.OperationalError):
                    build_web_snapshot(root)
