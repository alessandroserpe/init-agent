"""Same-index lexical baseline versus bounded structural evidence, no LLM."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import statistics
import tempfile
import time
from unittest.mock import patch

from init_agent.local_search import search
from init_agent.local_watch import Maintainer, maintenance_lock

QUERIES = ['Maintainer.tick', 'fingerprint iter_project_files', 'Git inventory fallback gitignore']


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        shutil.copytree(Path.cwd()/'init_agent',root/'init_agent',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        with contextlib.redirect_stdout(io.StringIO()),maintenance_lock(root):Maintainer(root).tick()
        rows=[]
        for q in QUERIES:
            times={'lexical':[],'paths':[]};responses={}
            for i in range(6):
                for mode in (('lexical','paths') if i%2 else ('paths','lexical')):
                    context=patch('init_agent.local_search.call_paths',return_value=([],{'stale_paths':[]})) if mode=='lexical' else contextlib.nullcontext()
                    with context:
                        start=time.perf_counter();r=search(root,q,include_relations=(mode=='paths'));elapsed=time.perf_counter()-start
                    if mode=='lexical':
                        r.pop('call_paths',None);r.pop('call_path_diagnostics',None)
                    times[mode].append(elapsed*1000);responses[mode]=r
            lexical_paths=[h['path'] for h in responses['lexical']['results']]
            structural_files=sorted({e[side]['path'] for p in responses['paths']['call_paths'] for e in p['edges'] for side in ('caller','callee')})
            rows.append({'query':q,'median_ms':{k:statistics.median(v) for k,v in times.items()},
                         'characters':{k:len(json.dumps(v,ensure_ascii=False)) for k,v in responses.items()},
                         'additional_paths':sorted(set(structural_files)-set(lexical_paths)),
                         'responses':responses})
        print(json.dumps({'scope':'Same fresh source-only index; selected diagnostic queries, no token-savings claim.', 'queries':rows},indent=2))

if __name__=='__main__':main()
