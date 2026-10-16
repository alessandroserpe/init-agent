import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from init_agent.graph_store import GraphStore
from init_agent.local_search import search
from init_agent.local_watch import Maintainer, maintenance_lock
from init_agent.run import prepare_repository


class TypedReceiverTests(unittest.TestCase):
    def fixture(self, root, body):
        (root/'pkg').mkdir()
        (root/'pkg/__init__.py').write_text('')
        (root/'pkg/worker.py').write_text('class Worker:\n    def send(self):\n        return "delivery confirmed"\n\nclass Other:\n    def send(self): return 2\n')
        (root/'pkg/use.py').write_text(body)
        with contextlib.redirect_stdout(io.StringIO()):prepare_repository(root)

    def edges(self, root):
        with GraphStore(root) as store:
            return [dict(r) for r in store.connection.execute("SELECT s.qualified_name AS source,t.qualified_name AS target,f.path AS target_path,r.metadata_json FROM relations r JOIN symbols s ON s.id=r.source_id JOIN symbols t ON t.id=CAST(r.target_id AS INTEGER) JOIN files f ON f.id=t.file_id WHERE r.source_type='symbol' AND r.target_type='resolved_symbol' AND r.relation='calls' AND t.name='send'")]

    def test_constructor_annotation_alias_module_and_homonyms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.fixture(root, 'from .worker import Worker as Courier\nfrom . import worker as mod\n'
                         'def checkout():\n    c = Courier()\n    return c.send()\n'
                         'def annotated(c: Courier):\n    return c.send()\n'
                         'def qualified(c: mod.Worker):\n    return c.send()\n')
            edges=self.edges(root)
            self.assertEqual({e['source'] for e in edges},{'checkout','annotated','qualified'})
            self.assertTrue(all(e['target']=='Worker.send' for e in edges))
            self.assertTrue(all(json.loads(e['metadata_json'])['resolver']=='python_typed_receiver' for e in edges))
            with contextlib.redirect_stdout(io.StringIO()),maintenance_lock(root):Maintainer(root).tick()
            paths=search(root,'checkout')['call_paths']
            self.assertEqual(paths[0]['edges'][0]['callee']['symbol'],'Worker.send')

    def test_unknown_rebound_conditional_and_shadowed_receivers_abstain(self):
        cases = {
            'unknown': 'def work(c):\n    return c.send()\n',
            'rebound': 'def work(c: Worker):\n    c = Other()\n    return c.send()\n',
            'later_rebound': 'def work(c: Worker):\n    c.send()\n    c = Other()\n',
            'conditional': 'def work(flag):\n    if flag:\n        c = Worker()\n    return c.send()\n',
            'factory': 'def work():\n    c = factory()\n    return c.send()\n',
            'loop': 'def work(c: Worker, items):\n    for c in items:\n        c.send()\n',
            'closure': 'def work():\n    c = Worker()\n    def inner():\n        return c.send()\n    return inner\n',
            'shadow_type': 'def work(Worker):\n    c = Worker()\n    return c.send()\n',
            'outer_shadow_type': 'def outer(Worker):\n    def work(c: Worker):\n        return c.send()\n    return work\n',
            'before_assignment': 'def work():\n    c.send()\n    c = Worker()\n',
            'deleted': 'def work(c: Worker):\n    del c\n    return c.send()\n',
            'nonlocal': 'def outer():\n    c = Worker()\n    def work():\n        nonlocal c\n        return c.send()\n    return work\n',
            'module_shadow': 'Worker = Other\ndef work(c: Worker):\n    return c.send()\n',
            'nested_attribute': 'def work(c: Worker):\n    return c.child.send()\n',
            'overridden_method': 'def work(c: Worker):\n    c.send = other\n    return c.send()\n',
            'module_overridden_method': 'Worker.send = other\ndef work(c: Worker):\n    return c.send()\n',
        }
        for label,body in cases.items():
            with self.subTest(case=label),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);self.fixture(root,'from .worker import Worker, Other\n'+body)
                self.assertEqual(self.edges(root),[])

    def test_local_class_and_duplicate_class_definitions(self):
        for duplicate in (False,True):
            with self.subTest(duplicate=duplicate),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                extra='class Worker:\n    def send(self): return 2\n' if duplicate else ''
                self.fixture(root,'class Worker:\n    def send(self): return 1\n'+extra+'def work():\n    c = Worker()\n    return c.send()\n')
                self.assertEqual(len(self.edges(root)),0 if duplicate else 1)

    def test_refresh_removes_old_edge_and_version_rebuild_preserves_notes(self):
        from init_agent.memory import add_note, list_notes
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root,'from .worker import Worker\ndef work(c: Worker):\n    return c.send()\n')
            self.assertEqual(len(self.edges(root)),1)
            note=add_note(root,'pkg/use.py','Verified typed receiver')
            with GraphStore(root) as store:
                store.set_meta('index_version','11')
                store.connection.commit()
            with contextlib.redirect_stdout(io.StringIO()):result=prepare_repository(root)
            self.assertEqual(result['map'],'done')
            self.assertEqual(list_notes(root)[0]['id'],note['id'])
            (root/'pkg/use.py').write_text('def work(c):\n    return c.send()\n')
            with contextlib.redirect_stdout(io.StringIO()):prepare_repository(root)
            self.assertEqual(self.edges(root),[])

if __name__=='__main__':unittest.main()
