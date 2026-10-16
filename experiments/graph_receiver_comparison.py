"""Bounded diagnostic against a separately checked-out Graphify source tree.
Run in temporary venv: python -m experiments.graph_receiver_comparison /tmp/graphify-audit
"""
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,sys.argv[1])
from graphify.extract import extract
from init_agent.graph_store import GraphStore
from init_agent.run import prepare_repository


def main():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);pkg=root/'pkg';pkg.mkdir()
  (pkg/'__init__.py').write_text('')
  (pkg/'worker.py').write_text('class Worker:\n    def tick(self):\n        return 1\n\nclass Other:\n    def tick(self):\n        return 2\n')
  (pkg/'use.py').write_text('from .worker import Worker, Other\n\ndef constructed():\n    worker = Worker()\n    return worker.tick()\n\ndef annotated(worker: Worker):\n    return worker.tick()\n\ndef unknown(worker):\n    return worker.tick()\n\ndef rebound(worker: Worker):\n    worker = Other()\n    return worker.tick()\n')
  with contextlib.redirect_stdout(io.StringIO()):
   prepare_repository(root)
   g=extract(sorted(pkg.glob('*.py')),root=root,cache_root=root/'cache',parallel=False)
  labels={n['id']:n['label'] for n in g['nodes']}
  ge=[{'source':labels.get(e['source']),'target':labels.get(e['target']),'target_id':e['target'],'confidence':e.get('confidence')} for e in g['edges'] if e['relation']=='calls' and labels.get(e['target'])=='.tick()']
  with GraphStore(root) as store:
   ie=[dict(r) for r in store.connection.execute("SELECT s.qualified_name AS source,t.qualified_name AS target FROM relations r JOIN symbols s ON s.id=r.source_id JOIN symbols t ON t.id=CAST(r.target_id AS INTEGER) WHERE r.source_type='symbol' AND r.target_type='resolved_symbol' AND r.relation='calls' AND t.name='tick'")]
  # Separately inspect the actual closure/nonlocal receiver; do not assume the
  # simple constructor fixture generalizes to the production control flow.
  actual=root/'actual';shutil.copytree(Path.cwd()/'init_agent',actual/'init_agent',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  with contextlib.redirect_stdout(io.StringIO()):
   real=extract(sorted((actual/'init_agent').glob('*.py')),root=actual,cache_root=root/'real-cache',parallel=False)
  nodes={n['id']:n for n in real['nodes']}
  tick_edges=[{'source':nodes.get(e['source'],{}),'target':nodes.get(e['target'],{}),'edge':e} for e in real['edges'] if e['relation']=='calls' and nodes.get(e['target'],{}).get('label')=='.tick()' and 'search_tool' in str(nodes.get(e['source'],{}).get('source_file',''))]
  print(json.dumps({'fixture_graphify':ge,'fixture_init_agent':ie,'actual_graphify_search_tool_tick':tick_edges,'actual_graphify_counts':{'nodes':len(real['nodes']),'edges':len(real['edges'])}},indent=2))

if __name__=='__main__':main()
