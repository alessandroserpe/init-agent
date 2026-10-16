"""Paired local cost measurements; temporary exported repositories only."""
import argparse
import contextlib
import io
import json
import math
from pathlib import Path
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time

from experiments.search_scope_chunks import passages, prepare
from init_agent.graph_store import GraphStore
from init_agent.local_search import search, terms

QUERIES = [
    'backup skills orientation synchron',
    'related.files related_files related-file callers callee calls',
    'fresh stale memory metadata mtime modified',
    'overview candidate repository map repo map unindexed drift deleted removed',
    'prepare_repository', 'init_agent/graph_store.py',
    'sqlite transaction rollback', 'function symbol qualified name',
    'Verifica quali informazioni vengono invalidate quando cambia il contenuto di un file già letto',
    'zznonexistentneedlezz',
]


def fixed(lines, symbols):
    for start in range(0, len(lines), 20):
        end = min(start+24, len(lines))
        yield start+1, end, '\n'.join(lines[start:end]), [s['name'] for s in symbols if start < s['line'] <= end]


def rebuild(root, mode, only=None):
    started = time.perf_counter()
    with GraphStore(root) as store:
        conn = store.connection
        files = list(conn.execute('SELECT path,sha256 FROM search_files' + (' WHERE path=?' if only else ''), (only,) if only else ()))
        if only:
            conn.execute('DELETE FROM search_chunks WHERE path=?', (only,))
        else:
            conn.execute('DELETE FROM search_chunks')
        for file in files:
            symbols = list(conn.execute('SELECT s.name,s.line,s.end_line FROM symbols s JOIN files f ON f.id=s.file_id WHERE f.path=?', (file['path'],)))
            lines = (root/file['path']).read_text().splitlines()
            for first,last,excerpt,names in (fixed if mode=='fixed' else passages)(lines, symbols):
                conn.execute('INSERT INTO search_chunks VALUES(?,?,?,?,?,?,?)',
                    (file['path'],file['sha256'],first,last,excerpt,
                     ' '.join(terms(file['path']+' '+' '.join(names))), ' '.join(terms(excerpt))))
        conn.commit()
    return (time.perf_counter()-started)*1000


def summary(values):
    return {'median':statistics.median(values), 'p95':sorted(values)[math.ceil(len(values)*.95)-1], 'min':min(values), 'max':max(values)}


def worker(root, mode):
    full = rebuild(root, mode)
    with GraphStore(root) as store:
        files = [r[0] for r in store.connection.execute("SELECT path FROM search_files WHERE path LIKE '%.py'")]
    largest = max(files, key=lambda p:(root/p).stat().st_size)
    single = [rebuild(root,mode,largest) for _ in range(5)]
    # Compact both databases identically; excluded from indexing/search timings.
    with GraphStore(root) as store:
        conn = store.connection
        conn.execute('VACUUM')
        disk = conn.execute('PRAGMA page_count').fetchone()[0]*conn.execute('PRAGMA page_size').fetchone()[0]
        count = conn.execute('SELECT count(*) FROM search_chunks').fetchone()[0]
        try:
            index_bytes = conn.execute("SELECT sum(pgsize) FROM dbstat WHERE name LIKE 'search_chunks%' OR name='search_files'").fetchone()[0]
        except Exception:
            index_bytes = None
    # Warm each query once. OS cache is not dropped: do not call these cold runs.
    for query in QUERIES:
        search(root,query)
    rows = []
    for query in QUERIES:
        timings=[]
        for _ in range(7):
            start=time.perf_counter();result=search(root,query);timings.append((time.perf_counter()-start)*1000)
        rows.append({'query':query,'milliseconds':timings,'response_bytes':len(json.dumps(result,ensure_ascii=False).encode()),'paths':[h['path'] for h in result['results']]})
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {'mode':mode,'full_reindex_ms':full,'single_file':largest,'single_file_reindex_ms':single,
            'compacted_database_bytes':disk,'search_tables_bytes':index_bytes,'chunks':count,
            'peak_process_rss_bytes':peak if sys.platform=='darwin' else peak*1024,'queries':rows}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--worker',type=Path);parser.add_argument('--mode');args=parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker,args.mode)));return
    repo=Path(__file__).resolve().parents[1]
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    runs=[]
    with tempfile.TemporaryDirectory(prefix='ia-scope-cost-') as tmp:
        base=Path(tmp);seed=base/'seed';seed.mkdir()
        data=subprocess.check_output(['git','archive','HEAD'],cwd=repo)
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:archive.extractall(seed,filter='data')
        prepare(seed)
        for trial in range(3):
            for mode in (('fixed','scope') if trial%2==0 else ('scope','fixed')):
                root=base/f'{trial}-{mode}';shutil.copytree(seed,root)
                output=subprocess.check_output([sys.executable,'-m','experiments.search_scope_cost','--worker',str(root),'--mode',mode],cwd=repo,text=True)
                row=json.loads(output);row['trial']=trial;runs.append(row)
                print(f'Completed trial {trial+1}/3: {mode}',file=sys.stderr,flush=True)
    aggregate={}
    for mode in ('fixed','scope'):
        selected=[r for r in runs if r['mode']==mode]
        aggregate[mode]={
            'full_reindex_ms':summary([r['full_reindex_ms'] for r in selected]),
            'single_file_reindex_ms':summary([v for r in selected for v in r['single_file_reindex_ms']]),
            'warm_search_ms':summary([v for r in selected for q in r['queries'] for v in q['milliseconds']]),
            'peak_rss_bytes':summary([r['peak_process_rss_bytes'] for r in selected]),
            'compacted_database_bytes':selected[0]['compacted_database_bytes'],
            'search_tables_bytes':selected[0]['search_tables_bytes'],
            'chunks':selected[0]['chunks'],
            'per_query':[{'query':query,'median_ms':statistics.median([v for r in selected for q in r['queries'] if q['query']==query for v in q['milliseconds']]),
                          'response_bytes':next(q['response_bytes'] for q in selected[0]['queries'] if q['query']==query)} for query in QUERIES]}
    print(json.dumps({'revision':revision,'python':platform.python_version(),'platform':platform.system()+' '+platform.machine(),
                     'protocol':'3 fresh processes per mode, alternating order; 10 warm queries x7; identical reindex pipeline; no cache flush; no model; single-file reindex excludes graph refresh and source edits',
                     'summary':aggregate,'runs':runs},indent=2))

if __name__=='__main__':main()
