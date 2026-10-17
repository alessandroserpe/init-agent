from pathlib import Path
import tempfile
import unittest

from init_agent.graph_store import GraphStore
from init_agent.scanner import scan_project
from init_agent.refresh import refresh_index
from init_agent.evidence_trace import trace_evidence
from init_agent.utils import ensure_agent_dir


class EvidenceTraceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        ensure_agent_dir(self.root)

    def write(self, path, text):
        (self.root/path).write_text(text)

    def scan(self):
        with GraphStore(self.root) as store:
            store.initialize()
            scan_project(self.root, store)

    def trace(self, symbol='run', **kw):
        return trace_evidence(self.root, [], anchor={'path':'main.py', 'symbol':symbol}, **kw)

    def test_import_alias_path_has_exact_endpoints_and_freshness(self):
        self.write('main.py', 'from helper import work as alias\ndef run():\n    return alias()\n')
        self.write('helper.py', 'def work():\n    return 1\n')
        self.scan()
        result = self.trace()
        self.assertEqual(len(result['paths']), 1, result)
        edge = result['paths'][0]['resolved_edges'][0]
        self.assertEqual((edge['from'], edge['line'], edge['to'], edge['target_symbol'], edge['target_line']), ('main.py',3,'helper.py','work',1))
        self.assertEqual(len(edge['source_sha256']),64)
        self.write('helper.py', 'def other():\n    return 2\n')
        self.assertEqual(self.trace()['paths'], [])
        refresh_index(self.root)
        self.assertEqual(self.trace()['paths'], [])
        (self.root/'helper.py').unlink()
        refresh_index(self.root)
        self.assertEqual(self.trace()['paths'], [])

    def test_shadowed_and_dynamic_receivers_are_not_resolved(self):
        for code in (
            'def work():\n    pass\ndef run(work):\n    work()\n',
            'def work():\n    pass\ndef run(obj):\n    obj.work()\n',
            'def work():\n    pass\ndef run():\n    work = lambda: 2\n    work()\n',
            'class A:\n    def work(self):\n        pass\ndef run():\n    work()\n',
        ):
            with self.subTest(code=code):
                self.write('main.py',code)
                self.scan()
                self.assertEqual(self.trace()['paths'], [])

    def test_nested_lexical_call_and_depth_boundary(self):
        self.write('main.py','def run():\n    def inner():\n        return 1\n    return inner()\n')
        self.scan()
        result=self.trace(max_depth=1)
        self.assertEqual(result['paths'][0]['resolved_edges'][0]['target_symbol'],'run.inner')
        self.assertTrue(any(g['reason']=='depth_limit' for g in result['gaps']))

    def test_unsupported_file_reports_gap(self):
        self.write('main.py','def broken(:\n    work()\n')
        self.scan()
        result=self.trace(symbol='')
        self.assertEqual(result['paths'],[])
        self.assertEqual(result['gaps'][0]['reason'],'structural_analysis_unavailable')

    def test_typescript_index_trace_and_dependency_invalidation(self):
        from init_agent.typescript_analyzer import COMPILER
        import shutil
        if not COMPILER.is_file() or not shutil.which('node'):
            self.skipTest('optional pinned TypeScript compiler unavailable')
        self.write('main.ts', 'import { work } from "./helper.js";\nexport function run() { return work(); }\n')
        self.write('helper.ts', 'export function work() { return 1; }\n')
        self.scan()
        def traced():
            return trace_evidence(self.root, [], anchor={'path':'main.ts','symbol':'run'})
        result=traced()
        self.assertTrue(result['paths'], result)
        edge=result['paths'][0]['resolved_edges'][0]
        self.assertEqual((edge['to'],edge['target_symbol'],edge['line']),('helper.ts','work',2))
        self.write('helper.ts','export function different() { return 2; }\n')
        self.assertFalse(traced()['paths'])
        updated=refresh_index(self.root)
        self.assertIn('main.ts',updated['updated'])
        self.assertFalse(traced()['paths'])

    def test_output_limit_and_dynamic_hints(self):
        self.write('main.py','def run(obj):\n    obj.work()\n')
        self.scan()
        result=self.trace()
        self.assertFalse(result['paths'])
        self.assertTrue(result['hints'])
        self.assertFalse(result['hints'][0]['resolved'])

    def test_oversized_source_reports_work_limit(self):
        self.write('main.py','def run():\n    pass\n#'+'x'*270000)
        self.scan()
        result=self.trace()
        self.assertFalse(result['paths'])
        self.assertTrue(result['work_budget']['truncated'])

    def test_python_imports_remain_case_sensitive(self):
        self.write('main.py','from helper import work\ndef run():\n    work()\n')
        self.write('helper.py','def Work():\n    pass\n')
        self.scan()
        self.assertFalse(self.trace()['paths'])

    def test_duplicate_qualified_scopes_are_ambiguous(self):
        self.write('main.py','from helper import work\ndef run():\n    return work()\ndef run(work):\n    return work()\n')
        self.write('helper.py','def work():\n    return 1\n')
        self.scan()
        self.assertFalse(self.trace()['paths'])
        self.assertEqual(self.trace()['gaps'][0]['reason'],'ambiguous_anchor')
        self.assertFalse([p for p in self.trace(symbol='')['paths'] if any(e['relation']=='calls' for e in p['resolved_edges'])])
