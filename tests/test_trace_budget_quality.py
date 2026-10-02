"""Trace must spend its budget discovering files, not duplicate routes."""
from pathlib import Path
import tempfile
import unittest

from init_agent.read_budget import ReadBudget
from init_agent.trace import _trace_from


class TraceBudgetQualityTests(unittest.TestCase):
    def test_dense_routes_leave_budget_for_later_starts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = {i: {'path': f'module_{i}.py', 'role': 'source'} for i in range(43)}
            for item in files.values():
                (root / item['path']).write_text('querytoken = 1\n')
            layers = [[0], *[list(range(1 + layer * 8, 9 + layer * 8)) for layer in range(5)]]
            graph = {}
            for current, following in zip(layers, layers[1:]):
                for source in current:
                    graph[source] = [{'target': target, 'relation': 'imports', 'confidence': 1.0} for target in following]
            graph[41] = [{'target': 42, 'relation': 'imports', 'confidence': 1.0}]
            budget = ReadBudget(max_states=1000)
            first = _trace_from(root, 0, graph, files, {'querytoken'}, 6, budget)
            second = _trace_from(root, 41, graph, files, {'querytoken'}, 6, budget)
            self.assertEqual(len(first), 41)
            self.assertEqual(len({item['target'] for item in first}), 41)
            self.assertEqual(budget.states, 43)
            self.assertFalse(budget.truncated)
            self.assertIn('module_42.py', [item['target'] for item in second])
            for item in first:
                self.assertEqual(len(item['edges']), item['distance'])
                self.assertEqual(len(item['path']), item['distance'] + 1)

    def test_converging_and_cyclic_paths_keep_shortest_real_route(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = {i: {'path': f'{i}.py', 'role': 'source'} for i in range(4)}
            for item in files.values():
                (root / item['path']).write_text('querytoken = 1\n')
            graph = {i: [{'target': t, 'relation': 'imports', 'confidence': 1.0} for t in targets]
                     for i, targets in {0: [1, 2], 1: [2, 3], 2: [0, 3], 3: [1]}.items()}
            budget = ReadBudget()
            paths = _trace_from(root, 0, graph, files, {'querytoken'}, 6, budget)
            indexed = {p['target']: p for p in paths}
            self.assertEqual(budget.states, 4)
            self.assertEqual(indexed['2.py']['distance'], 1)
            self.assertEqual(indexed['3.py']['distance'], 2)
            for item in paths:
                for source, target in zip(item['path'], item['path'][1:]):
                    a, b = int(Path(source).stem), int(Path(target).stem)
                    self.assertIn(b, [edge['target'] for edge in graph[a]])
