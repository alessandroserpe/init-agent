"""Compare scope-bounded passages in temporary indexes, without changing search."""
from collections import Counter, defaultdict
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time

from init_agent.graph_store import GraphStore
from init_agent.local_search import search, terms
from init_agent.local_watch import Maintainer, maintenance_lock


def passages(lines, symbols):
    """Split at known scope starts/ends; never infer missing end positions."""
    n = len(lines)
    events = defaultdict(Counter)
    declarations = defaultdict(list)
    for symbol in symbols:
        first, last = symbol['line'], symbol['end_line']
        if not isinstance(first, int) or not 1 <= first <= n:
            continue
        declarations[first].append(symbol['name'])
        if isinstance(last, int) and first <= last <= n:
            events[first][symbol['name']] += 1
            events[last + 1][symbol['name']] -= 1
        else:
            # Only the declaration line has established ownership.
            events[first]
            events[first + 1]
    boundaries = sorted({1, n + 1, *events})
    active = Counter()
    for first, stop in zip(boundaries, boundaries[1:]):
        active.update(events[first])
        active = +active
        for start in range(first, stop, 20):
            end = min(start + 24, stop)
            names = set(active)
            for line in range(start, end):
                names.update(declarations.get(line, ()))
            yield start, end - 1, '\n'.join(lines[start - 1:end - 1]), sorted(names)


def fixed_passages(lines, symbols):
    """Frozen pre-integration baseline for reproducible historical comparisons."""
    for start in range(0, len(lines), 20):
        end = min(start + 24, len(lines))
        yield start + 1, end, '\n'.join(lines[start:end]), [s['name'] for s in symbols if start < s['line'] <= end]


def rebuild(root, legacy=False):
    started = time.perf_counter()
    with GraphStore(root) as store:
        conn = store.connection
        files = list(conn.execute('SELECT path,sha256 FROM search_files'))
        conn.execute('DELETE FROM search_chunks')
        for file in files:
            symbols = list(conn.execute('SELECT s.name,s.line,s.end_line FROM symbols s JOIN files f ON f.id=s.file_id WHERE f.path=?', (file['path'],)))
            lines = (root/file['path']).read_text().splitlines()
            for first, last, excerpt, names in (fixed_passages if legacy else passages)(lines, symbols):
                conn.execute('INSERT INTO search_chunks VALUES(?,?,?,?,?,?,?)',
                    (file['path'], file['sha256'], first, last, excerpt,
                     ' '.join(terms(file['path'] + ' ' + ' '.join(names))), ' '.join(terms(excerpt))))
        conn.commit()
    return time.perf_counter() - started


def stats(root):
    with GraphStore(root) as store:
        row = store.connection.execute('SELECT count(*),sum(length(CAST(excerpt AS BLOB))+length(CAST(names AS BLOB))+length(CAST(body AS BLOB))) FROM search_chunks').fetchone()
        return {'chunks': row[0], 'text_bytes': row[1] or 0}


def prepare(root):
    with contextlib.redirect_stdout(io.StringIO()), maintenance_lock(root):
        Maintainer(root).tick()
    rebuild(root, legacy=True)


def run():
    results = []
    for name, detail in [('restoreArchive', 'checksum mismatch'), ('renewLease', 'deadline exceeded'),
                         ('parseManifest', 'unsupported encoding'), ('flushJournal', 'durability barrier')]:
        for guide in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root/'worker.py').write_text(f'def {name}():\n' + '    value = 1\n'*65 + f'    raise RuntimeError("{detail}")\n')
                if guide:
                    (root/'guide.md').write_text(f'# Troubleshooting\n{name}: {detail}.\n')
                prepare(root)
                row = {'query': name + ' ' + detail, 'guide': guide}
                for phase in ('before', 'after'):
                    if phase == 'after': rebuild(root)
                    answer = search(root, row['query'])
                    target = next(h for h in answer['results'] if h['path']=='worker.py')
                    row[phase] = {'paths': [h['path'] for h in answer['results']],
                                  'implementation_excerpt_correct': detail in target['excerpt'], **stats(root)}
                results.append(row)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root/'scope.py').write_text('def outerScope():\n' + '    x = 1\n'*23 + '\ndef unrelated():\n    return "foreignneedle"\n')
        (root/'nested.py').write_text('def parentScope():\n    def childScope():\n' + '        x = 1\n'*23 + '        return "innerneedle"\n' + '    x = 2\n'*30 + '    return "outerneedle"\n')
        prepare(root); rebuild(root)
        with GraphStore(root) as store:
            checks = {q: store.connection.execute('SELECT count(*) FROM search_chunks WHERE search_chunks MATCH ?', (q,)).fetchone()[0]
                      for q in ['outer AND foreignneedle', 'child AND outerneedle', 'child AND innerneedle', 'parent AND outerneedle']}
        assert checks['outer AND foreignneedle'] == checks['child AND outerneedle'] == 0
        assert checks['child AND innerneedle'] > 0 and checks['parent AND outerneedle'] > 0
    repo = Path(__file__).resolve().parents[1]
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = subprocess.check_output(['git', 'archive', 'HEAD'], cwd=repo)
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            archive.extractall(root, filter='data')
        prepare(root)
        queries = ['backup skills orientation synchron', 'related.files related_files related-file callers callee calls',
                   'fresh stale memory metadata mtime modified', 'overview candidate repository map repo map unindexed drift deleted removed']
        real = {'revision': revision, 'before': stats(root), 'queries': []}
        for query in queries:
            real['queries'].append({'query': query, 'before': [h['path'] for h in search(root, query, path_prefixes=['init_agent/'])['results']]})
        real['experimental_rebuild_seconds'] = rebuild(root)
        real['after'] = stats(root)
        for row in real['queries']:
            row['after'] = [h['path'] for h in search(root, row['query'], path_prefixes=['init_agent/'])['results']]
    regressions = []
    for fixture in ('local_search_cases.json', 'search_diversity_cases.json'):
        for case in json.loads((repo/'tests/fixtures'/fixture).read_text()):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                files = case.get('files') or {case['noise_path']: case['noise_line']*2400, case['target']: case['target_text']}
                for name, content in files.items():
                    path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content)
                prepare(root)
                row = {'id': case['id'], 'fixture': fixture}
                for phase in ('before', 'after'):
                    if phase == 'after': rebuild(root)
                    paths = [h['path'] for h in search(root, case['query'])['results']]
                    row[phase] = paths
                    row[phase + '_passes'] = ((paths[0] if paths else None) == case['expected']) if 'expected' in case else case['target'] in paths
                regressions.append(row)
    return {'synthetic_cases': results, 'scope_controls': checks, 'repository': real, 'regressions': regressions}

if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
