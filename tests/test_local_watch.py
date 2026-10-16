import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from init_agent.graph_store import GraphStore
from init_agent.local_watch import Maintainer, maintenance_lock
from init_agent.run import prepare_repository


def graph(root):
    with GraphStore(root) as store:
        files = sorted(store.file_hashes().items())
        symbols = sorted(tuple(r) for r in store.connection.execute(
            'SELECT f.path,s.name,s.kind,s.signature FROM symbols s JOIN files f ON f.id=s.file_id'))
        edges = sorted(tuple(r) for r in store.connection.execute(
            "SELECT f.path,r.relation,r.target_type,r.target_id FROM relations r JOIN files f ON f.id=r.source_id WHERE r.source_type='file' AND r.target_type='resolved_file'"))
    return files, symbols, edges


class LocalWatchTests(unittest.TestCase):
    def assert_clean_equivalent(self, root):
        with tempfile.TemporaryDirectory() as tmp:
            clean = Path(tmp)
            for p in root.glob('*.py'):
                (clean / p.name).write_bytes(p.read_bytes())
            prepare_repository(clean)
            self.assertEqual(graph(root), graph(clean))

    def test_changes_match_full_map_and_idle_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'main.py').write_text('from worker import execute\ndef main():\n    return execute()\n')
            with maintenance_lock(root):
                worker = Maintainer(root)
                self.assertEqual(worker.tick()['status'], 'ready')
                worker.tick()  # Settle newly created configuration metadata.
                db = root/'.agent/graph.sqlite'
                before = db.read_bytes()
                self.assertIsNone(worker.tick())
                self.assertEqual(before, db.read_bytes())
                # Resolves an import that was previously unresolved.
                (root/'worker.py').write_text('def execute():\n    return 1\n')
                self.assertIn('worker.py', worker.tick()['paths']['added'])
                self.assert_clean_equivalent(root)
                # Same-size edit with mtime restored must still be detected.
                p=root/'worker.py'; stat=p.stat()
                p.write_text('def execute():\n    return 2\n')
                os.utime(p, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                self.assertIn('worker.py', worker.tick()['paths']['updated'])
                self.assert_clean_equivalent(root)
                p.rename(root/'renamed.py')
                (root/'main.py').write_text('from renamed import execute\ndef main():\n    return execute()\n')
                event=worker.tick()
                self.assertIn('worker.py',event['paths']['removed'])
                self.assertIn('renamed.py',event['paths']['added'])
                self.assert_clean_equivalent(root)
                (root/'renamed.py').unlink()
                worker.tick()
                self.assert_clean_equivalent(root)
                records=[json.loads(l) for l in (root/'.agent/maintenance.jsonl').read_text().splitlines()]
                self.assertEqual(records[-1]['counts']['removed'],1)

    def test_reconcile_catches_missed_poll_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'a.py').write_text('a=1\n')
            with maintenance_lock(root):
                worker=Maintainer(root);worker.tick();worker.tick()
                old=worker.previous
                (root/'a.py').write_text('a=2\n')
                worker.last_reconcile=-1000
                with patch('init_agent.local_watch.fingerprint',return_value=old):
                    self.assertIn('a.py',worker.tick()['paths']['updated'])
            (root/'a.py').write_text('a=3\n')
            with maintenance_lock(root):
                event=Maintainer(root).tick()
                self.assertEqual(event['reason'],'startup')
                self.assertIn('a.py',event['paths']['updated'])

    def test_refresh_preserves_memory_evidence_and_serves_updated_symbols(self):
        from init_agent.memory import add_note, list_notes
        from init_agent.agent_tools import repo_symbol_callers
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'app.py').write_text('def old_name(): return 1\n')
            with maintenance_lock(root):
                worker=Maintainer(root);worker.tick()
                note=add_note(root,'app.py','The entry function is old_name',evidence='read_full_file')
                (root/'app.py').write_text('def new_name(): return 2\n')
                worker.tick()
                notes=list_notes(root)
                self.assertTrue(notes[0]['stale'])
                self.assertEqual(notes[0]['file_sha256'],note['file_sha256'])
                self.assertTrue(repo_symbol_callers(root,'new_name',prepare=False)['definitions'])
                self.assertFalse(repo_symbol_callers(root,'old_name',prepare=False)['definitions'])

    def test_lock_excludes_second_worker_and_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with maintenance_lock(root):
                with self.assertRaisesRegex(RuntimeError,'already owns'):
                    with maintenance_lock(root):pass
            with maintenance_lock(root):pass

    def test_live_process_updates_without_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'app.py').write_text('def before(): pass\n')
            with open(root/'output.log','w') as log:
                process=subprocess.Popen([sys.executable,'-m','init_agent.local_watch','--root',str(root),'--interval','0.1'],stdout=log,stderr=log)
                try:
                    def wait_for(name):
                        deadline=time.monotonic()+8
                        while time.monotonic()<deadline:
                            if process.poll() is not None:self.fail('worker exited: '+(root/'output.log').read_text())
                            if (root/'.agent/graph.sqlite').exists():
                                try:
                                    if any(s[1]==name for s in graph(root)[1]):return
                                except Exception:pass
                            time.sleep(.05)
                        self.fail('update timed out')
                    wait_for('before')
                    (root/'app.py').write_text('def after(): pass\n')
                    wait_for('after')
                finally:
                    process.send_signal(__import__('signal').SIGINT)
                    process.wait(timeout=5)
                self.assertEqual(process.returncode,0)


if __name__=='__main__':unittest.main()
