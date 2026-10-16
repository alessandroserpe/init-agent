"""Isolated symbol-context hypothesis test; mutates temporary indexes only."""
import contextlib
import io
import json
from pathlib import Path
import tempfile

from init_agent.graph_store import GraphStore
from init_agent.local_search import search, terms
from experiments.search_scope_chunks import prepare


def add_enclosing_names(root):
    with GraphStore(root) as store:
        conn = store.connection
        chunks = list(conn.execute('SELECT rowid,* FROM search_chunks'))
        for chunk in chunks:
            symbols = list(conn.execute(
                'SELECT s.name,s.line,s.end_line FROM symbols s JOIN files f ON f.id=s.file_id WHERE f.path=?',
                (chunk['path'],)))
            first, last = int(chunk['first_line']), int(chunk['last_line'])
            names = [s['name'] for s in symbols if
                     first <= s['line'] <= last or
                     (s['end_line'] is not None and s['line'] <= first <= s['end_line'])]
            conn.execute('UPDATE search_chunks SET names=? WHERE rowid=?',
                         (' '.join(terms(chunk['path'] + ' ' + ' '.join(names))), chunk['rowid']))
        conn.commit()


def run():
    results = []
    for name, detail in [('restoreArchive', 'checksum mismatch'),
                         ('renewLease', 'deadline exceeded'),
                         ('parseManifest', 'unsupported encoding'),
                         ('flushJournal', 'durability barrier')]:
        for distractor in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                code = f'def {name}():\n' + '    value = 1\n' * 65 + f'    raise RuntimeError("{detail}")\n'
                (root/'worker.py').write_text(code)
                if distractor:
                    (root/'guide.md').write_text(f'# Troubleshooting\n{name}: {detail}.\n')
                prepare(root)
                row = {'query': name + ' ' + detail, 'distractor': distractor}
                for phase in ('before', 'after'):
                    if phase == 'after':
                        add_enclosing_names(root)
                    answer = search(root, row['query'])
                    row[phase] = {
                        'paths': [hit['path'] for hit in answer['results']],
                        'top_has_target_evidence': bool(answer['results']) and answer['results'][0]['path']=='worker.py' and detail in answer['results'][0]['excerpt'],
                        'target_channels': next((hit['retrieval'] for hit in answer['results'] if hit['path']=='worker.py'), []),
                    }
                results.append(row)
    # Conservative null-end behavior and boundary contamination are index checks,
    # independent of any relevance ranking chosen above.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root/'scope.py').write_text('def outerScope():\n' + '    x = 1\n'*23 + '\ndef unrelated():\n    return "foreignneedle"\n')
        prepare(root)
        add_enclosing_names(root)
        with GraphStore(root) as store:
            boundary = [dict(r) for r in store.connection.execute("SELECT first_line,last_line,names FROM search_chunks WHERE search_chunks MATCH 'outer AND foreignneedle'")]
            store.connection.execute('UPDATE symbols SET end_line=NULL')
            store.connection.commit()
        add_enclosing_names(root)
        with GraphStore(root) as store:
            unknown = [dict(r) for r in store.connection.execute("SELECT first_line,names FROM search_chunks WHERE CAST(first_line AS INTEGER)>1 AND names LIKE '%outer%'")]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root/'nested.py').write_text('def parentScope():\n    def childScope():\n' + '        x = 1\n'*23 + '        return "innerneedle"\n' + '    x = 2\n'*30 + '    return "outerneedle"\n')
        prepare(root)
        add_enclosing_names(root)
        with GraphStore(root) as store:
            nested = {
                'child_with_inner_evidence': len(list(store.connection.execute("SELECT rowid FROM search_chunks WHERE search_chunks MATCH 'child AND innerneedle'"))),
                'child_with_distant_outer_evidence': len(list(store.connection.execute("SELECT rowid FROM search_chunks WHERE search_chunks MATCH 'child AND outerneedle'"))),
                'parent_with_outer_evidence': len(list(store.connection.execute("SELECT rowid FROM search_chunks WHERE search_chunks MATCH 'parent AND outerneedle'"))),
            }
    return {'nested_scope': nested, 'cases': results, 'boundary_false_association': boundary, 'unknown_end_extension': unknown,
            'limitations': 'Synthetic mechanism checks only; intersecting windows do not prove that every token belongs to the named symbol.'}

if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
