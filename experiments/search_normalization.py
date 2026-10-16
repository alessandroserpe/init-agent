"""Fixed-snapshot comparison of full-text query/source normalization only."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
from unittest.mock import patch

from init_agent.graph_store import GraphStore
from init_agent.local_search import search, update_search_index
from init_agent.local_watch import Maintainer, maintenance_lock
from init_agent.text_tokens import FUNCTION_WORDS, identifier_terms

QUERIES = [
    'Perché la scansione include i log generati dagli esperimenti anche quando sono esclusi tramite .gitignore?',
    'Come viene gestita la cancellazione dei file già indicizzati?',
    'Where are stale notes checked after source files change?',
    'prepare_repository', 'init_agent/local_search.py',
]
REVISION = '4c15567'


def legacy_terms(text):
    return [t for t in identifier_terms(text) if t not in FUNCTION_WORDS]


def run():
    repo=Path(__file__).resolve().parents[1]
    revision=subprocess.check_output(['git','rev-parse',REVISION],cwd=repo,text=True).strip()
    rows=[]
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        data=subprocess.check_output(['git','archive',revision],cwd=repo)
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:archive.extractall(root,filter='data')
        with patch('init_agent.local_search.terms',legacy_terms), contextlib.redirect_stdout(io.StringIO()), maintenance_lock(root):
            Maintainer(root).tick()
            for query in QUERIES:
                result=search(root,query)
                rows.append({'query':query,'before':{'terms':result['terms'],'paths':[h['path'] for h in result['results']],
                    'response_bytes':len(json.dumps(result,ensure_ascii=False).encode())}})
        with GraphStore(root) as store:
            store.connection.execute('DELETE FROM search_index_meta');store.connection.commit()
        update_search_index(root)
        for row in rows:
            result=search(root,row['query'])
            row['after']={'terms':result['terms'],'paths':[h['path'] for h in result['results']],
                'response_bytes':len(json.dumps(result,ensure_ascii=False).encode())}
    return {'revision':revision,'cases':rows,'scope':'same exported source and ranking; full-text normalization differs; not a blind relevance benchmark'}

if __name__=='__main__':print(json.dumps(run(),indent=2,ensure_ascii=False))
