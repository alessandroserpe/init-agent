"""Bounded call-path evidence from a lexical hit; never infer missing edges."""
from __future__ import annotations

import json

from .repo_budget import checkpoint
from .repo_files import repo_snapshot
from .search_tokens import search_terms

MAX_NEIGHBORS = 12
MAX_DEPTH = 2
MAX_PATH_CHARACTERS = 5000


def call_paths(conn, root, hit, query, prefixes, allowed_path):
    """Return at most one incoming and one outgoing path from one grounded seed.

    Paths explain indexed calls, not runtime execution or exhaustive relevance.
    Direction stays fixed: incoming expansion cannot jump to sibling callees.
    """
    diagnostics = {'seed': None, 'truncated': False, 'ambiguous_branches': 0,
                   'stale_paths': [], 'max_depth': MAX_DEPTH}
    snapshots = {}
    terms = set(search_terms(query))

    def current(symbol):
        path = symbol['path']
        if not allowed_path(path) or (prefixes and not any(path.startswith(p) for p in prefixes)):
            return None
        if path not in snapshots:
            checkpoint()
            try:
                snap = repo_snapshot(root, path)
            except OSError:
                snap = None
            snapshots[path] = snap
        snap = snapshots[path]
        if snap is None or snap.content is None or snap.sha256 != symbol['sha256']:
            if path not in diagnostics['stale_paths']:
                diagnostics['stale_paths'].append(path)
            return None
        return snap

    def symbol(sid):
        row = conn.execute('SELECT s.id,s.qualified_name,s.line,s.end_line,f.path,f.sha256 '
                           'FROM symbols s JOIN files f ON f.id=s.file_id '
                           'JOIN search_files i ON i.path=f.path AND i.sha256=f.sha256 WHERE s.id=?', (sid,)).fetchone()
        return dict(row) if row else None

    lines = hit['excerpt'].splitlines()
    anchor = hit['start_line'] + (max(range(len(lines)), key=lambda i: len(set(search_terms(lines[i])) & terms)) if lines else 0)
    # Only an enclosing callable; a file import, class heading or nearby function
    # must not become a fabricated call-site seed.
    seed_row = conn.execute("SELECT s.id FROM symbols s JOIN files f ON f.id=s.file_id "
                            "WHERE f.path=? AND s.kind IN ('function','method') AND s.line<=? AND s.end_line>=? "
                            "ORDER BY (s.end_line-s.line),s.line DESC,s.id LIMIT 1",
                            (hit['path'], anchor, anchor)).fetchone()
    if seed_row is None:
        return [], diagnostics
    seed = symbol(seed_row['id'])
    if seed is None or current(seed) is None:
        return [], diagnostics
    diagnostics['seed'] = {'path': seed['path'], 'symbol': seed['qualified_name'][:200]}

    def endpoint(item):
        return {'path': item['path'], 'symbol': item['qualified_name'][:200], 'line': item['line'], 'sha256': item['sha256']}

    def evidence(src, dst, row):
        a, b = current(src), current(dst)
        if a is None or b is None:
            return None
        try:
            metadata = json.loads(row['metadata_json'])
            line = metadata.get('line')
        except (ValueError, TypeError, AttributeError):
            return None
        # A missing or invalid call location is not repaired by guessing.
        if type(line) is not int or not src['line'] <= line <= (src['end_line'] or src['line']):
            return None
        source_lines, target_lines = a.content.splitlines(), b.content.splitlines()
        if not 1 <= line <= len(source_lines) or not 1 <= dst['line'] <= len(target_lines):
            return None
        call_text = source_lines[line-1]
        target_text = '\n'.join(target_lines[dst['line']-1:min(dst['line']+3,dst['end_line'] or dst['line'])])
        return {'caller': endpoint(src), 'callee': endpoint(dst), 'relation': 'calls',
                'call_line': line, 'call_excerpt': call_text[:240],
                'target_excerpt': target_text[:400],
                'excerpt_truncated': len(call_text)>240 or len(target_text)>400,
                'confidence': row['confidence'], 'provenance': 'resolved',
                'resolver': str(metadata.get('resolver',''))[:100]}

    paths = []
    for direction in ('outgoing', 'incoming'):
        node, visited, steps = seed, {seed['id']}, []
        for _ in range(MAX_DEPTH):
            checkpoint()
            clause, value = ('source_id=?', node['id']) if direction == 'outgoing' else ('target_id=?', str(node['id']))
            rows = list(conn.execute("SELECT source_id,target_id,confidence,metadata_json FROM relations "
                                    "WHERE source_type='symbol' AND target_type='resolved_symbol' AND relation='calls' AND "
                                    + clause + ' ORDER BY confidence DESC,source_id,target_id LIMIT ?', (value, MAX_NEIGHBORS+1)))
            if len(rows)>MAX_NEIGHBORS:
                diagnostics['truncated'] = True
                # A hub is not a useful transit shortcut. Do not select an
                # arbitrary subset of its neighbors as a supposedly best path.
                break
            candidates = []
            for row in rows:
                try:
                    sid = int(row['target_id']) if direction=='outgoing' else int(row['source_id'])
                except (ValueError, TypeError):
                    continue
                if sid in visited:
                    continue
                other = symbol(sid)
                if other is None:
                    continue
                src, dst = (node, other) if direction=='outgoing' else (other, node)
                edge = evidence(src,dst,row)
                if edge:
                    overlap = len(terms & set(search_terms(other['qualified_name'])))
                    candidates.append(((-overlap,-float(row['confidence']),other['path'],other['line']),other,edge))
            if not candidates:
                break
            if len(candidates)>1:
                diagnostics['truncated'] = True
                best_overlap = min(item[0][0] for item in candidates)
                if best_overlap == 0 or sum(item[0][0] == best_overlap for item in candidates)>1:
                    # Confidence says how well an edge was resolved, not which
                    # branch answers the question. Abstain on semantic ties.
                    diagnostics['ambiguous_branches'] += 1
                    break
            _, node, edge = min(candidates, key=lambda item:item[0])
            visited.add(node['id']);steps.append(edge)
        if steps:
            # Edges always read caller -> callee, including incoming traversal.
            paths.append({'direction':direction,'edges':steps if direction=='outgoing' else list(reversed(steps))})
    while paths and len(json.dumps(paths,ensure_ascii=False))>MAX_PATH_CHARACTERS:
        diagnostics['truncated'] = True
        paths[-1]['edges'].pop(0 if paths[-1]['direction']=='incoming' else -1)
        if not paths[-1]['edges']:
            paths.pop()
    return paths, diagnostics
