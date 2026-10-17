"""Opt-in bounded retrieval of static evidence, never observed execution."""
from __future__ import annotations

import ast
import hashlib
import os
from types import SimpleNamespace
from collections import deque
from contextlib import closing
from pathlib import Path

from .metadata_db import connect_metadata
from .persisted_json import decode_persisted_object, CorruptMetadata
from .read_budget import ReadBudget
from .repo_files import open_repo_file


def capabilities(conn, path):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='file_analysis'").fetchone():
        return {'indexed': True, 'structural': False, 'text_search': True,
                'errors': ['Analyzer provenance absent; remap required']}
    row = conn.execute('SELECT a.metadata_json FROM file_analysis a JOIN files f ON f.id=a.file_id WHERE f.path=?', (path,)).fetchone()
    try:
        return decode_persisted_object(row[0]) if row else {'structural': False, 'errors': ['Analysis absent']}
    except CorruptMetadata:
        return {'structural': False, 'errors': ['Invalid analysis metadata']}


def _lexical_call(source, target, metadata, text):
    """Reject nominal matches, receiver guesses and shadowed bindings.

    Only lexical direct names and explicit module imports are admitted initially.
    Annotated receivers and self dispatch remain hints (possible overrides).
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return False
    line = metadata.get('line')
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and n.lineno == line]
    qualified = metadata.get('qualified_name') or metadata.get('raw_target_id')
    matches = [n for n in calls if ast.unparse(n.func) == qualified]
    if len(matches) != 1:
        return False
    func = matches[0].func
    name = func.id if isinstance(func, ast.Name) else func.value.id if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) else None
    if not name:
        return False
    # Enumerate lexical scopes and all binding sites, including reassignment.
    scopes = []
    def walk(node, prefix='', parents=()):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = f'{prefix}.{child.name}' if prefix else child.name
                scopes.append((q, child, parents))
                walk(child, q, (*parents, node))
            else:
                walk(child, prefix, parents)
    walk(tree)
    matching_scopes = [n for q,n,p in scopes if q == source['qualified_name']]
    if len(matching_scopes) != 1:
        return False
    scope = matching_scopes[0]
    if scope.lineno != source['line'] or not scope.lineno <= line <= scope.end_lineno:
        return False
    chain = [scope]
    current = source['qualified_name']
    while '.' in current:
        current = current.rsplit('.', 1)[0]
        parent = next((n for q,n,p in scopes if q == current), None)
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            chain.append(parent)
    chain.append(tree)
    for enclosing in chain:
        bindings = []
        def collect(node):
            if node is not enclosing and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == name:
                    bindings.append(('definition', node))
                return
            if isinstance(node, ast.arg) and node.arg == name:
                bindings.append(('dynamic', node))
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id == name:
                bindings.append(('dynamic', node))
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if (alias.asname or (alias.name.split('.')[0] if isinstance(node, ast.Import) else alias.name)) == name:
                        bindings.append(('import', node))
            for child in ast.iter_child_nodes(node):
                collect(child)
        collect(enclosing)
        if not bindings:
            continue
        if len(bindings) != 1:
            return False
        kind, binding = bindings[0]
        if kind == 'definition':
            return isinstance(func, ast.Name) and source['path'] == target['path'] and binding.lineno == target['line']
        if kind == 'import':
            if target.get('container_name'):
                return False
            if isinstance(binding, ast.ImportFrom) and isinstance(func, ast.Name):
                imported = [a.name for a in binding.names if (a.asname or a.name) == name]
                return metadata.get('resolver') == 'imported_symbol' and imported == [target['name']]
            if isinstance(func, ast.Attribute):
                return metadata.get('resolver') == 'qualified_module_symbol' and func.attr == target['name']
            return False
        return False
    return False


def trace_evidence(root: Path, starts, *, anchor=None, limit=10, max_depth=4):
    budget = ReadBudget()
    result = {'mode': 'static_evidence_experimental', 'paths': [], 'capabilities': {},
              'gaps': [], 'hints': [], 'verification': {'status': 'no_linked_evidence'},
              'execution_observed': False}
    with closing(connect_metadata(root, readonly=True)) as conn:
        conn.row_factory = __import__('sqlite3').Row
        files = {r['path']: dict(r) for r in conn.execute('SELECT * FROM files ORDER BY path LIMIT 10001')}
        symbols = {r['id']: dict(r) for r in conn.execute('SELECT s.*,f.path FROM symbols s JOIN files f ON f.id=s.file_id ORDER BY s.id LIMIT 50001')}
        snapshots = {}
        def fresh(path):
            if path not in snapshots:
                if len(snapshots) >= budget.max_files:
                    budget.truncated = True
                    return False
                if not budget.visit():
                    return False
                try:
                    with open_repo_file(root, path) as handle:
                        size = os.fstat(handle.fileno()).st_size
                        if size > budget.max_file_bytes or budget.bytes_read + size > budget.max_bytes:
                            budget.truncated = True
                            return False
                        raw = handle.read(budget.max_file_bytes + 1)
                    budget.bytes_read += len(raw)
                    digest = hashlib.sha256(raw).hexdigest()
                    snap = SimpleNamespace(content=raw.decode('utf-8', errors='replace'), sha256=digest)
                    snapshots[path] = snap if len(raw) <= budget.max_file_bytes and digest == files[path]['sha256'] else None
                except (OSError, KeyError):
                    snapshots[path] = None
            return snapshots[path] is not None
        def gap(path, reason, **extra):
            if len(result['gaps']) < 100:
                result['gaps'].append({'path': path, 'reason': reason, **extra})
        if len(files) > 10000 or len(symbols) > 50000:
            gap('', 'index_read_limit')
            budget.truncated = True
        seeds = [(p, '') for p in starts[:8] if p in files]
        if anchor:
            path, symbol = anchor.get('path'), anchor.get('symbol', '')
            if not isinstance(path, str) or Path(path).is_absolute() or '..' in Path(path).parts or not isinstance(symbol, str):
                raise ValueError('anchor requires repository-relative path and optional qualified symbol')
            seeds = [(path, symbol)]
            if symbol and sum(s['path']==path and s['qualified_name']==symbol for s in symbols.values()) > 1:
                gap(path, 'ambiguous_anchor', symbol=symbol)
                seeds = []
            if path not in files or (symbol and not any(s['path']==path and s['qualified_name']==symbol for s in symbols.values())):
                gap(path, 'anchor_not_indexed', symbol=symbol)
                seeds = []
        queue = deque((node, [], {node}) for node in seeds)
        while queue and len(result['paths']) < limit and budget.visit():
            (path, symbol), edges, seen = queue.popleft()
            cap = capabilities(conn, path)
            result['capabilities'][path] = cap
            if not fresh(path):
                gap(path, 'changed_or_missing_file', symbol=symbol)
                continue
            if not cap.get('structural'):
                gap(path, 'structural_analysis_unavailable', symbol=symbol)
                continue
            if len(edges) >= max_depth:
                gap(path, 'depth_limit', symbol=symbol)
                continue
            file_id = files[path]['id']
            if files[path]['language'] == 'typescript':
                dependencies = conn.execute("SELECT path,sha256 FROM analysis_dependencies WHERE file_id=? LIMIT 1001", (file_id,)).fetchall()
                if any(not fresh(d['path']) or snapshots[d['path']].sha256 != d['sha256'] for d in dependencies):
                    gap(path, 'changed_or_missing_analysis_dependency', symbol=symbol)
                    continue
                for message in cap.get('errors', [])[:20]:
                    gap(path, 'analyzer_gap', detail=message)
                records = list(conn.execute("SELECT * FROM relations WHERE source_type='file' AND source_id=? AND target_type='structural_file' ORDER BY id LIMIT 26", (file_id,)))
                if len(records) > 25:
                    gap(path, 'neighbor_limit', symbol=symbol)
                for record in records[:25]:
                    try:
                        item = decode_persisted_object(record['metadata_json'], relation=True)
                    except CorruptMetadata:
                        gap(path, 'invalid_relation_metadata')
                        continue
                    if symbol and item.get('source_symbol') != symbol:
                        continue
                    dest = record['target_id']
                    if not fresh(dest) or item.get('source_sha256') != snapshots[path].sha256 or item.get('target_sha256') != snapshots[dest].sha256:
                        gap(path, 'changed_or_missing_target', target=dest, line=item.get('line'))
                        continue
                    dest_symbol = '' if record['relation'] == 'imports' else item.get('target_symbol', '')
                    edge = {**item, 'from':path, 'to':dest, 'target_symbol':dest_symbol, 'resolved':True}
                    chain = [*edges, edge]
                    result['paths'].append({'path':[chain[0]['from'], *[e['to'] for e in chain]], 'resolved_edges':chain, 'hints':[], 'execution_observed':False})
                    node = (dest, dest_symbol)
                    if node not in seen:
                        queue.append((node, chain, seen | {node}))
                    if len(result['paths']) >= limit:
                        gap(path, 'result_limit', line=item.get('line'))
                        break
                if not records:
                    gap(path, 'no_extracted_links', symbol=symbol)
                continue
            rows = list(conn.execute("SELECT * FROM relations WHERE source_type='file' AND source_id=? AND relation IN ('calls','imports','imports_symbol','include','include_once','require','require_once') AND target_type NOT IN ('resolved_file','resolved_symbol') ORDER BY id LIMIT 1001", (file_id,)))
            if len(rows)>1000:
                gap(path, 'relation_limit', symbol=symbol)
            followed = 0
            for row in rows[:1000]:
                if not budget.visit():
                    gap(path, 'work_limit', symbol=symbol)
                    break
                try:
                    meta = decode_persisted_object(row['metadata_json'], relation=True)
                except CorruptMetadata:
                    gap(path, 'invalid_relation_metadata')
                    continue
                context = symbols.get(row['context_symbol_id'], {}).get('qualified_name', '')
                if symbol and context != symbol:
                    continue
                # File anchors expose independent call edges; they do not claim
                # a call chain between unrelated functions in the same file.
                candidates = []
                for resolved in conn.execute("SELECT * FROM relations WHERE target_type IN ('resolved_symbol','resolved_file') AND relation=? AND ((source_type='symbol' AND source_id=?) OR (source_type='file' AND source_id=?)) LIMIT 1000", (row['relation'], row['context_symbol_id'], file_id)):
                    try:
                        rm = decode_persisted_object(resolved['metadata_json'], relation=True)
                    except CorruptMetadata:
                        continue
                    if rm.get('raw_relation_id') == row['id']:
                        candidates.append((resolved, rm))
                edge = None
                for resolved, rm in candidates:
                    if resolved['target_type']=='resolved_symbol' and row['relation']=='calls':
                        source = symbols.get(resolved['source_id'])
                        try:
                            target = symbols.get(int(resolved['target_id']))
                        except (ValueError, TypeError):
                            target = None
                        if not source or not target:
                            continue
                        if files[path]['language'] == 'python':
                            if not _lexical_call(source, target, rm, snapshots[path].content):
                                continue
                        elif files[path]['language'] == 'php':
                            # Qualified procedural calls inside one parsed file.
                            # Cross-file include dispatch remains a separate path.
                            if ((target['path'] != path and rm.get('resolver') != 'php_namespace_function') or target['kind'] != 'function'
                                    or meta.get('dispatch_kind') != 'function'
                                    or meta.get('qualified_name', '').lower() != target['qualified_name'].lower()
                                    or meta.get('provenance', '').startswith('regex')):
                                continue
                        else:
                            continue
                        dest, dest_symbol, dest_line = target['path'], target['qualified_name'], target['line']
                    elif resolved['target_type']=='resolved_file' and ((row['relation']=='imports' and not symbol) or (row['relation'] in {'include','include_once','require','require_once'} and meta.get('include_kind') and not meta.get('provenance','').startswith('regex'))):
                        dest, dest_symbol, dest_line = resolved['target_id'], '', 1
                    else:
                        continue
                    if dest not in files or not fresh(dest):
                        gap(path, 'changed_or_missing_target', line=meta.get('line'), target=dest)
                        continue
                    if rm.get('source_sha256') != files[path]['sha256'] or rm.get('target_sha256') != files[dest]['sha256']:
                        gap(path, 'provenance_missing_or_changed', line=meta.get('line'), target=dest)
                        continue
                    if row['relation'] == 'calls' and not capabilities(conn, dest).get('structural'):
                        gap(path, 'target_structural_analysis_unavailable', line=meta.get('line'), target=dest)
                        continue
                    edge = {'from':path, 'to':dest, 'source_symbol':context,
                            'target_symbol':dest_symbol, 'line':meta.get('line'),
                            'target_line':dest_line, 'relation':row['relation'],
                            'method':rm.get('resolver'), 'source_sha256':files[path]['sha256'],
                            'target_sha256':files[dest]['sha256'], 'resolved':True}
                    break
                if edge is None:
                    if len(result['hints']) < 30:
                        result['hints'].append({'from': path, 'source_symbol': context, 'line': meta.get('line'), 'relation': row['relation'], 'target_name': row['target_id'], 'resolved': False})
                    gap(path, 'unresolved_or_insufficient_proof', line=meta.get('line'), symbol=context, target=row['target_id'])
                    continue
                followed += 1
                chain = [*edges, edge]
                result['paths'].append({'path':[chain[0]['from'], *[e['to'] for e in chain]],
                                        'resolved_edges':chain, 'hints':[], 'execution_observed':False})
                node = (edge['to'], edge['target_symbol'])
                if node not in seen:
                    queue.append((node, chain, seen | {node}))
                if len(result['paths']) >= limit:
                    if queue or followed < len(rows):
                        gap(path, 'result_limit', line=edge['line'])
                    break
            if not rows:
                gap(path, 'no_extracted_links', symbol=symbol)
        if budget.truncated:
            gap(queue[0][0][0] if queue else '', 'work_limit')
    result['work_budget'] = {'states':budget.states, 'bytes_read':budget.bytes_read, 'truncated':budget.truncated}
    return result
