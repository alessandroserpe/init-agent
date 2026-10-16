import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from init_agent.mcp_server import InitAgentMcpServer
from init_agent.memory import add_note
from init_agent.local_watch import maintenance_lock


class McpLocalSearchTests(unittest.TestCase):
    def call(self, server, query='checksum', **kwargs):
        return server.handle({'jsonrpc':'2.0','id':1,'method':'tools/call',
            'params':{'name':'repo_search','arguments':{'query':query,**kwargs}}})['result']

    def test_lazy_initialization_updates_notes_deletion_and_idle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'worker.py'
            p.write_text('def restoreArchive():\n'+'    x=1\n'*50+'    return "checksum mismatch"\n')
            server=InitAgentMcpServer(root)
            server.handle({'jsonrpc':'2.0','id':0,'method':'tools/list'})
            self.assertFalse((root/'.agent').exists())
            stdout=io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result=self.call(server,'restoreArchive checksum mismatch')
            self.assertEqual(stdout.getvalue(),'')
            self.assertFalse(result['isError'])
            self.assertIn('checksum mismatch',result['structuredContent']['results'][0]['excerpt'])
            note=add_note(root,'worker.py','Checksum decision retained for audit')
            self.call(server)  # settle initialization config fingerprint
            before=(root/'.agent/graph.sqlite').read_bytes()
            with patch('init_agent.local_watch.prepare_repository',side_effect=AssertionError('idle rebuild')):
                idle=self.call(server)
            self.assertEqual(idle['structuredContent']['maintenance']['status'],'unchanged')
            self.assertEqual(before,(root/'.agent/graph.sqlite').read_bytes())
            self.assertEqual(idle['structuredContent']['memories'][0]['id'],note['id'])
            p.write_text(p.read_text().replace('checksum mismatch','journal recovered'))
            updated=self.call(server,'journal recovered')['structuredContent']
            self.assertIn('journal recovered',updated['results'][0]['excerpt'])
            old=self.call(server,'checksum')['structuredContent']
            self.assertFalse(old['results'])
            self.assertTrue(old['memories'][0]['stale'])
            p.unlink()
            self.assertFalse(self.call(server,'journal')['structuredContent']['results'])

    def test_invalid_requests_do_not_create_metadata(self):
        for arguments in ({'query':''},{'query':'x'*1001},{'query':['x']},
                          {'query':'x','limit':True},{'query':'x','limit':11},
                          {'query':'x','path_prefixes':['../']},
                          {'query':'x','path_prefixes':'src'},
                          {'query':'x','unexpected':1}):
            with self.subTest(arguments=arguments), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);server=InitAgentMcpServer(root)
                query=arguments.pop('query')
                self.assertTrue(self.call(server,query,**arguments)['isError'])
                self.assertFalse((root/'.agent').exists())

    def test_contention_and_failed_preparation_return_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a.py').write_text('x=1\n');server=InitAgentMcpServer(root)
            with maintenance_lock(root):
                self.assertTrue(self.call(server)['isError'])
            failure={'status':'error','preparation':{'warnings':['failed']}}
            with patch('init_agent.search_tool.Maintainer.tick',return_value=failure), patch('init_agent.search_tool.search') as retrieval:
                self.assertTrue(self.call(server)['isError'])
                retrieval.assert_not_called()
            self.assertFalse(self.call(server)['isError'])

    def test_partial_index_warning_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a.py').write_text('x="checksum"\n');server=InitAgentMcpServer(root)
            self.call(server)
            event={'status':'warning','preparation':{'warnings':['parser incomplete']},'search_index':{'skipped_count':1}}
            with patch('init_agent.search_tool.Maintainer.tick',return_value=event):
                result=self.call(server)['structuredContent']
            self.assertIn('parser incomplete',result['warnings'])
            self.assertTrue(any('incomplete' in w for w in result['warnings']))

    def test_work_budget_failure_returns_explicit_incomplete_result(self):
        from init_agent.repo_budget import CURRENT_BUDGET, RepoBudget
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a.py').write_text('x="checksum"\n')
            server=InitAgentMcpServer(root)
            budget=RepoBudget();budget.limits['steps']=0
            token=CURRENT_BUDGET.set(budget)
            try:
                result=self.call(server)
            finally:
                CURRENT_BUDGET.reset(token)
            self.assertTrue(result['isError'])
            self.assertTrue(result['structuredContent']['truncated'])
            self.assertFalse(self.call(server)['isError'])

    def test_real_stdio_server_first_call_is_valid_json_and_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a.py').write_text('x="checksum"\n')
            requests=[{'jsonrpc':'2.0','id':1,'method':'tools/list'},
                      {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'repo_search','arguments':{'query':'checksum','limit':1}}}]
            proc=subprocess.run([sys.executable,'-m','init_agent.mcp_server','--root',str(root)],
                input=''.join(json.dumps(r)+'\n' for r in requests),capture_output=True,text=True,timeout=30,check=True)
            responses=[json.loads(line) for line in proc.stdout.splitlines()]
            self.assertEqual(len(responses),2)
            self.assertIn('repo_search',{t['name'] for t in responses[0]['result']['tools']})
            result=responses[1]['result']
            self.assertFalse(result['isError'])
            self.assertEqual([h['path'] for h in result['structuredContent']['results']],['a.py'])
            self.assertLess(len(json.dumps(result)),16000)

if __name__=='__main__':unittest.main()
