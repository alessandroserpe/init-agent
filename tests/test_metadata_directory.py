import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from experiments.evaluate import measure_indexed_file_read
from init_agent.graph_store import GraphStore
from init_agent.private_files import MetadataDirectory, write_private_text
from init_agent.utils import ensure_agent_dir


class MetadataDirectoryTests(unittest.TestCase):
    def test_config_write_remains_in_opened_directory_after_parent_swap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ensure_agent_dir(root)
            outside = root / 'outside'
            outside.mkdir()
            original = MetadataDirectory.open
            def raced(anchor, name, mode='rb'):
                if mode == 'w':
                    anchor.path.rename(root / 'original')
                    anchor.path.symlink_to(outside, target_is_directory=True)
                return original(anchor, name, mode)
            with patch.object(MetadataDirectory, 'open', raced):
                write_private_text(root / '.agent' / 'config.json', 'private')
            self.assertEqual((root / 'original/config.json').read_text(), 'private')
            self.assertEqual(list(outside.iterdir()), [])

    def test_parent_swap_before_sqlite_connect_fails_without_redirected_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ensure_agent_dir(root)
            outside = root / 'outside'
            outside.mkdir()
            original = MetadataDirectory.verify_identity
            def raced(anchor):
                anchor.path.rename(root / 'original')
                anchor.path.symlink_to(outside, target_is_directory=True)
                original(anchor)
            with patch.object(MetadataDirectory, 'verify_identity', raced), patch('init_agent.metadata_db.sqlite3.connect') as connect:
                with self.assertRaisesRegex(OSError, 'directory changed'):
                    GraphStore(root)
                connect.assert_not_called()
            self.assertEqual(list(outside.iterdir()), [])

    def test_swap_after_handoff_fails_before_next_statement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ensure_agent_dir(root)
            outside = root / 'outside'
            outside.mkdir()
            with GraphStore(root) as store:
                store.initialize()
                (root / '.agent').rename(root / 'original')
                (root / '.agent').symlink_to(outside, target_is_directory=True)
                with self.assertRaisesRegex(OSError, 'directory changed'):
                    store.connection.execute('CREATE TABLE forbidden(x)')
            self.assertEqual(list(outside.iterdir()), [])

    def test_shared_writable_sqlite_namespace_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ensure_agent_dir(root)
            root.chmod(0o777)
            try:
                with patch('init_agent.metadata_db.sqlite3.connect') as connect:
                    with self.assertRaisesRegex(PermissionError, 'writable by other users'):
                        GraphStore(root)
                    connect.assert_not_called()
                self.assertFalse((root / '.agent/graph.sqlite').exists())
            finally:
                root.chmod(0o700)

    def test_sidecar_directories_fifos_and_symlinks_fail_before_sqlite(self):
        for name in ('graph.sqlite-wal', 'graph.sqlite-journal', 'graph.sqlite-shm'):
            for kind in ('directory', 'fifo', 'symlink'):
                with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    ensure_agent_dir(root)
                    child = root / '.agent' / name
                    if kind == 'directory':
                        child.mkdir()
                        (child / 'tracked').write_text('x')
                    elif kind == 'fifo':
                        os.mkfifo(child)
                    else:
                        child.symlink_to(root / 'missing')
                    with patch('init_agent.metadata_db.sqlite3.connect') as connect:
                        with self.assertRaises(OSError):
                            GraphStore(root)
                        connect.assert_not_called()

    def test_sqlite_journal_and_wal_stay_in_validated_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ensure_agent_dir(root)
            with GraphStore(root) as store:
                store.initialize()
                store.connection.execute('PRAGMA journal_mode=WAL')
                store.connection.execute("INSERT INTO project_meta VALUES ('test', 'value')")
                store.connection.commit()
                self.assertTrue((root / '.agent/graph.sqlite-wal').is_file())
                self.assertEqual((root / '.agent/graph.sqlite-wal').stat().st_mode & 0o777, 0o600)
                self.assertEqual({p.name for p in root.iterdir()}, {'.agent'})

    def test_manual_scan_rejects_untrusted_index_paths_and_caps_work(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            root = parent / 'repo'
            root.mkdir()
            ensure_agent_dir(root)
            secret = parent / 'secret'
            secret.write_text('SECRET_OUTSIDE')
            (root / 'valid').write_text('abc')
            (root / 'link').symlink_to(secret)
            os.mkfifo(root / 'fifo')
            (root / 'large').write_bytes(b'x' * (256 * 1024 + 1))
            with closing(sqlite3.connect(root / '.agent/graph.sqlite')) as conn:
                conn.execute('CREATE TABLE files(path TEXT)')
                conn.executemany('INSERT INTO files VALUES (?)', [(p,) for p in ('valid', str(secret), '../secret', 'link', 'fifo', 'large')])
                conn.commit()
            result = measure_indexed_file_read(root)
            self.assertEqual(result['files'], 1)
            self.assertEqual(result['characters'], 3)
            self.assertEqual(result['bytes_read'], 3)
            self.assertEqual(result['rejected_files'], 5)
            self.assertTrue(result['truncated'])
            with closing(sqlite3.connect(root / '.agent/graph.sqlite')) as conn:
                conn.execute('DELETE FROM files')
                conn.executemany('INSERT INTO files VALUES (?)', [('valid',)] * 300)
                conn.commit()
            result = measure_indexed_file_read(root)
            self.assertEqual(result['files'], 256)
            self.assertTrue(result['truncated'])
