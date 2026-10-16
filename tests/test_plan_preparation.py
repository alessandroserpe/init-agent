"""Preparation must not spend a plan's work budget on a discarded ranking."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from init_agent.agent_tools import repo_reading_plan
from init_agent.graph_store import GraphStore
from init_agent.repo_budget import RepoBudget, budget_scope
from init_agent.run import prepare_repository, run_query


class PlanPreparationTests(unittest.TestCase):
    def test_full_plan_fits_budget_without_duplicate_context_search(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'pyproject.toml').write_text('[project]\nname="fixture"\n')
            for index in range(40):
                (root / f'service_{index}.py').write_text('\n'.join(
                    f'def validate_invoice_{j}(payment):\n    return dispatch_notification(payment)\n'
                    for j in range(30)
                ))
            prepare_repository(root)
            budget = RepoBudget()
            budget.limits['steps'] = 100_000
            with budget_scope(budget):
                result = repo_reading_plan(
                    root,
                    'Investigate invoice payment validation retry duplicate transaction notification '
                    'dispatch persistence checkout customer order lifecycle reconciliation refund '
                    'cancellation scheduling service integration behavior',
                    kind='experiment',
                )
            self.assertTrue(result['plan_items'])
            self.assertIsInstance(result['id'], int)
            self.assertLess(budget.used['steps'], budget.limits['steps'])
            with GraphStore(root) as store:
                self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM reading_plans').fetchone()[0], 1)

    def test_preparation_initializes_and_refreshes_without_searching(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'app.py').write_text('def initial_function():\n    pass\n')
            with patch('init_agent.run.build_context_pack', side_effect=AssertionError('unexpected search')):
                first = prepare_repository(root)
                (root / 'app.py').write_text('def replacement_function():\n    return 123\n')
                second = prepare_repository(root)
            self.assertEqual(first['init'], 'done')
            self.assertEqual(first['map'], 'done')
            self.assertEqual(second['refresh'], 'done')
            with GraphStore(root) as store:
                names = {row[0] for row in store.connection.execute('SELECT name FROM symbols')}
            self.assertIn('replacement_function', names)
            self.assertNotIn('initial_function', names)
            self.assertTrue(run_query(root, 'replacement function')['context']['candidate_files'])

    def test_failed_preparation_does_not_build_or_persist_a_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for stage in ('init', 'map'):
                with self.subTest(stage=stage):
                    preparation = {'init': 'skipped', 'map': 'skipped', 'warnings': ['fixture failure']}
                    preparation[stage] = 'failed'
                    with patch('init_agent.agent_tools.prepare_repository', return_value=preparation), \
                         patch('init_agent.agent_tools.build_reading_plan', side_effect=AssertionError('unexpected plan')):
                        result = repo_reading_plan(root, 'invoice validation')
                    self.assertIsNone(result['id'])
                    self.assertEqual(result['plan_items'], [])
                    self.assertIn('fixture failure', result['warnings'])
