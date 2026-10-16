"""Audit extraction -> resolution -> retrieval on current source in isolation."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile

from init_agent.graph_store import GraphStore
from init_agent.local_watch import Maintainer, maintenance_lock
from init_agent.local_search import search

# Manually source-verified calls in the actual maintenance path; no ranking labels.
EDGES = [
 ('init_agent/search_tool.py','make_repo_search_handler.handle','init_agent/local_watch.py','Maintainer.tick','tick'),
 ('init_agent/local_watch.py','Maintainer.tick','init_agent/local_watch.py','fingerprint','fingerprint'),
 ('init_agent/local_watch.py','fingerprint','init_agent/scanner.py','iter_project_files','iter_project_files'),
 ('init_agent/scanner.py','iter_project_files','init_agent/utils.py','iter_indexable_files','iter_indexable_files'),
 ('init_agent/utils.py','iter_indexable_files','init_agent/utils.py','_git_indexable_paths','_git_indexable_paths'),
 ('init_agent/utils.py','_git_indexable_paths','init_agent/utils.py','run_git_read','run_git_read'),
 ('init_agent/local_watch.py','Maintainer.tick','init_agent/run.py','prepare_repository','prepare_repository'),
 ('init_agent/local_watch.py','Maintainer.tick','init_agent/local_search.py','update_search_index','update_search_index'),
 ('init_agent/search_tool.py','make_repo_search_handler.handle','init_agent/local_search.py','search','search'),
]


def main():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp)
  shutil.copytree(Path.cwd()/'init_agent',root/'init_agent',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  with contextlib.redirect_stdout(io.StringIO()), maintenance_lock(root):
   event=Maintainer(root).tick()
  output={'maintenance_status':event['status'],'edges':[]}
  with GraphStore(root) as store:
   conn=store.connection
   for sf,sq,tf,tq,raw in EDGES:
    def symbol(path,q):
     return conn.execute('SELECT s.id,s.line,s.end_line FROM symbols s JOIN files f ON f.id=s.file_id WHERE f.path=? AND s.qualified_name=?',(path,q)).fetchone()
    src,dst=symbol(sf,sq),symbol(tf,tq)
    extracted=[];resolved=[]
    if src:
     extracted=[dict(r) for r in conn.execute("SELECT relation,target_id,metadata_json FROM relations WHERE context_symbol_id=? AND target_type='symbol_name' AND relation='calls' AND target_id=?",(src['id'],raw))]
     if dst:
      resolved=[dict(r) for r in conn.execute("SELECT relation,metadata_json FROM relations WHERE source_type='symbol' AND source_id=? AND target_type='resolved_symbol' AND target_id=? AND relation='calls'",(src['id'],str(dst['id'])))]
    output['edges'].append(dict(source=sf+':'+sq,target=tf+':'+tq,source_exists=bool(src),target_exists=bool(dst),raw_calls=extracted,resolved_calls=resolved))
   output['counts']={t:conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['files','symbols','relations']}
  output['queries']={q:search(root,q,3) for q in ['Maintainer.tick','fingerprint iter_project_files','Git inventory fallback gitignore']}
  print(json.dumps(output,indent=2))

if __name__=='__main__':main()
