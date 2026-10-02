"""Shared cooperative work budgets for one repository operation."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps


class WorkBudgetExceeded(RuntimeError):
    """The operation stopped; its output must not be presented as complete."""


@dataclass
class RepoBudget:
    max_seconds: float = 30.0
    limits: dict[str, int] = field(default_factory=lambda: {
        'rows': 200_000, 'records': 200_000, 'bytes': 128 * 1024 * 1024,
        'io_bytes': 64 * 1024 * 1024, 'git_bytes': 8 * 1024 * 1024,
        'entries': 10_000, 'steps': 1_000_000, 'sql_steps': 10_000_000,
    })
    used: dict[str, int] = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)
    reason: str = ''

    def check(self, kind='steps', amount=1):
        if not self.reason:
            self.used[kind] = self.used.get(kind, 0) + amount
            if self.used[kind] > self.limits[kind]:
                self.reason = f'{kind} limit'
            elif time.monotonic() - self.started > self.max_seconds:
                self.reason = 'elapsed-time limit'
        if self.reason:
            raise WorkBudgetExceeded(f'repository work budget exceeded ({self.reason}); results are incomplete')

    def values(self, values, *, kind='rows'):
        self.check(kind)
        size = 256
        for value in values:
            if isinstance(value, str):
                if len(value) > 16_384:
                    self.reason = 'metadata string limit'
                    self.check()
                size += len(value.encode('utf-8', errors='replace'))
            elif isinstance(value, bytes):
                size += len(value)
        self.check('bytes', size)


CURRENT_BUDGET: ContextVar[RepoBudget | None] = ContextVar('repo_budget', default=None)


@contextmanager
def budget_scope(budget=None):
    if CURRENT_BUDGET.get() is not None:
        yield CURRENT_BUDGET.get()
        return
    active = budget or RepoBudget()
    token = CURRENT_BUDGET.set(active)
    try:
        yield active
        active.check(amount=0)
    finally:
        CURRENT_BUDGET.reset(token)


def bounded_operation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with budget_scope():
            return function(*args, **kwargs)
    return wrapped


def bounded_write(function):
    operation = bounded_operation(function)
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except WorkBudgetExceeded:
            for value in (*args, *kwargs.values()):
                connection = value if isinstance(value, sqlite3.Connection) else getattr(value, 'connection', None)
                if isinstance(connection, sqlite3.Connection):
                    connection.rollback()
            raise
    return wrapped


def checkpoint(kind='steps', amount=1):
    budget = CURRENT_BUDGET.get()
    if budget is not None:
        budget.check(kind, amount)


def budgeted(iterable):
    for item in iterable:
        checkpoint()
        yield item


class BudgetCursor(sqlite3.Cursor):
    def _budget(self):
        return CURRENT_BUDGET.get() or self.connection.work_budget

    def _check_error(self, exc):
        if isinstance(exc, sqlite3.DataError):
            self._budget().reason = 'SQLite value limit'
        self._budget().check(amount=0)

    def execute(self, sql, parameters=()):
        self.connection.validate_metadata()
        self._budget().values(parameters.values() if isinstance(parameters, dict) else parameters, kind='records')
        try:
            return super().execute(sql, parameters)
        except sqlite3.Error as exc:
            self._check_error(exc)
            raise

    def executemany(self, sql, parameters):
        self.connection.validate_metadata()
        def bounded():
            for values in parameters:
                self._budget().values(values.values() if isinstance(values, dict) else values, kind='records')
                yield values
        try:
            return super().executemany(sql, bounded())
        except sqlite3.Error as exc:
            self._check_error(exc)
            raise

    def _account(self, row):
        if row is not None:
            self._budget().values(row)
        return row

    def __next__(self):
        try:
            return self._account(super().__next__())
        except sqlite3.Error as exc:
            self._check_error(exc)
            raise

    def fetchone(self):
        try:
            return self._account(super().fetchone())
        except sqlite3.Error as exc:
            self._check_error(exc)
            raise

    def fetchall(self):
        return list(self)

    def fetchmany(self, size=None):
        result = []
        for _ in range(self.arraysize if size is None else max(0, size)):
            row = self.fetchone()
            if row is None:
                break
            result.append(row)
        return result


class BudgetConnection(sqlite3.Connection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.validate_metadata()
        self.work_budget = CURRENT_BUDGET.get() or RepoBudget()
        self.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 8 * 1024 * 1024)
        # Large ORDER BY/GROUP BY work must spill instead of retaining a corpus.
        super().execute("PRAGMA temp_store = FILE")
        super().execute("PRAGMA cache_size = -2048")
        def progress():
            try:
                (CURRENT_BUDGET.get() or self.work_budget).check('sql_steps', 1000)
                return 0
            except WorkBudgetExceeded:
                return 1
        self.set_progress_handler(progress, 1000)

    def validate_metadata(self):
        pass

    def cursor(self, factory=BudgetCursor):
        return super().cursor(factory)

    def execute(self, sql, parameters=()):
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql, parameters):
        return self.cursor().executemany(sql, parameters)

    def executescript(self, sql_script):
        self.validate_metadata()
        budget = CURRENT_BUDGET.get() or self.work_budget
        budget.check()
        try:
            return super().executescript(sql_script)
        except sqlite3.Error:
            budget.check(amount=0)
            raise

    def commit(self):
        self.validate_metadata()
        (CURRENT_BUDGET.get() or self.work_budget).check(amount=0)
        return super().commit()
