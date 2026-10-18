import json
from pathlib import Path
import tempfile
import unittest

from init_agent.local_watch import Maintainer, maintenance_lock
from init_agent.local_search import search
from init_agent.memory import add_note
from init_agent.graph_store import GraphStore


class LocalSearchTests(unittest.TestCase):
    def prepare(self, root):
        with maintenance_lock(root):
            Maintainer(root).tick()

    def test_long_requests_retain_late_evidence_in_sources_and_notes(self):
        prefixes = [
            'Investigate unexpected behavior during deployment startup configuration loading environment validation logging retries background workers scheduling resources diagnostics failures',
            'Verifica comportamento inatteso durante avvio applicazione configurazione ambiente caricamento moduli controlli registrazione eventi tentativi risorse processi richieste errori',
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'worker.py').write_text('raise RuntimeError("lease exhausted")\n')
            self.prepare(root)
            note = add_note(root, None, 'Checkpoint rollback requires restoring the journal', scope='repo')
            for prefix in prefixes:
                for suffix, field, expected in [
                    ('lease exhausted', 'results', 'worker.py'),
                    ('checkpoint rollback', 'memories', note['id']),
                ]:
                    for query in (prefix + ' ' + suffix, suffix + ' ' + prefix):
                        with self.subTest(query=query):
                            result = search(root, query)
                            key = 'path' if field == 'results' else 'id'
                            self.assertIn(expected, [hit[key] for hit in result[field]])
                            self.assertIn(suffix.split()[-1], result['terms'])

    def test_max_length_request_executes_without_fts_expression_overflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'worker.py').write_text('MESSAGE="zircon"\n')
            self.prepare(root)
            # Many distinct short terms exercise the existing 1000-character bound.
            prefix = ' '.join(str(i) for i in range(400))
            query = prefix[:993] + ' zircon'
            self.assertEqual(len(query), 1000)
            self.assertEqual(search(root, query)['results'][0]['path'], 'worker.py')

    def test_large_document_does_not_exhaust_candidate_slots(self):
        cases=json.loads((Path(__file__).parent/'fixtures/search_diversity_cases.json').read_text())
        for case in cases:
            with self.subTest(case=case['id']), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                (root/case['noise_path']).write_text(case['noise_line']*2400)
                target=root/case['target'];target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(case['target_text'])
                self.prepare(root)
                hits=search(root,case['query'])['results']
                self.assertIn(case['target'],[r['path'] for r in hits])
                self.assertLessEqual(len(hits),3)

    def test_frozen_search_cases(self):
        cases=json.loads((Path(__file__).parent/'fixtures/local_search_cases.json').read_text())
        for case in cases:
            with self.subTest(case=case['id']), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                for name,content in case['files'].items():
                    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
                self.prepare(root)
                hits=search(root,case['query'])['results']
                self.assertEqual(hits[0]['path'] if hits else None,case['expected'])

    def test_body_only_evidence_symbols_and_identifier_splitting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'opaque.py').write_text('def openArchive():\n    raise ValueError("retention window exhausted")\n')
            (root/'caller.py').write_text('from opaque import openArchive\ndef run():\n    return openArchive()\n')
            self.prepare(root)
            result=search(root,'retention exhausted',include_relations=True)
            hit=result['results'][0]
            self.assertEqual(hit['path'],'opaque.py')
            self.assertIn('retention window exhausted',hit['excerpt'])
            self.assertIn('openArchive',[s['name'] for s in hit['symbols']])
            self.assertTrue(any(e['caller']['path']=='caller.py'
                                for p in result['call_paths'] for e in p['edges']))
            self.assertEqual(search(root,'open_archive')['results'][0]['path'],'opaque.py')
            self.assertEqual([r['path'] for r in search(root,'open_archive',path_prefixes=['caller.py'])['results']],['caller.py'])
            with self.assertRaises(ValueError):search(root,'x',path_prefixes=['../'])
            lines=(root/'opaque.py').read_text().splitlines()
            self.assertEqual(hit['excerpt'],'\n'.join(lines[hit['start_line']-1:hit['end_line']]))

    def test_stale_candidates_omitted_then_replaced_and_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'app.py';p.write_text('MESSAGE="quartz obsolete"\n')
            self.prepare(root)
            p.write_text('MESSAGE="zircon current"\n')
            result=search(root,'quartz')
            self.assertEqual(result['results'],[])
            self.assertEqual(result['stale_candidates'],['app.py'])
            self.prepare(root)
            self.assertFalse(search(root,'quartz')['results'])
            self.assertTrue(search(root,'zircon')['results'])
            p.unlink();self.prepare(root)
            self.assertFalse(search(root,'zircon')['results'])

    def test_notes_existing_new_updated_deleted_and_stale(self):
        from init_agent.run import prepare_repository
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'app.py').write_text('x=1\n')
            prepare_repository(root)
            note=add_note(root,'app.py','Retain backups for the audit requirement',topic='retention')
            self.prepare(root)
            result=search(root,'audit')
            self.assertEqual(result['memories'][0]['id'],note['id'])
            self.assertFalse(result['memories'][0]['stale'])
            fresh=add_note(root,None,'Migration rollback decision',scope='repo')
            self.assertEqual(search(root,'rollback')['memories'][0]['id'],fresh['id'])
            self.assertIsNone(search(root,'rollback')['memories'][0]['stale'])
            (root/'app.py').write_text('x=2\n')
            self.assertTrue(search(root,'audit')['memories'][0]['stale'])
            with GraphStore(root) as store:
                store.connection.execute("UPDATE agent_notes SET note=?,tags_json='[]' WHERE id=?",('zircon decision',note['id']))
                store.connection.commit()
            self.assertFalse(search(root,'audit')['memories'])
            self.assertTrue(search(root,'zircon')['memories'])
            with GraphStore(root) as store:
                store.connection.execute('DELETE FROM agent_notes WHERE id=?',(note['id'],))
                store.connection.commit()
            self.assertFalse(search(root,'zircon')['memories'])

    def test_exclusions_query_syntax_limits_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'app.py').write_text('x="public marker"\n')
            (root/'.env').write_text('SECRET=hidden_marker\n')
            self.prepare(root)
            before=(root/'.agent/graph.sqlite').read_bytes()
            self.assertNotIn('.env',[r['path'] for r in search(root,'hidden_marker')['results']])
            result=search(root,'public OR "marker" * ( ) NOT')
            self.assertLessEqual(len(result['results']),5)
            self.assertEqual(before,(root/'.agent/graph.sqlite').read_bytes())
            with self.assertRaises(ValueError):search(root,'x',limit=100)
            with self.assertRaises(ValueError):search(root,'x'*1001)

if __name__=='__main__':unittest.main()
