import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from init_agent.feedback import add_feedback, list_feedback
from init_agent.graph_store import GraphStore
from init_agent.metadata_limits import MAX_ITEMS, validate_input
from init_agent.mcp_tools import MCP_TOOL_HANDLERS
from init_agent.overview import render_overview_markdown
from init_agent.plan_feedback import save_reading_plan, finish_reading_plan, reading_plan_stats
from init_agent.read_budget import ReadBudget
from init_agent.repo_files import open_repo_file, repo_snapshot
from init_agent.scanner import index_file
from init_agent.utils import ensure_agent_dir


class MetadataBoundaryTests(unittest.TestCase):
    def test_symlink_swap_at_open_cannot_read_outside(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'repo'
            root.mkdir()
            outside = Path(temp) / 'secret.py'
            outside.write_text('SECRET_OUTSIDE')
            target = root / 'main.py'
            target.write_text('def safe(): pass')
            real_open = os.open
            swapped = False
            def swap(path, flags, *args, **kwargs):
                nonlocal swapped
                if path == 'main.py' and not swapped:
                    swapped = True
                    target.unlink()
                    target.symlink_to(outside)
                return real_open(path, flags, *args, **kwargs)
            # Preserve supports_dir_fd membership when replacing os.open.
            with patch('os.open', side_effect=swap) as mocked, patch('os.supports_dir_fd', {mocked}):
                self.assertEqual(ReadBudget().text(root, 'main.py'), '')
            with self.assertRaises(OSError):
                repo_snapshot(root, 'main.py')
            (root / 'escape').symlink_to(outside.parent, target_is_directory=True)
            with self.assertRaises(OSError):
                repo_snapshot(root, 'escape/secret.py')

    def test_directory_swap_keeps_opened_parent_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'repo'
            root.mkdir()
            directory = root / 'src'
            directory.mkdir()
            (directory / 'main.py').write_text('INSIDE')
            outside = Path(temp) / 'outside'
            outside.mkdir()
            (outside / 'main.py').write_text('SECRET_OUTSIDE')
            real_open = os.open
            def swap(path, flags, *args, **kwargs):
                fd = real_open(path, flags, *args, **kwargs)
                if path == 'src':
                    directory.rename(root / 'saved')
                    directory.symlink_to(outside, target_is_directory=True)
                return fd
            with patch('os.open', side_effect=swap) as mocked, patch('os.supports_dir_fd', {mocked}):
                snapshot = repo_snapshot(root, 'src/main.py')
            self.assertEqual(snapshot.content, 'INSIDE')
            self.assertEqual(snapshot.sha256, hashlib.sha256(b'INSIDE').hexdigest())

    def test_global_byte_and_record_quotas_are_transactional(self):
        from init_agent.metadata_limits import MAX_STORAGE_BYTES
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ensure_agent_dir(root)
            record = add_feedback(root, 'q', 'a', 'useful')
            with GraphStore(root) as store:
                store.initialize()
                before = dict(store.connection.execute("SELECT * FROM metadata_usage WHERE name='orientation_feedback'").fetchone())
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'metadata quota'):
                    store.connection.execute('UPDATE orientation_feedback SET reason=?, query=?, path=?, query_tokens_json=? WHERE id=?', (*(['x' * 9000] * 4), record['id']))
                after = dict(store.connection.execute("SELECT * FROM metadata_usage WHERE name='orientation_feedback'").fetchone())
                self.assertEqual(before, after)
                store.connection.execute("UPDATE metadata_usage SET bytes=? WHERE name='orientation_feedback'", (MAX_STORAGE_BYTES,))
                store.connection.commit()
            with self.assertRaisesRegex(ValueError, 'metadata quota'):
                add_feedback(root, 'q', 'b', 'useful')
            self.assertEqual(len(list_feedback(root)), 1)

    def test_snapshot_and_scanner_use_one_open_file_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'main.py'
            data = b'def original(): pass\n'
            path.write_bytes(data)
            snap = repo_snapshot(root, 'main.py')
            path.unlink()
            path.write_text('def replacement(): pass')
            ensure_agent_dir(root)
            with GraphStore(root) as store:
                store.initialize()
                index_file(root, path, store, snapshot=snap)
                row = store.connection.execute('SELECT * FROM files').fetchone()
                self.assertEqual(row['sha256'], hashlib.sha256(data).hexdigest())
                self.assertEqual(row['size'], len(data))
                self.assertEqual(store.connection.execute('SELECT name FROM symbols').fetchone()['name'], 'original')
            with open_repo_file(root, 'main.py') as handle:
                path.unlink()
                path.symlink_to('/etc/passwd')
                self.assertEqual(handle.read(), b'def replacement(): pass')

    def test_all_markdown_data_stays_on_its_own_line(self):
        hostile = '`\n# FORGED [link](https://evil) ```'
        pack = {'project': {'name': hostile, 'root': hostile, 'git': True, 'branch': hostile},
                'suggested_first_reads': [{'path': hostile, 'role': hostile, 'language': hostile, 'reasons': [hostile]}],
                'entry_points': [{'path': hostile, 'line': hostile, 'kind': hostile, 'name': hostile}],
                'manifests': [{'path': hostile}],
                'subsystems': [{'path_prefix': hostile, 'files': hostile, 'languages': [hostile], 'roles': [hostile]}]}
        rendered = render_overview_markdown(pack)
        self.assertNotIn('\n# FORGED', rendered)
        self.assertIn('```` ', rendered)
        self.assertIn(r'\n# FORGED', rendered)
        self.assertEqual(len(rendered.splitlines()), 23)

    def test_oversized_metadata_rejected_before_creating_database(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for arguments in ({'id': 1, 'read': ['a'] * (MAX_ITEMS + 1)}, {'id': 1, 'summary': 'x' * 4097}):
                with self.assertRaises(ValueError):
                    MCP_TOOL_HANDLERS['repo_reading_plan_finish'](root, arguments)
                self.assertFalse((root / '.agent').exists())
            with self.assertRaises(ValueError):
                add_feedback(root, 'q', 'p', 'useful', reason='x' * 4097)
            nested = []
            for _ in range(10):
                nested = [nested]
            with self.assertRaises(ValueError):
                validate_input(nested)

    def test_finalization_is_atomic_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = save_reading_plan(root, 'query', [], 3)
            result = finish_reading_plan(root, plan['id'], central=['a.py'])
            self.assertTrue(result['updated'])
            self.assertTrue(finish_reading_plan(root, plan['id'], central=['a.py'])['already_finished'])
            self.assertEqual(len(list_feedback(root)), 1)
            second = save_reading_plan(root, 'query', [], 3)
            with GraphStore(root) as store:
                store.initialize()
                store.connection.execute("CREATE TRIGGER fail_event BEFORE INSERT ON reading_plan_events BEGIN SELECT RAISE(ABORT, 'test rollback'); END")
                store.connection.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                finish_reading_plan(root, second['id'], central=['b.py'])
            self.assertEqual(len(list_feedback(root)), 1)

    def test_persistent_quota_and_bounded_feedback_pagination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ensure_agent_dir(root)
            for index in range(4):
                add_feedback(root, 'q', str(index), 'useful')
            first = list_feedback(root, limit=2)
            second = list_feedback(root, limit=2, before_id=first[-1]['id'])
            self.assertEqual([r['path'] for r in first + second], ['3','2','1','0'])
            with GraphStore(root) as store:
                store.initialize()
                store.connection.execute("UPDATE metadata_usage SET records=5000 WHERE name='orientation_feedback'")
                store.connection.commit()
            with self.assertRaisesRegex(ValueError, 'metadata quota'):
                add_feedback(root, 'q', 'extra', 'useful')
            self.assertEqual(len(list_feedback(root)), 4)

    def test_statistics_only_load_selected_plan_histories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for n in range(3):
                plan = save_reading_plan(root, str(n), [], 3)
                finish_reading_plan(root, plan['id'], central=[str(n)])
            stats = reading_plan_stats(root, limit=1)
            self.assertEqual(stats['plan_count'], 3)
            self.assertEqual(stats['finished_plan_count'], 3)
            self.assertEqual(len(stats['plans']), 1)
            self.assertEqual(stats['central_count'], 1)
