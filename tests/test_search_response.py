"""Response usefulness: complete decisions, bounded evidence, optional expansion."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from init_agent.local_search import search
from init_agent.local_watch import Maintainer, maintenance_lock
from init_agent.mcp_server import InitAgentMcpServer
from init_agent.search_passages import source_excerpt


class SearchResponseTests(unittest.TestCase):
    def test_short_decisions_are_complete_across_chunk_boundaries(self):
        cases = [('stale changed hash', 'stale'), ('retry exhausted attempts', 'retry'),
                 ('permission denied owner', 'permission')]
        for query, marker in cases:
            with self.subTest(query=query), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                body = (f'def check_{marker}(value):\n' + '    # context\n' * 23
                        + f'    if value == "{query}":\n'
                        + '        return False\n    return True\n')
                (root/'decision.py').write_text(body + '\ndef unrelated():\n    return 0\n')
                with maintenance_lock(root):
                    Maintainer(root).tick()
                hit = search(root, query, limit=1)['results'][0]
                self.assertEqual(hit['excerpt'], body.rstrip())
                self.assertTrue(hit['complete_symbol'])
                self.assertFalse(hit['excerpt_truncated'])
                self.assertEqual((hit['start_line'], hit['end_line']), (1, 27))
                self.assertLessEqual(len(hit['excerpt']), 1400)

    def test_default_avoids_paths_and_expansion_is_explicit_over_mcp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'note.py').write_text('def stale():\n    return "changed hash"\n\ndef delete_note():\n    return stale()\n')
            server = InitAgentMcpServer(root)
            def call(**options):
                response = server.handle({'jsonrpc':'2.0','id':1,'method':'tools/call',
                    'params':{'name':'repo_search','arguments':{'query':'changed hash', **options}}})['result']
                self.assertFalse(response['isError'])
                return response['structuredContent']
            with patch('init_agent.local_search.call_paths', side_effect=AssertionError('unrequested expansion')):
                compact = call()
            self.assertEqual(compact['call_paths'], [])
            self.assertTrue(all(not hit['graph_links'] for hit in compact['results']))
            expanded = call(include_relations=True)
            self.assertTrue(expanded['call_paths'])
            self.assertEqual(compact['results'][0]['excerpt'], expanded['results'][0]['excerpt'])

    def test_large_function_keeps_matching_evidence_and_does_not_claim_completeness(self):
        lines = ['def large():'] + ['    value = "' + 'x'*150 + '"']*30 + ['    return "needle"']
        first, last, text, truncated, complete = source_excerpt(lines, 32, {'line':1,'end_line':32})
        self.assertIn('needle', text)
        self.assertFalse(complete)
        self.assertLessEqual(len(text), 1400)
        self.assertEqual(text, '\n'.join(lines[first-1:last]))

    def test_long_preceding_lines_do_not_hide_match(self):
        lines = ['x'*2000]*3 + ['needle']
        first, last, text, truncated, complete = source_excerpt(lines, 4)
        self.assertEqual((first,last,text), (4,4,'needle'))
        self.assertFalse(complete)

    def test_nested_scope_and_import_are_not_expanded_to_neighbor(self):
        lines = ['import package', 'def outer():', '    def inner():', '        return 1', '    return inner()']
        self.assertEqual(source_excerpt(lines,4,{'line':3,'end_line':4})[2], '\n'.join(lines[2:4]))
        self.assertFalse(source_excerpt(lines,1)[4])
