import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from init_agent.exporter import export_graph
from init_agent.trace import trace_query
from init_agent.graph_store import GraphStore
from init_agent.utils import ensure_agent_dir
from init_agent.persisted_json import decode_persisted_object, CorruptMetadata
from init_agent.relation_resolver import _metadata


class PersistedJsonTests(unittest.TestCase):
    def test_corrupt_index_is_partial_in_trace_and_export(self):
        bad = ['{"x":' + '[' * 1200 + '0' + ']' * 1200 + '}',
               '{"raw_relation_id":' + '9' * 6000 + '}',
               '{"raw_relation_id":"not-an-id"}', '{', '[]',
               '{"x":{"nested":1}}', '{"x":NaN}']
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'main.py').write_text('import target\n')
            (root / 'target.py').write_text('value = 1\n')
            ensure_agent_dir(root)
            with GraphStore(root) as store:
                store.initialize()
                store.connection.executemany("INSERT INTO files(path, language, role) VALUES (?, 'python', 'source')", [('main.py',), ('target.py',)])
                store.connection.execute("INSERT INTO relations(source_type, source_id, relation, target_type, target_id, confidence, metadata_json) VALUES ('file', 1, 'imports', 'resolved_file', 'target.py', 0.9, '{}')")
                store.connection.commit()
            for value in bad:
                with self.subTest(value=value[:50]):
                    with GraphStore(root) as store:
                        store.connection.execute('UPDATE relations SET metadata_json=?', (value,))
                        store.connection.commit()
                    trace = trace_query(root, 'main')
                    exported = export_graph(root)
                    self.assertEqual(len(trace['warnings']), 1)
                    self.assertEqual(len(exported['warnings']), 1)
                    self.assertIn('Rebuild', trace['warnings'][0])
                    self.assertEqual(exported['relations'][0]['metadata'], {})
                    self.assertLess(len(json.dumps(exported['warnings'])), 200)
            with GraphStore(root) as store:
                store.connection.execute('UPDATE relations SET metadata_json=?', ('{"raw_relation_id":1,"resolver":"module","resolved":true}',))
                store.connection.commit()
            self.assertFalse(export_graph(root)['warnings'])
            self.assertFalse(trace_query(root, 'main')['warnings'])

    def test_preflight_and_decoder_resource_errors_are_contained(self):
        for payload in ('{"x":' + '[' * 50 + '0' + ']' * 50 + '}', 'x' * 16385,
                        '{' + ','.join('"x%d":0' % n for n in range(300)) + '}'):
            with patch('init_agent.bounded_json.json.loads') as decode:
                with self.assertRaises(CorruptMetadata):
                    decode_persisted_object(payload, relation=True)
                decode.assert_not_called()
        for error in (ValueError, RecursionError, MemoryError):
            with patch('init_agent.bounded_json.json.loads', side_effect=error):
                with self.assertRaises(CorruptMetadata):
                    decode_persisted_object('{}', relation=True)
        with self.assertWarns(RuntimeWarning):
            self.assertEqual(_metadata({'metadata_json': '{"raw_relation_id": []}'}), {})
        self.assertEqual(decode_persisted_object('{"name":"foo","line":2}', relation=True), {'name': 'foo', 'line': 2})
