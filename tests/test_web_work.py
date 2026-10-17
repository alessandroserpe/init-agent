import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from init_agent.tasks import add_task, close_task, update_task
from init_agent.task_checks import verify_task
from init_agent.graph_store import GraphStore
from init_agent.web_ui import build_web_snapshot, render_dashboard_html


class WebWorkTests(unittest.TestCase):
    def test_completed_checks_stay_visible_and_refresh_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'logic.py').write_text('x=1\n')
            (root/'test_logic.py').write_text('import unittest\nclass Case(unittest.TestCase):\n def test_x(self): self.assertTrue(True)\n')
            task = add_task(root, '<script>bad()</script>', files=['logic.py'])
            verify_task(root, task['id'], 'test_logic.Case')
            close_task(root, task['id'])
            database = root/'.agent/graph.sqlite'
            before = database.read_bytes()
            with patch('init_agent.task_checks.subprocess.run', side_effect=AssertionError('must not execute tests')):
                snapshot = build_web_snapshot(root)
            self.assertEqual(database.read_bytes(), before)
            self.assertEqual(snapshot['open_tasks'], [])
            self.assertEqual(snapshot['recent_checks'][0]['state'], 'passed')
            self.assertEqual(snapshot['recent_checks'][0]['task_status'], 'done')
            page = render_dashboard_html(snapshot)
            self.assertNotIn('<script>bad()</script>', page)
            self.assertIn('&lt;script&gt;bad()', page)
            (root/'logic.py').write_text('x=2\n')
            check = build_web_snapshot(root)['recent_checks'][0]
            self.assertEqual(check['state'], 'needs_rerun')
            self.assertEqual(check['changed_files'], ['logic.py'])
            self.assertEqual(check['run_state'], 'passed')

    def test_partial_scope_and_budget_never_claim_current_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'logic.py').write_text('x=1')
            (root/'test_logic.py').write_text('import unittest\nclass Case(unittest.TestCase):\n def test_x(self): pass\n')
            task=add_task(root,'Task',files=['logic.py'])
            verify_task(root,task['id'],'test_logic.Case')
            (root/'logic.py').write_bytes(b'x'*300000)
            self.assertEqual(build_web_snapshot(root)['recent_checks'][0]['state'], 'unknown')
            (root/'new.py').write_text('x=1')
            update_task(root,task['id'],files=['new.py'])
            self.assertEqual(build_web_snapshot(root)['recent_checks'][0]['state'], 'needs_rerun')
            with GraphStore(root) as store:
                store.connection.execute("UPDATE agent_task_checks SET evidence_json='{}'")
                store.connection.commit()
            self.assertEqual(build_web_snapshot(root)['recent_checks'][0]['state'], 'unknown')

    def test_older_store_and_accessible_rendering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            add_task(root,'Task')
            with GraphStore(root) as store:
                store.connection.execute('DROP TABLE agent_task_checks')
                store.connection.commit()
            snapshot=build_web_snapshot(root)
            self.assertEqual(snapshot['recent_checks'],[])
            with GraphStore(root) as store:
                self.assertIsNone(store.connection.execute("SELECT name FROM sqlite_master WHERE name='agent_task_checks'").fetchone())
            page=render_dashboard_html(snapshot)
            self.assertIn('role="tab"',page)
            self.assertIn('aria-controls="panel-checks"',page)
            self.assertIn('Evidence',render_dashboard_html({'recent_checks':[{'task_id':1,'test':'a.b','title':'test','state':'passed'}]}))
            self.assertIn('No saved test runs', page)
