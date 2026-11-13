"""Portable database access: SQLite locally, PostgreSQL on a serverless host.

Every module (``core``, ``push``, ``whatsapp``, ``email_alerts``,
``google_integration``) opens its database through :func:`connect` and then runs
plain SQL with ``?`` placeholders. That is all SQLite needs on a laptop.

A serverless host such as Vercel gives the function a read-only and ephemeral
filesystem, so the same code must talk to a real database. Set ``DATABASE_URL``
to a PostgreSQL connection string (Neon, Supabase, Vercel Postgres, ...) and the
identical SQL runs against PostgreSQL instead.

Only the connection object changes. :class:`PostgresConnection` rewrites the few
SQLite-only constructs:

* ``?`` placeholders become ``%s``
* ``INSERT OR IGNORE INTO t`` becomes ``INSERT INTO t ... ON CONFLICT DO NOTHING``
* ``BEGIN IMMEDIATE`` becomes ``BEGIN``
* ``PRAGMA ...`` statements are dropped

Rows are mappings on both backends, so ``row['column']`` works everywhere.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
DB_DEFAULT = ROOT / 'data' / 'executive_desk.db'

_INSERT_OR_IGNORE = re.compile(r'^\s*INSERT\s+OR\s+IGNORE\s+INTO\b', re.IGNORECASE)
_PRAGMA = re.compile(r'^\s*PRAGMA\b', re.IGNORECASE)
_BEGIN_IMMEDIATE = re.compile(r'\bBEGIN\s+IMMEDIATE\b', re.IGNORECASE)


def database_url() -> str:
    """The configured PostgreSQL URL, or '' when the app runs on SQLite."""
    return (os.environ.get('DATABASE_URL') or '').strip()


def is_postgres() -> bool:
    return database_url().startswith(('postgres://', 'postgresql://'))


def translate(sql: str) -> Optional[str]:
    """Rewrite SQLite SQL for PostgreSQL. ``None`` means 'skip this statement'."""
    if _PRAGMA.match(sql):
        return None
    ignore = bool(_INSERT_OR_IGNORE.match(sql))
    sql = _INSERT_OR_IGNORE.sub('INSERT INTO', sql, count=1)
    sql = sql.replace('?', '%s')
    sql = _BEGIN_IMMEDIATE.sub('BEGIN', sql)
    if ignore:
        sql = sql.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'
    return sql


class _EmptyCursor:
    """Returned for statements the target backend does not need to run."""

    rowcount = 0

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def __iter__(self):
        return iter(())


class PostgresConnection:
    """Minimal ``sqlite3.Connection`` look-alike backed by psycopg."""

    def __init__(self, dsn: str):
        import psycopg
        from psycopg.rows import dict_row
        # autocommit mirrors sqlite3's isolation_level=None: each statement takes
        # effect immediately, while an explicit BEGIN/COMMIT around a
        # compare-and-swap still groups those statements into one transaction.
        self._conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

    def execute(self, sql: str, params: Iterable[Any] = ()):
        text = translate(sql)
        if text is None:
            return _EmptyCursor()
        cur = self._conn.cursor()
        cur.execute(text, tuple(params) if params else None)
        return cur

    def executescript(self, script: str) -> None:
        for statement in script.split(';'):
            if statement.strip():
                self.execute(statement)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False


def connect(path: Optional[str | Path] = None):
    """Open the application database — PostgreSQL when ``DATABASE_URL`` is set."""
    if is_postgres():
        return PostgresConnection(database_url())
    p = Path(path or os.environ.get('EDA_DB_PATH') or DB_DEFAULT)
    p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(p, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=10000')
    db.execute('PRAGMA foreign_keys=ON')
    return db
