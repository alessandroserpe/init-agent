import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from init_agent.cli import main
from init_agent.tasks import add_task, get_task, list_tasks, update_task
from init_agent.task_checks import verify_task
from init_agent.agent_tools import repo_task_list
from init_agent.session_tools import repo_session_summary
from init_agent.renderers import render_repo_task_list_text


class TaskChecksTests(unittest.TestCase):
    def test_cli_records_and_normal_retrieval_revalidates_without_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'logic.py').write_text('x=1\n')
            (root / 'test_case.py').write_text('import unittest\nclass Case(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n')
            task = add_task(root, 'Fix behavior', files=['logic.py'])
            previous = Path.cwd()
            out = StringIO()
            try:
                os.chdir(root)
                with redirect_stdout(out):
                    self.assertEqual(main(['task', 'verify', str(task['id']), '--test', 'test_case.Case', '--json']), 0)
            finally:
                os.chdir(previous)
            record = json.loads(out.getvalue())
            self.assertEqual(set(record['files']), {'logic.py', 'test_case.py'})
            with patch('init_agent.task_checks.subprocess.run', side_effect=AssertionError('Retrieval must not run tests')):
                recovered = get_task(root, task['id'])
                self.assertEqual(recovered['status'], 'open')
                self.assertEqual(recovered['checks'][0]['state'], 'passed')
                self.assertEqual(repo_session_summary(root)['recent_tasks'][0]['checks'][0]['state'], 'passed')
                self.assertNotIn('output', recovered['checks'][0])
                (root / 'logic.py').write_text('x=2\n')
                result = repo_task_list(root)
                self.assertEqual(result['tasks'][0]['checks'][0]['state'], 'needs_rerun')
                self.assertIn('[needs_rerun]', render_repo_task_list_text(result))
                self.assertEqual(get_task(root, task['id'])['checks'][0]['changed_files'], ['logic.py'])
            second = verify_task(root, task['id'], 'test_case.Case')
            self.assertEqual(second['id'], record['id'])
            self.assertEqual(len(list_tasks(root)[0]['checks']), 1)
            (root / 'extra.py').write_text('x=3')
            update_task(root, task['id'], files=['extra.py'])
            check = get_task(root, task['id'])['checks'][0]
            self.assertEqual(check['state'], 'needs_rerun')
            self.assertEqual(check['uncovered_files'], ['extra.py'])

    def test_missing_context_never_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = add_task(root, 'No scope')
            with patch('init_agent.task_checks.subprocess.run', side_effect=AssertionError('Unexpected run')):
                for task_id in [task['id'], task['id'] + 1]:
                    with self.assertRaises(ValueError):
                        verify_task(root, task_id, 'test_case.Case')

    def test_scope_rejects_nonregular_and_escaping_files(self):
        from init_agent.task_checks import fingerprints
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                fingerprints(root, ['../outside'])
            os.mkfifo(root / 'pipe')
            with self.assertRaises(OSError):
                fingerprints(root, ['pipe'])
