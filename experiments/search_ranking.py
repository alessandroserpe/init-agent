"""Frozen synthetic comparison; no model calls or production repository edits."""
import importlib.util,json,pathlib,tempfile,sys,time
from init_agent.local_watch import Maintainer,maintenance_lock
from init_agent.local_search import search
REPO=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('init_agent._search_baseline',str(REPO/'experiments/search-ranking/baseline.py'))
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
rows=[]
for case in json.loads((REPO/'tests/fixtures/local_search_cases.json').read_text()):
 if len(sys.argv)>1 and case['split']!=sys.argv[1]:continue
 with tempfile.TemporaryDirectory() as tmp:
  root=pathlib.Path(tmp)
  for name,contents in case['files'].items():
   p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(contents)
  with maintenance_lock(root):Maintainer(root).tick()
  row={k:case[k] for k in ('id','split','expected','query')}
  for label,fn in [('before',old.search),('after',search)]:
   result=fn(root,case['query']);paths=[r['path'] for r in result['results']]
   row[label]={'paths':paths,'top1':(paths[0] if paths else None)==case['expected'],'bytes':len(json.dumps(result).encode())}
  rows.append(row)
print(json.dumps(rows,indent=2))
