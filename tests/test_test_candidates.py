"""Optional MCP/CLI test evidence must be read-only and bounded."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from init_agent.mcp_server import InitAgentMcpServer
from init_agent.test_evidence import find_tests


class TestCandidatesTests(unittest.TestCase):
    def fixture(self, root, source=None):
        (root/'tests').mkdir()
        (root/'tests/test_work.py').write_text(source or
            'raise RuntimeError("must not import tests")\n'
            'from package.logic import decide\nimport unittest\n'
            'class WorkTests(unittest.TestCase):\n'
            '    def test_decision(self):\n        self.assertEqual(decide(1), 2)\n')

    def call(self, root, arguments):
        return InitAgentMcpServer(root).handle({'jsonrpc':'2.0','id':1,'method':'tools/call',
            'params':{'name':'repo_test_candidates','arguments':arguments}})['result']

    def test_mcp_and_cli_without_preparation_or_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            response=self.call(root,{'module':'package.logic','symbol':'decide'})
            self.assertFalse(response['isError'])
            result=response['structuredContent']
            self.assertEqual(result['candidates'][0]['command_candidate'],
                ['python3','-m','unittest','tests.test_work.WorkTests.test_decision'])
            self.assertEqual(result['candidates'][0]['assertion_lines'],[6])
            self.assertFalse((root/'.agent').exists())
            # Exercise CLI parser/dispatch with an isolated cwd and explicit source import path.
            command=[sys.executable,'-c',
                'import sys;sys.path.insert(0,sys.argv.pop(1));from init_agent.cli import main;raise SystemExit(main())',
                str(Path(__file__).resolve().parents[1]),'tool','repo_test_candidates',
                '--module','package.logic','--symbol','decide','--json']
            cli=subprocess.run(command,cwd=root,capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(cli.stdout)['candidates'][0]['test'],'WorkTests.test_decision')
            self.assertFalse((root/'.agent').exists())

    def test_validation_and_missing_direct_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            for args in ({}, {'module':'../a','symbol':'x'}, {'module':'a','symbol':'C.method'},
                         {'module':'a','symbol':'x','limit':True}, {'module':'a','symbol':'x','extra':1}):
                with self.subTest(args=args):self.assertTrue(self.call(root,args)['isError'])
            self.assertEqual(find_tests(root,'package.logic','missing')['status'],'no_direct_test_found')
            self.assertFalse((root/'.agent').exists())

    def test_shadowed_captures_and_source_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            first=find_tests(root,'package.logic','decide')['candidates'][0]['sha256']
            p=root/'tests/test_work.py'
            p.write_text(p.read_text()+'# changed\n')
            self.assertNotEqual(first,find_tests(root,'package.logic','decide')['candidates'][0]['sha256'])
            p.write_text('from package.logic import decide\ndef test_choice():\n'
                         '    try: pass\n    except Exception as decide:\n        assert decide(1)\n')
            self.assertFalse(find_tests(root,'package.logic','decide')['candidates'])

    def test_output_and_unparseable_files_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            (root/'tests/bad.py').write_text('def invalid(:\n')
            for index in range(5):
                (root/f'tests/test_{index}.py').write_text('from package.logic import decide\ndef test_choice():\n'
                    +'    # '+('x'*6500)+'\n    assert decide(1)\n')
            result=find_tests(root,'package.logic','decide',limit=5)
            self.assertLessEqual(len(json.dumps(result,ensure_ascii=False)),24000)
            self.assertTrue(result['truncated'])
            self.assertIn('tests/bad.py',result['skipped_paths'])
            self.assertTrue(result['warnings'])
