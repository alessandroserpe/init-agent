"""A local definition must not be attributed to an imported production function."""
from pathlib import Path
import tempfile
import unittest

from init_agent.test_evidence import find_tests


class LocalDefinitionTests(unittest.TestCase):
    def test_local_definitions_shadow_import_but_unrelated_async_helper_does_not(self):
        for definition, expected in (
            ('def decide(): return 1', False),
            ('async def decide(): return 1', False),
            ('class decide: pass', False),
            ('async def helper(): return 1', True),
        ):
            with self.subTest(definition=definition), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root/'tests').mkdir()
                (root/'tests/test_sample.py').write_text(
                    'from package.logic import decide\n'
                    'def test_decision():\n'
                    f'    {definition}\n'
                    '    assert decide()\n')
                result = find_tests(root, 'package.logic', 'decide')
                self.assertEqual(bool(result['candidates']), expected)
