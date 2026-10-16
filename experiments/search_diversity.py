"""Synthetic candidate crowding checks; no model calls."""
import importlib.util,json,pathlib,tempfile
from init_agent.local_watch import Maintainer,maintenance_lock
from init_agent.local_search import search
REPO=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('init_agent._diversity_baseline',str(REPO/'experiments/search-diversity/baseline.py'));old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
rows=[]
for c in json.loads((REPO/'tests/fixtures/search_diversity_cases.json').read_text()):
 with tempfile.TemporaryDirectory() as tmp:
  root=pathlib.Path(tmp);(root/c['noise_path']).write_text(c['noise_line']*2400)
  p=root/c['target'];p.parent.mkdir(parents=True,exist_ok=True);p.write_text(c['target_text'])
  with maintenance_lock(root):Maintainer(root).tick()
  row={'id':c['id'],'split':c['split'],'target':c['target']}
  for label,fn in [('before',old.search),('after',search)]:
   r=fn(root,c['query']);paths=[v['path'] for v in r['results']]
   row[label]={'paths':paths,'found':c['target'] in paths,'bytes':len(json.dumps(r).encode())}
  rows.append(row)
print(json.dumps(rows,indent=2))
