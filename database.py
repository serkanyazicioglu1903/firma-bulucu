"""Explicit application backend. Startup validates PostgreSQL; it never migrates it.

SQLite remains the default. DATABASE_URL is deliberately not consulted. Configure
AS_CONTROL_TOWER_BACKEND=postgres and AS_CONTROL_TOWER_POSTGRES_URL separately.
"""
import os
import re
import sqlite3
from functools import lru_cache

import pandas as pd


def is_postgres():
    backend = os.environ.get('AS_CONTROL_TOWER_BACKEND', 'sqlite')
    if backend not in ('sqlite', 'postgres'):
        raise ValueError('AS_CONTROL_TOWER_BACKEND must be sqlite or postgres.')
    return backend == 'postgres'


def pg_config():
    url = os.environ.get('AS_CONTROL_TOWER_POSTGRES_URL', '')
    schema = os.environ.get('AS_CONTROL_TOWER_POSTGRES_SCHEMA', 'ct_staging')
    if not url:
        raise ValueError('PostgreSQL seçildi ancak özel bağlantı ayarı eksik.')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', schema) or schema in ('public', 'information_schema') or schema.startswith('pg_'):
        raise ValueError('Ayrı bir uygulama şeması gerekli.')
    from psycopg.conninfo import conninfo_to_dict
    cfg = conninfo_to_dict(url)
    if cfg.get('options') or cfg.get('service'):
        raise ValueError('Connection options and service overrides are not supported.')
    return url, schema


@lru_cache(maxsize=512)
def postgres_sql(sql):
    """Parse SQL rather than replacing question marks inside literals/comments."""
    import sqlglot
    from sqlglot import exp
    statements = sqlglot.parse(sql, read='sqlite')
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union, exp.Insert, exp.Update, exp.Delete)):
        raise ValueError('Application queries must be a single SELECT/INSERT/UPDATE/DELETE statement.')
    tree = statements[0]
    def adapt(node):
        if isinstance(node, exp.Round) and node.args.get("decimals") is not None:
            node.set("this", exp.Cast(this=node.this, to=exp.DataType.build("DECIMAL")))
        if isinstance(node, exp.Date) and node.this == exp.Literal.string('now'):
            return exp.Cast(this=exp.CurrentDate(), to=exp.DataType.build('TEXT'))
        if isinstance(node, exp.Anonymous) and node.name.upper() == 'JULIANDAY':
            node.set('this', 'ct_julianday')
            node.set('expressions', [exp.Cast(this=x, to=exp.DataType.build('TEXT')) for x in node.expressions])
        return node
    # psycopg interprets % only with parameters. Escape literal percent tokens
    # before replacing AST placeholders, preserving e.g. LIKE '%food?%'.
    tree = tree.transform(adapt)
    marker = '__CT_BIND_PARAMETER__'
    while marker in sql:
        marker += '_'
    placeholders = list(tree.find_all(exp.Placeholder))
    for placeholder in placeholders:
        placeholder.replace(exp.Var(this=marker))
    result = tree.sql(dialect='postgres', unsupported_level=sqlglot.ErrorLevel.RAISE)
    return result.replace('%', '%%').replace(marker, '%s')


class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def row_factory(cursor):
    names = [c.name for c in cursor.description] if cursor.description else []
    return lambda values: Row(zip(names, values))


class Cursor:
    def __init__(self, cursor, lastrowid=None):
        self.cursor, self.lastrowid = cursor, lastrowid
    def fetchone(self):
        return self.cursor.fetchone()
    def fetchall(self):
        return self.cursor.fetchall()
    @property
    def rowcount(self):
        return self.cursor.rowcount
    @property
    def description(self):
        return self.cursor.description


@lru_cache(maxsize=1)
def identity_tables():
    from scripts.build_pg_schema import sqlite_schema
    with sqlite_schema() as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return frozenset(t for t in tables if any(r[1] == 'id' and r[5] for r in conn.execute(f'PRAGMA table_info("{t}")')))


class PostgresConnection:
    def __init__(self, url, schema):
        import psycopg
        from psycopg import sql
        self.conn = psycopg.connect(url, row_factory=row_factory, connect_timeout=5)
        self._write_locked = False
        try:
            # Session settings survive explicit commit() calls in existing services.
            self.conn.execute(sql.SQL('SET search_path TO {}, pg_catalog').format(sql.Identifier(schema)))
            self.conn.execute("SET TIME ZONE 'UTC'")
            self.conn.execute("SET lock_timeout TO '10s'")
            self.conn.execute("SET statement_timeout TO '30s'")
            self.conn.commit()
        except BaseException:
            self.conn.close()
            raise
    def __enter__(self):
        return self
    def __exit__(self, kind, value, tb):
        try:
            self.conn.rollback() if kind else self.conn.commit()
        finally:
            self.conn.close()
    def execute(self, statement, params=()):
        if statement.strip().upper() == 'BEGIN IMMEDIATE':
            self._write_locked = True
            return Cursor(self.conn.execute('SELECT pg_advisory_xact_lock(26061028)'))
        if not self._write_locked and re.match(r'\s*(INSERT|UPDATE|DELETE)\b', statement, re.I):
            # Ordinary CRUD and compound services share the same write lock.
            self.conn.execute('SELECT pg_advisory_xact_lock(26061028)')
            self._write_locked = True
        translated = postgres_sql(statement)
        match = re.match(r'\s*INSERT\s+INTO\s+([a-z_]+)', statement, re.I)
        returning = bool(match and match.group(1).lower() in identity_tables() and 'RETURNING' not in statement.upper())
        if returning:
            translated = translated.rstrip(';') + ' RETURNING id'
        cur = self.conn.execute(translated, tuple(x.item() if hasattr(x, 'item') else x for x in params))
        row = cur.fetchone() if returning else None
        return Cursor(cur, row['id'] if row else None)
    def commit(self):
        self.conn.commit()
        self._write_locked = False
    def rollback(self):
        self.conn.rollback()
        self._write_locked = False
    def close(self):
        self.conn.close()


class SQLiteConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(db_path):
    if is_postgres():
        return PostgresConnection(*pg_config())
    conn = sqlite3.connect(db_path, check_same_thread=False, factory=SQLiteConnection)
    conn.row_factory = sqlite3.Row
    return conn


def frame(conn, sql, params=()):
    cur = conn.execute(sql, params)
    return pd.DataFrame.from_records([dict(row) for row in cur.fetchall()], coerce_float=True, columns=[c[0] for c in cur.description])


def query_df(db_path, sql, params=()):
    with connect(db_path) as conn:
        return frame(conn, sql, params)


def table_names(conn):
    if isinstance(conn, PostgresConnection):
        return [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() ORDER BY tablename").fetchall()]
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]


def validate_schema(db_path):
    """Read-only structural check; no fallback or automatic migrations."""
    from psycopg.rows import tuple_row
    from scripts.staging_validate import expected_structure, read_structure, compare_structure
    _, schema = pg_config()
    with connect(db_path) as conn:
        with conn.conn.cursor(row_factory=tuple_row) as cur:
            cur.execute('SET TRANSACTION READ ONLY')
            columns, constraints = read_structure(cur, schema)
            differences = compare_structure(expected_structure(), columns, constraints)
            if differences:
                raise RuntimeError('PostgreSQL şeması hazır değil: ' + '; '.join(differences[:5]) +
                                   '. Otomatik değişiklik yapılmadı.')
            cur.execute("SELECT to_regprocedure('ct_julianday(text)')")
            if not cur.fetchone()[0]:
                raise RuntimeError('PostgreSQL tarih yardımcı işlevi eksik; şema güncellemesi gerekli.')
            cur.execute("""SELECT COUNT(*) FROM pg_trigger
                WHERE tgrelid='quotes'::regclass AND tgname='workflow_quote_frozen'
                AND tgenabled IN ('O','A')""")
            if cur.fetchone()[0] != 1:
                raise RuntimeError('Siparişe bağlı teklif kilidi eksik veya devre dışı.')
