"""Experimental local full-text retrieval with source evidence; no model calls."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sqlite3

from .graph_store import GraphStore
from .search_passages import passages, OversizedPassage
from .memory import with_live_staleness
from .metadata_db import connect_metadata
from .repo_budget import bounded_operation, checkpoint
from .repo_files import repo_snapshot
from .text_tokens import FUNCTION_WORDS, identifier_terms

SEARCH_INDEX_VERSION = 3

SCHEMA = '''
CREATE TABLE IF NOT EXISTS search_index_meta(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS search_files(path TEXT PRIMARY KEY, sha256 TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS search_chunks USING fts5(
 path UNINDEXED, sha256 UNINDEXED, first_line UNINDEXED, last_line UNINDEXED,
 excerpt UNINDEXED, names, body, tokenize='porter unicode61'
);
'''


MEMORY_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS search_notes USING fts5(
 note, topic, query, tags_json, path, content='agent_notes', content_rowid='id',
 tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS search_notes_insert AFTER INSERT ON agent_notes BEGIN
 INSERT INTO search_notes(rowid,note,topic,query,tags_json,path)
 VALUES(new.id,new.note,new.topic,new.query,new.tags_json,new.path);
END;
CREATE TRIGGER IF NOT EXISTS search_notes_delete AFTER DELETE ON agent_notes BEGIN
 INSERT INTO search_notes(search_notes,rowid,note,topic,query,tags_json,path)
 VALUES('delete',old.id,old.note,old.topic,old.query,old.tags_json,old.path);
END;
CREATE TRIGGER IF NOT EXISTS search_notes_update AFTER UPDATE ON agent_notes BEGIN
 INSERT INTO search_notes(search_notes,rowid,note,topic,query,tags_json,path)
 VALUES('delete',old.id,old.note,old.topic,old.query,old.tags_json,old.path);
 INSERT INTO search_notes(rowid,note,topic,query,tags_json,path)
 VALUES(new.id,new.note,new.topic,new.query,new.tags_json,new.path);
END;
"""


def searchable_path(path):
    name = Path(path).name.lower()
    return not (name.startswith('.env') or name in {'credentials.json', 'secrets.json', 'id_rsa', 'id_ed25519'}
                or Path(path).suffix.lower() in {'.pem', '.key', '.p12', '.pfx'})


def terms(text):
    return [t for t in identifier_terms(text) if t not in FUNCTION_WORDS]


@bounded_operation
def update_search_index(root: Path):
    """Maintain source passages; rebuild older formats even with unchanged hashes."""
    with GraphStore(root) as store:
        conn = store.connection
        conn.executescript(SCHEMA)
        had_notes = conn.execute("SELECT 1 FROM sqlite_master WHERE name='search_notes'").fetchone()
        conn.executescript(MEMORY_SCHEMA)
        if not had_notes:
            conn.execute("INSERT INTO search_notes(search_notes) VALUES('rebuild')")
            conn.commit()
        result = {'updated': 0, 'removed': 0, 'skipped': [], 'rebuilt': False,
                  'index_version': SEARCH_INDEX_VERSION}
        try:
            conn.execute('BEGIN IMMEDIATE')
            version_row = conn.execute("SELECT value FROM search_index_meta WHERE key='version'").fetchone()
            version = version_row[0] if version_row else 0
            if version > SEARCH_INDEX_VERSION:
                raise ValueError('Search index is newer than this implementation; upgrade before maintenance')
            result['rebuilt'] = version != SEARCH_INDEX_VERSION
            if result['rebuilt']:
                conn.execute('DELETE FROM search_chunks')
                conn.execute('DELETE FROM search_files')
            indexed = {p: h for p, h in store.file_hashes().items() if searchable_path(p)}
            previous = dict(conn.execute('SELECT path,sha256 FROM search_files'))
            removed = previous.keys() - indexed.keys()
            retired = [path for path, sha in previous.items() if indexed.get(path) != sha]
            result['removed'] = len(removed)
            if retired:
                # FTS path is UNINDEXED: one delete per file scans the whole
                # corpus repeatedly. Visit it once for the entire changed set.
                conn.execute('CREATE TEMP TABLE search_retired_paths(path TEXT PRIMARY KEY)')
                conn.executemany('INSERT INTO search_retired_paths VALUES(?)', ((path,) for path in retired))
                conn.execute('DELETE FROM search_chunks WHERE path IN (SELECT path FROM search_retired_paths)')
                conn.execute('DELETE FROM search_files WHERE path IN (SELECT path FROM search_retired_paths)')
            for path, sha in indexed.items():
                checkpoint()
                if previous.get(path) == sha:
                    continue
                try:
                    snapshot = repo_snapshot(root, path)
                except OSError:
                    result['skipped'].append(path)
                    continue
                if snapshot.sha256 != sha or snapshot.content is None:
                    result['skipped'].append(path)
                    continue
                lines = snapshot.content.splitlines()
                symbols = list(conn.execute('SELECT s.name,s.line,s.end_line FROM symbols s JOIN files f ON f.id=s.file_id WHERE f.path=?', (path,)))
                records = []
                try:
                    for first, last, excerpt, enclosing in passages(lines, symbols):
                        names = ' '.join(terms(path + ' ' + ' '.join(enclosing)))
                        body = ' '.join(terms(excerpt))
                        if max(len(names), len(body), len(excerpt)) > 16384:
                            raise OversizedPassage('passage field exceeds metadata string limit')
                        checkpoint('bytes', len(body.encode()) + len(excerpt.encode()) + len(names.encode()))
                        records.append((path, sha, first, last, excerpt, names, body))
                except OversizedPassage:
                    result['skipped'].append(path)
                    continue
                conn.executemany('INSERT INTO search_chunks VALUES(?,?,?,?,?,?,?)', records)
                conn.execute('INSERT INTO search_files VALUES(?,?)', (path, sha))
                result['updated'] += 1
            conn.execute("INSERT OR REPLACE INTO search_index_meta VALUES('version',?)", (SEARCH_INDEX_VERSION,))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        result['skipped_count'] = len(result['skipped'])
        result['skipped'] = result['skipped'][:20]
        return result


def _proximity(row, query_terms):
    """Smallest token window containing the literal query terms; no synonyms."""
    wanted = set(query_terms)
    if len(wanted) < 2:
        return 0
    checkpoint('bytes', len(row['excerpt'].encode()))
    words = terms(row['excerpt'])
    checkpoint('steps', len(words))
    counts, left, best = {}, 0, len(words) + 1
    for right, word in enumerate(words):
        if word in wanted:
            counts[word] = counts.get(word, 0) + 1
        while len(counts) == len(wanted):
            best = min(best, right - left + 1)
            first = words[left]
            if first in counts:
                counts[first] -= 1
                if not counts[first]:
                    del counts[first]
            left += 1
    return best if best <= len(words) else float('inf')


def _source_candidates(conn, query, query_terms, path_prefixes):
    # Independent bounded channels keep exact definitions from being crowded out
    # by repeated textual mentions. No file roles or repository names get bonuses.
    scope = (' AND (' + ' OR '.join('substr(path,1,length(?))=?' for _ in path_prefixes) + ')') if path_prefixes else ''
    scope_args = [v for p in path_prefixes for v in (p,p)]
    candidates, capped = {}, []

    def merge(rows, channel):
        if len(rows) == 80:
            capped.append(channel)
        for raw in rows:
            row = dict(raw)
            key = (row['path'], row['first_line'])
            if key not in candidates:
                candidates[key] = {**row, 'channels': []}
            candidates[key]['channels'].append(channel)

    quoted = ['"' + t.replace('"', '""') + '"' for t in query_terms]
    for channel, separator in [('all_terms', ' AND '), ('any_term', ' OR ')]:
        expression = separator.join(quoted)
        # Diversify before the global cap: post-cap deduplication loses files
        # when one large document supplies most of the best-ranked chunks.
        sql = ('WITH hits AS MATERIALIZED ('
               'SELECT *,bm25(search_chunks,0,0,0,0,0,2,1) AS rank '
               'FROM search_chunks WHERE search_chunks MATCH ?' + scope + '), '
               'diverse AS (SELECT *,ROW_NUMBER() OVER ('
               'PARTITION BY path ORDER BY rank,CAST(first_line AS INTEGER)) AS file_rank FROM hits) '
               'SELECT * FROM diverse WHERE file_rank<=2 '
               'ORDER BY rank,path,CAST(first_line AS INTEGER) LIMIT 80')
        rows = list(conn.execute(sql, [expression,*scope_args]))
        merge(rows,channel)

    # A one-item query may name an actual symbol or a repository path.
    literal = query.strip().strip('`"')
    if literal and not any(c.isspace() for c in literal):
        exact_scope = (' AND (' + ' OR '.join('substr(c.path,1,length(?))=?' for _ in path_prefixes) + ')') if path_prefixes else ''
        rows = list(conn.execute("SELECT DISTINCT c.*,0.0 AS rank FROM search_chunks c JOIN files f ON f.path=c.path LEFT JOIN symbols s ON s.file_id=f.id AND s.line BETWEEN CAST(c.first_line AS INTEGER) AND CAST(c.last_line AS INTEGER) WHERE (f.path=? OR (s.kind NOT IN ('heading','command_example') AND (s.name=? OR s.qualified_name=?)))" + exact_scope + ' ORDER BY c.path,CAST(c.first_line AS INTEGER) LIMIT 80', [literal,literal,literal,*scope_args]))
        merge(rows,'exact_symbol_or_path')
    rows = sorted(candidates.values(), key=lambda row: (
        'exact_symbol_or_path' not in row['channels'],
        'all_terms' not in row['channels'],
        _proximity(row,query_terms), row['rank'], row['path'], int(row['first_line'])))
    return rows, capped


@bounded_operation
def search(root: Path, query: str, limit=3, path_prefixes=()):
    if not 1 <= limit <= 10 or len(query) > 1000:
        raise ValueError('limit must be 1..10; query at most 1000 characters')
    if len(path_prefixes) > 8 or any(Path(p).is_absolute() or '..' in Path(p).parts for p in path_prefixes):
        raise ValueError('Use at most eight repository-relative path prefixes')
    # The character limit above bounds the FTS expression. Do not silently
    # discard late task details, including terms used to retrieve SQL notes.
    query_terms = list(dict.fromkeys(terms(query)))
    result = {'query': query, 'terms': query_terms, 'results': [], 'memories': [], 'stale_candidates': [],
              'path_prefixes': list(path_prefixes), 'candidate_limit_per_channel': 80, 'warnings': [], 'excerpt_character_limit': 1400}
    if not query_terms:
        return result
    expression = ' OR '.join('"' + t.replace('"', '""') + '"' for t in query_terms)
    conn = connect_metadata(root, readonly=True)
    conn.row_factory = sqlite3.Row
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='search_chunks'").fetchone():
            raise ValueError('Search index missing; run local_watch --once first')
        note_rows = [dict(r) for r in conn.execute('SELECT n.id,n.path,n.scope,n.topic,n.note,n.file_sha256,n.evidence,n.source,n.created_at FROM search_notes JOIN agent_notes n ON n.id=search_notes.rowid WHERE search_notes MATCH ? ORDER BY bm25(search_notes) LIMIT 3', (expression,))]
        for note in with_live_staleness(root, note_rows):
            note['note_truncated'] = len(note['note']) > 1000
            note['note'] = note['note'][:1000]
            result['memories'].append(note)
        rows, capped = _source_candidates(conn,query,query_terms,path_prefixes)
        result['candidate_limit_reached'] = bool(capped)
        result['capped_channels'] = capped
        result['candidate_count'] = len(rows)
        snapshots, seen = {}, set()
        for row in rows:
            path = row['path']
            if path in seen or not searchable_path(path):
                continue
            if path not in snapshots:
                try:
                    snapshots[path] = repo_snapshot(root, path)
                except OSError:
                    snapshots[path] = None
            snapshot = snapshots[path]
            if snapshot is None or snapshot.sha256 != row['sha256']:
                seen.add(path)
                result['stale_candidates'].append(path)
                continue
            seen.add(path)
            lines = row['excerpt'].splitlines()
            # Center the returned evidence on a matching line within the hit chunk.
            position = max(range(len(lines)), key=lambda i: len(set(terms(lines[i])) & set(query_terms))) if lines else 0
            start = max(0, position-3)
            selected = lines[start:start+12]
            text = '\n'.join(selected)
            first = int(row['first_line']) + start
            symbols = [dict(s) for s in conn.execute('SELECT s.name,s.kind,s.line,s.end_line FROM symbols s JOIN files f ON f.id=s.file_id WHERE f.path=? AND s.line<=? AND (s.end_line>=? OR s.line>=?) ORDER BY s.line DESC LIMIT 3', (path, first+len(selected)-1, first, first))]
            links = [dict(r) for r in conn.execute("SELECT r.relation,f.path AS source,r.target_id AS target,r.confidence FROM relations r JOIN files f ON f.id=r.source_id WHERE r.source_type='file' AND r.target_type='resolved_file' AND (f.path=? OR r.target_id=?) ORDER BY r.confidence DESC,f.path,r.target_id LIMIT 4", (path,path))]
            result['results'].append({'path': path, 'sha256': snapshot.sha256,
                'start_line': first, 'end_line': first+len(selected)-1,
                'excerpt': text[:1400], 'excerpt_truncated': len(text)>1400,
                'bm25': row['rank'], 'retrieval': row['channels'], 'symbols': symbols, 'graph_links': links})
            if len(result['results']) >= limit:
                break
        if result['stale_candidates']:
            result['warnings'].append('Changed or missing candidates omitted; maintenance must catch up.')
        result['warnings'].append('Graph links are index evidence, not proof of test coverage or semantic correctness.')
        return result
    finally:
        conn.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query')
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--limit',type=int,default=3)
    parser.add_argument('--path-prefix',action='append',default=[],help='Restrict source hits; repeat for multiple directories')
    args=parser.parse_args(argv)
    try:
        print(json.dumps(search(args.root.resolve(),args.query,args.limit,args.path_prefix),indent=2,ensure_ascii=False))
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({'status':'error','error':str(exc)}))
        return 1

if __name__=='__main__':
    raise SystemExit(main())
