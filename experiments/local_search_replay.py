"""Diagnostic keyword replay on HEAD; not an agent performance benchmark."""
import io,json,pathlib,subprocess,tarfile,tempfile,time
from init_agent.local_watch import Maintainer,maintenance_lock
from init_agent.local_search import search
from init_agent.context_builder import build_context_pack
repo=pathlib.Path(__file__).resolve().parents[1]
revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
with tempfile.TemporaryDirectory(prefix='ia-search-replay-') as tmp:
 root=pathlib.Path(tmp)
 data=subprocess.check_output(['git','archive','HEAD'],cwd=repo)
 with tarfile.open(fileobj=io.BytesIO(data)) as archive:archive.extractall(root,filter='data')
 started=time.perf_counter()
 with maintenance_lock(root):event=Maintainer(root).tick()
 report={'revision':revision,'index_seconds':time.perf_counter()-started,'index_event':event,'cases':[]}
 cases=[('backup skills orientation synchron','init_agent/skill_installer.py'),('related.files related_files related-file callers callee calls','init_agent/relation_resolver.py'),('fresh stale memory metadata mtime modified','init_agent/web_ui.py'),('overview candidate repository map repo map unindexed drift deleted removed','init_agent/index_health.py')]
 for query,expected in cases:
  started=time.perf_counter();result=search(root,query);seconds=time.perf_counter()-started
  old=build_context_pack(root,query)
  report['cases'].append({'query':query,'expected_reference':expected,'search_seconds':seconds,'response_bytes':len(json.dumps(result).encode()),'new_paths':[r['path'] for r in result['results']],'old_paths':[r['path'] for r in old['candidate_files'][:3]],'code_paths':[r['path'] for r in search(root,query,path_prefixes=['init_agent/'])['results']], 'result':result})
 pathlib.Path(tempfile.gettempdir(),'init-agent-search-replay.json').write_text(json.dumps(report,indent=2))
 print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2))
 for c in report['cases']:print(json.dumps({k:v for k,v in c.items() if k!='result'}))
