import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from init_agent.graph_store import GraphStore
from init_agent.local_search import SEARCH_INDEX_VERSION, search, update_search_index
from init_agent.local_watch import Maintainer, maintenance_lock
from init_agent.memory import add_note
from init_agent.search_passages import passages


class SearchIndexMigrationTests(unittest.TestCase):
    def prepare(self, root):
        with maintenance_lock(root):
            Maintainer(root).tick()

    def state(self, root):
        with GraphStore(root) as store:
            return {table: [tuple(row) for row in store.connection.execute(f'SELECT * FROM {table} ORDER BY 1,2')]
                    for table in ('search_chunks', 'search_files', 'search_index_meta')}

    def legacy(self, root):
        with GraphStore(root) as store:
            store.connection.execute('DELETE FROM search_index_meta')
            store.connection.execute("UPDATE search_chunks SET names='legacy'")
            store.connection.commit()

    def test_unversioned_index_rebuilds_unchanged_files_and_preserves_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'a.py').write_text('def recoverArchive():\n'+'    x=1\n'*65+'    return "checksum mismatch"\n')
            self.prepare(root)
            note=add_note(root,None,'Keep the audit trail',scope='repo')
            self.legacy(root)
            result=update_search_index(root)
            self.assertTrue(result['rebuilt'])
            self.assertEqual(result['updated'],1)
            self.assertEqual(result['index_version'],SEARCH_INDEX_VERSION)
            self.assertIn('checksum mismatch',search(root,'recoverArchive checksum mismatch')['results'][0]['excerpt'])
            self.assertEqual(search(root,'audit')['memories'][0]['id'],note['id'])
            before=self.state(root)
            result=update_search_index(root)
            self.assertFalse(result['rebuilt'])
            self.assertEqual(result['updated'],0)
            self.assertEqual(before,self.state(root))

    def test_interrupted_rebuild_rolls_back_rows_hashes_and_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a.py').write_text('def first():\n    return 1\n')
            self.prepare(root);self.legacy(root);before=self.state(root)
            def broken(*args):
                yield next(passages(*args))
                raise RuntimeError('injected rebuild failure')
            with patch('init_agent.local_search.passages',side_effect=broken):
                with self.assertRaisesRegex(RuntimeError,'injected'):
                    update_search_index(root)
            self.assertEqual(before,self.state(root))
            self.assertTrue(update_search_index(root)['rebuilt'])

    def test_incremental_add_edit_delete_matches_full_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'a.py').write_text('def beforeName():\n    return "oldneedle"\n')
            (root/'removed.py').write_text('x="removedneedle"\n')
            self.prepare(root)
            (root/'a.py').write_text('def afterName():\n'+'    x=1\n'*40+'    return "newneedle"\n\ndef neighbor():\n    return "foreignneedle"\n')
            (root/'removed.py').unlink()
            (root/'added.py').write_text('def extra():\n    return 3\n')
            self.prepare(root)
            incremental=self.state(root)
            self.assertFalse(search(root,'oldneedle')['results'])
            self.assertFalse(search(root,'removedneedle')['results'])
            self.assertIn('newneedle',search(root,'afterName newneedle')['results'][0]['excerpt'])
            with GraphStore(root) as store:
                self.assertEqual(store.connection.execute("SELECT count(*) FROM search_chunks WHERE search_chunks MATCH 'after AND foreignneedle'").fetchone()[0],0)
                store.connection.execute('DELETE FROM search_index_meta');store.connection.commit()
            update_search_index(root)
            self.assertEqual(incremental,self.state(root))

    def test_future_version_is_not_downgraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a.py').write_text('x=1\n');self.prepare(root)
            with GraphStore(root) as store:
                store.connection.execute("UPDATE search_index_meta SET value=? WHERE key='version'",(SEARCH_INDEX_VERSION+1,));store.connection.commit()
            before=self.state(root)
            with self.assertRaisesRegex(ValueError,'newer'):
                update_search_index(root)
            self.assertEqual(before,self.state(root))

if __name__=='__main__':unittest.main()
