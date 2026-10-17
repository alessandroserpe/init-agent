import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from init_agent.index_health import index_readiness
from init_agent.session_tools import repo_session_close


class IndexGuidanceTests(unittest.TestCase):
    def test_drift_is_conditional_but_inspection_errors_still_need_attention(self):
        for status in ('ready', 'stale', 'missing', 'empty', 'error'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                summary = {'index_health': {'status': status}, 'git': {'status': []},
                           'memory_audit': {'summary': {}}, 'recent_tasks': []}
                with patch('init_agent.session_tools.repo_session_summary', return_value=summary):
                    result = repo_session_close(Path(tmp))
                refresh = next(item for item in result['checklist'] if item['id'] == 'refresh_repository_index')
                self.assertEqual(result['close_ready'], status != 'error')
                self.assertEqual(refresh['status'], 'needed' if status == 'error' else ('clean' if status == 'ready' else 'optional'))
                if status in {'stale', 'missing', 'empty'}:
                    self.assertIn('repo_search', refresh['reason'])
                    self.assertIn('Task retrieval', refresh['reason'])
                else:
                    self.assertEqual(refresh['command'], '')

    def test_missing_index_guidance_does_not_create_an_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = index_readiness(root, use_cache=False)
            self.assertFalse(result['ready'])
            self.assertIn('repo_search prepares its index automatically', result['warnings'][0])
            self.assertIn('Before using graph orientation', result['warnings'][0])
            self.assertFalse((root / '.agent').exists())

    def test_other_handoff_issues_still_block_readiness(self):
        for issue in ({'git': {'status': [' M logic.py']}},
                      {'recent_tasks': [{'id': 1}]},
                      {'memory_audit': {'summary': {'stale': 1}}}):
            with self.subTest(issue=issue), tempfile.TemporaryDirectory() as tmp:
                summary = {'index_health': {'status': 'stale'}, 'git': {'status': []},
                           'memory_audit': {'summary': {}}, 'recent_tasks': [], **issue}
                with patch('init_agent.session_tools.repo_session_summary', return_value=summary), \
                     patch('init_agent.session_tools._session_suggestions', return_value=([], [])):
                    self.assertFalse(repo_session_close(Path(tmp))['close_ready'])
