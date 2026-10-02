"""Limits apply before mutation and again at the SQLite persistence boundary."""
from functools import wraps
import inspect
import sqlite3
from .repo_budget import budget_scope

MAX_ITEMS = 128
MAX_STRING = 4096
MAX_INPUT_BYTES = 65536
MAX_STORAGE_BYTES = 64 * 1024 * 1024
TABLE_LIMITS = {
    'orientation_feedback': 5000, 'agent_notes': 1000, 'agent_tasks': 1000,
    'agent_task_notes': 5000, 'reading_plans': 1000, 'reading_plan_items': 10000,
    'reading_plan_events': 10000, 'reading_plan_workstreams': 1000,
}


def validate_input(value):
    remaining = MAX_INPUT_BYTES
    nodes = 0
    def visit(item, depth=0):
        nonlocal remaining, nodes
        nodes += 1
        if depth > 8 or nodes > 2048:
            raise ValueError('metadata input exceeds nesting/node limit')
        if isinstance(item, str):
            if len(item) > MAX_STRING:
                raise ValueError('metadata string exceeds 4096 characters')
            remaining -= len(item.encode('utf-8'))
        elif isinstance(item, (list, tuple, dict)):
            if len(item) > MAX_ITEMS:
                raise ValueError('metadata collection exceeds 128 items')
            if isinstance(item, dict):
                for key, val in item.items():
                    visit(key, depth + 1)
                    visit(val, depth + 1)
            else:
                for val in item:
                    visit(val, depth + 1)
        elif item is not None and not isinstance(item, (bool, int, float)):
            raise ValueError('unsupported metadata input type')
        if remaining < 0:
            raise ValueError('metadata input exceeds 64 KiB')
    visit(value)


def bounded_metadata(function):
    signature = inspect.signature(function)
    @wraps(function)
    def wrapped(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        validate_input({k: v for k, v in bound.arguments.items() if k != 'root'})
        try:
            with budget_scope():
                return function(*args, **kwargs)
        except sqlite3.IntegrityError as exc:
            if 'metadata quota' in str(exc):
                raise ValueError(str(exc)) from exc
            raise
    return wrapped


def install_quotas(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS metadata_usage (name TEXT PRIMARY KEY, records INTEGER NOT NULL, bytes INTEGER NOT NULL)')
    for table, limit in TABLE_LIMITS.items():
        columns = [row['name'] for row in conn.execute(f'PRAGMA table_info({table})')]
        def size(prefix):
            return '64 + ' + ' + '.join(f'COALESCE(length(CAST({prefix}"{col}" AS BLOB)), 0)' for col in columns)
        new, old = size('NEW.'), size('OLD.')
        # Seed once for pre-existing indexes. Quota accounting is transactional.
        if conn.execute('SELECT 1 FROM metadata_usage WHERE name = ?', (table,)).fetchone() is None:
            conn.execute(f'INSERT INTO metadata_usage SELECT ?, COUNT(*), COALESCE(SUM({size("")}), 0) FROM {table}', (table,))
        for event in ('INSERT', 'UPDATE'):
            delta = f'({new})' if event == 'INSERT' else f'({new}) - ({old})'
            row_check = f"OR (SELECT records FROM metadata_usage WHERE name = '{table}') >= {limit}" if event == 'INSERT' else ''
            # The compressed index manifest has its own larger bounded field.
            record_limit = 512 * 1024 if table == 'reading_plans' else 32768
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS quota_{table}_{event.lower()} BEFORE {event} ON {table}
                WHEN ({new}) > {record_limit} {row_check}
                  OR (SELECT SUM(bytes) FROM metadata_usage) + ({delta}) > {MAX_STORAGE_BYTES}
                BEGIN SELECT RAISE(ABORT, 'metadata quota exceeded; export or remove old metadata before retrying'); END''')
            record_delta = 1 if event == 'INSERT' else 0
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS usage_{table}_{event.lower()} AFTER {event} ON {table}
                BEGIN UPDATE metadata_usage SET records = records + {record_delta}, bytes = bytes + ({delta}) WHERE name = '{table}'; END''')
        conn.execute(f'''CREATE TRIGGER IF NOT EXISTS usage_{table}_delete AFTER DELETE ON {table}
            BEGIN UPDATE metadata_usage SET records = records - 1, bytes = bytes - ({old}) WHERE name = '{table}'; END''')
