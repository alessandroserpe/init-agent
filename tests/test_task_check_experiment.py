import tempfile
import unittest
from pathlib import Path

from init_agent.task_checks import run_check, check_status


class TaskCheckExperimentTests(unittest.TestCase):
    def test_pass_stale_deleted_and_stable_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'test_case.py').write_text('import unittest\nclass Case(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n')
            source = root / 'logic.py'
            source.write_text('x=1\n')
            record = run_check(root, 14, 'test_case.Case.test_ok', ['logic.py'])
            self.assertEqual(record['state'], 'passed')
            self.assertFalse(record['task_closed'])
            self.assertIn('test_case.py', record['files'])
            self.assertEqual(check_status(root, record)['state'], 'passed')
            source.write_text('x=2\n')
            self.assertEqual(check_status(root, record)['state'], 'needs_rerun')
            rerun = run_check(root, 14, 'test_case.Case.test_ok', ['logic.py'])
            self.assertEqual(record['id'], rerun['id'])
            source.unlink()
            self.assertEqual(check_status(root, rerun)['state'], 'needs_rerun')

    def test_failure_skip_empty_timeout_and_changes_during_run(self):
        bodies = {
            'failure': (' def test_x(self): self.fail()\n', 'not_verified'),
            'skip': (' @unittest.skip("not available")\n def test_x(self): pass\n', 'not_verified'),
            'empty': (' pass\n', 'not_verified'),
            'timeout': (' def test_x(self): __import__("time").sleep(2)\n', 'timeout'),
            'mutated': (' def test_x(self):\n  from pathlib import Path\n  Path("logic.py").write_text("changed")\n', 'needs_rerun'),
        }
        for name, (body, expected) in bodies.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'logic.py').write_text('initial')
                (root / 'test_case.py').write_text('import unittest\nclass Case(unittest.TestCase):\n' + body)
                record = run_check(root, 14, 'test_case.Case', ['logic.py'], timeout=0.5 if name == 'timeout' else 5)
                self.assertEqual(record['state'], expected)
                self.assertFalse(record['task_closed'])
