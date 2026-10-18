"""Call-path retrieval must find nonlexical evidence without guessing links."""
import json
from pathlib import Path
import tempfile
import unittest

from init_agent.graph_store import GraphStore
from init_agent.local_search import search
from init_agent.local_watch import Maintainer, maintenance_lock


class SearchPathTests(unittest.TestCase):
    def fixture(self, root):
        files = {
            'entry.py': 'from service import dispatch\ndef checkout():\n    return dispatch()\n',
            'service.py': 'from storage import persist\ndef dispatch():\n    return persist()\n',
            'storage.py': 'def persist():\n    return "durable"\n',
            'noise.py': 'def persist():\n    return "unrelated"\n',
        }
        for p, s in files.items(): (root/p).write_text(s)
        with maintenance_lock(root): Maintainer(root).tick()

    def test_nonlexical_two_hop_path_and_reverse_call_sites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            result=search(root,'checkout',include_relations=True,limit=1)
            self.assertEqual([h['path'] for h in result['results']],['entry.py'])
            path=result['call_paths'][0]
            self.assertEqual(path['direction'],'outgoing')
            self.assertEqual([e['callee']['path'] for e in path['edges']],['service.py','storage.py'])
            self.assertNotIn('noise.py',json.dumps(result['call_paths']))
            for edge in path['edges']:
                lines=(root/edge['caller']['path']).read_text().splitlines()
                self.assertEqual(edge['call_excerpt'],lines[edge['call_line']-1])
            reverse=search(root,'durable',include_relations=True,limit=1)
            incoming=next(p for p in reverse['call_paths'] if p['direction']=='incoming')
            self.assertEqual([e['caller']['path'] for e in incoming['edges']],['entry.py','service.py'])
            self.assertLessEqual(len(json.dumps(result['call_paths'],ensure_ascii=False)),5000)

    def test_stale_deleted_and_prefix_excluded_targets_are_not_evidence(self):
        for action in ('edit','delete','prefix'):
            with self.subTest(action=action),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);self.fixture(root)
                if action=='edit':(root/'service.py').write_text('def dispatch(): return 7\n')
                if action=='delete':(root/'service.py').unlink()
                result=search(root,'checkout',include_relations=True,path_prefixes=['entry.py'] if action=='prefix' else [])
                self.assertEqual(result['call_paths'],[])
                if action!='prefix':self.assertIn('service.py',result['call_path_diagnostics']['stale_paths'])

    def test_unknown_receiver_does_not_link_same_named_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'a.py').write_text('class Worker:\n    def send(self): return 1\n\ndef checkout(obj):\n    return obj.send()\n')
            with maintenance_lock(root):Maintainer(root).tick()
            self.assertEqual(search(root,'checkout',include_relations=True)['call_paths'],[])

    def test_cycles_hubs_and_missing_line_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'a.py').write_text('def alpha():\n    return beta()\n\ndef beta():\n    return alpha()\n')
            with maintenance_lock(root):Maintainer(root).tick()
            result=search(root,'alpha',include_relations=True)
            self.assertTrue(result['call_paths'])
            self.assertTrue(all(len(p['edges'])==1 for p in result['call_paths']))
            with GraphStore(root) as store:
                store.connection.execute("UPDATE relations SET metadata_json='{}' WHERE target_type='resolved_symbol'")
                store.connection.commit()
            self.assertEqual(search(root,'alpha',include_relations=True)['call_paths'],[])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'a.py').write_text('def hub():\n'+''.join(f'    leaf{i}()\n' for i in range(13))+'\n'+''.join(f'def leaf{i}(): return {i}\n' for i in range(13)))
            with maintenance_lock(root):Maintainer(root).tick()
            result=search(root,'hub',include_relations=True)
            self.assertEqual(result['call_paths'],[])
            self.assertTrue(result['call_path_diagnostics']['truncated'])

    def test_import_only_match_has_no_callable_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            result=search(root,'from service',include_relations=True,path_prefixes=['entry.py'])
            self.assertEqual(result['call_paths'],[])
            self.assertIsNone(result['call_path_diagnostics']['seed'])

    def test_ambiguous_branches_abstain_but_named_branch_is_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'a.py').write_text('def checkout():\n    charge()\n    notify()\n\ndef charge(): return 1\n\ndef notify(): return 2\n')
            with maintenance_lock(root):Maintainer(root).tick()
            ambiguous=search(root,'checkout',include_relations=True)
            self.assertEqual(ambiguous['call_paths'],[])
            self.assertEqual(ambiguous['call_path_diagnostics']['ambiguous_branches'],1)
            focused=search(root,'checkout charge',include_relations=True)
            self.assertEqual(focused['call_paths'][0]['edges'][0]['callee']['symbol'],'charge')

    def test_mcp_returns_paths_and_excludes_source_not_in_search_index(self):
        from init_agent.mcp_server import InitAgentMcpServer
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            server=InitAgentMcpServer(root)
            response=server.handle({'jsonrpc':'2.0','id':1,'method':'tools/call',
                'params':{'name':'repo_search','arguments':{'query':'checkout','limit':1,'include_relations':True}}})['result']
            self.assertFalse(response['isError'])
            self.assertEqual(len(response['structuredContent']['call_paths'][0]['edges']),2)
            with GraphStore(root) as store:
                store.connection.execute("DELETE FROM search_files WHERE path='service.py'")
                store.connection.commit()
            self.assertEqual(search(root,'checkout',include_relations=True)['call_paths'],[])

    def test_output_budget_keeps_path_connected_to_seed(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            complete=search(root,'durable',include_relations=True)['call_paths'][0]
            one_edge_size=len(json.dumps([{'direction':'incoming','edges':complete['edges'][-1:]}],ensure_ascii=False))
            with patch('init_agent.search_paths.MAX_PATH_CHARACTERS',one_edge_size):
                bounded=search(root,'durable',include_relations=True)
            edges=bounded['call_paths'][0]['edges']
            self.assertEqual(len(edges),1)
            self.assertEqual(edges[0]['callee']['path'],'storage.py')
            self.assertTrue(bounded['call_path_diagnostics']['truncated'])


if __name__=='__main__':unittest.main()
