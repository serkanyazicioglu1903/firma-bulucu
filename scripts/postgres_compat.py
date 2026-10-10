"""SQLite-compatible DB facade for the existing Control Tower UI on ct_app.

A compatibility bridge, not arbitrary SQL execution for clients: only checked-in
server-side SQL should reach this module. All values use bound parameters.
The facade never connects to ct_staging or any SQLite business database.
PostgreSQL text date columns mirror the original application's schema.
"""
import re
from contextlib import contextmanager
from functools import lru_cache

from scripts.postgres_connection import sslmode_for
from scripts.staging_transaction_smoke import validate_test_url


def _nested_call(sql, function):
    """Replace nested SQLite function calls without touching aggregate MAX/MIN."""
    pattern = re.compile(r"\b" + function + r"\(", flags=re.I)
    offset = 0
    while True:
        match = pattern.search(sql, offset)
        if not match:
            return sql
        start, pos, depth = match.start(), match.end(), 1
        quoted = False
        while pos < len(sql) and depth:
            c = sql[pos]
            if c == "'":
                if quoted and pos + 1 < len(sql) and sql[pos + 1] == "'":
                    pos += 2
                    continue
                quoted = not quoted
            elif not quoted and c == "(":
                depth += 1
            elif not quoted and c == ")":
                depth -= 1
            pos += 1
        if depth:
            raise ValueError("Unclosed SQL function.")
        argument = sql[match.end():pos - 1]
        if function.lower() == "julianday":
            if re.fullmatch(r"\s*date\('now'\)\s*", argument, flags=re.I):
                replacement = "(EXTRACT(EPOCH FROM CURRENT_DATE::timestamp)/86400.0)"
            else:
                replacement = (
                    "(EXTRACT(EPOCH FROM NULLIF(CAST(" + argument +
                    " AS TEXT),'')::date::timestamp)/86400.0)"
                )
        elif function.lower() == "round":
            # SQLite accepts ROUND(double precision, digits), PostgreSQL only
            # supports the two-argument variant with NUMERIC input.
            split, nested, in_quote = -1, 0, False
            for index, c in enumerate(argument):
                if c == "'":
                    in_quote = not in_quote
                if not in_quote:
                    if c == "(": nested += 1
                    elif c == ")": nested -= 1
                    elif c == "," and nested == 0:
                        split = index
                        break
            if split >= 0:
                number = argument[:split]
                digits = argument[split + 1:]
                replacement = (
                    "(ROUND(CAST(" + number + " AS NUMERIC), " +
                    digits + "))::double precision"
                )
            else:
                offset = pos
                continue
        else:
            # SQLite MIN(x,y) and MAX(x,y) are scalar; PostgreSQL uses
            # LEAST/GREATEST, but one-argument MIN/MAX must stay aggregate.
            commas, nested, in_quote = 0, 0, False
            for c in argument:
                if c == "'":
                    in_quote = not in_quote
                if not in_quote:
                    if c == "(": nested += 1
                    elif c == ")": nested -= 1
                    elif c == "," and nested == 0: commas += 1
            if commas:
                replacement = ("LEAST" if function.lower() == "min" else "GREATEST") + "(" + argument + ")"
            else:
                offset = pos
                continue
        sql = sql[:start] + replacement + sql[pos:]
        offset = start + len(replacement)


def translate_sql(sql):
    """Translate known SQLite dialect expressions and anonymous parameters."""
    statement = str(sql)
    statement = _nested_call(statement, "julianday")
    statement = _nested_call(statement, "min")
    statement = _nested_call(statement, "max")
    statement = _nested_call(statement, "round")
    # SQLite preserves uppercase aliases such as PO / SKT, PostgreSQL folds
    # unquoted aliases to lowercase and breaks UI dataframe column access.
    statement = re.sub(
        r"\\bAS\\s+(PO|SKT)\\b",
        lambda match: 'AS "' + match.group(1) + '"',
        statement, flags=re.I,
    )
    statement = re.sub(r"\bdate\('now'\)", "CURRENT_DATE::text", statement, flags=re.I)
    # Input is checked-in SQL, not caller data. Replace positional '?' only
    # outside SQL string and double-quoted identifier literals.
    out, quoted, identifier, index = [], False, False, 0
    while index < len(statement):
        char = statement[index]
        if char == "'" and not identifier:
            if quoted and index + 1 < len(statement) and statement[index + 1] == "'":
                out.extend(("'", "'"))
                index += 2
                continue
            quoted = not quoted
        elif char == '"' and not quoted:
            identifier = not identifier
        if char == "?" and not quoted and not identifier:
            out.append("%s")
        elif char == "%":
            # Psycopg treats percent as a parameter marker even in quoted SQL.
            out.append("%%")
        else:
            out.append(char)
        index += 1
    return "".join(out)


class CompatRow:
    """sqlite3.Row-style integer/string indexing around psycopg tuples."""
    def __init__(self, columns, values):
        self._columns = tuple(columns)
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._values[self._columns.index(key)]
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def keys(self):
        return list(self._columns)

    def __len__(self):
        return len(self._values)


class Result:
    def __init__(self, cursor):
        self._cursor = cursor
        self.rowcount = cursor.rowcount

    def _columns(self):
        return [col.name for col in (self._cursor.description or [])]

    def fetchone(self):
        row = self._cursor.fetchone()
        return CompatRow(self._columns(), row) if row is not None else None

    def fetchall(self):
        columns = self._columns()
        return [CompatRow(columns, row) for row in self._cursor.fetchall()]

    @property
    def description(self):
        return self._cursor.description


@lru_cache(maxsize=2)
def _pool(url):
    from psycopg_pool import ConnectionPool
    if not validate_test_url(url):
        raise ValueError("PostgreSQL URL is required.")
    return ConnectionPool(
        conninfo=url,
        min_size=1,
        max_size=6,
        timeout=8,
        open=True,
        kwargs={"sslmode": sslmode_for(url), "connect_timeout": 8},
    )


class CompatConnection:
    def __init__(self, url):
        self.url = url
        self._connection_scope = None
        self._conn = None

    def __enter__(self):
        self._connection_scope = _pool(self.url).connection()
        self._conn = self._connection_scope.__enter__()
        self._conn.execute("SET LOCAL search_path TO ct_app, pg_catalog")
        self._conn.execute("SET LOCAL statement_timeout = '20s'")
        return self

    def __exit__(self, typ, value, tb):
        try:
            return self._connection_scope.__exit__(typ, value, tb)
        finally:
            self._conn = None
            self._connection_scope = None

    def execute(self, sql, params=()):
        from scripts.postgres_operational_write import _REQUEST_LIVE_WRITES
        from security_admin import current_user, WRITE_TABLE_PERMISSIONS
        statement = str(sql).strip()
        match = re.match(
            r"^(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([a-z_]+)\b",
            statement, re.I,
        )
        role = str((current_user() or {}).get("role", "")).upper()
        if match:
            if not _REQUEST_LIVE_WRITES.get() or not role:
                raise PermissionError("Authenticated live request required.")
            table = match.group(2).lower()
            if table not in ALLOWED_TABLES:
                raise PermissionError("Unrecognized PostgreSQL write table.")
            if role != "ADMIN" and table not in WRITE_TABLE_PERMISSIONS.get(role, set()):
                raise PermissionError("Role is not authorized for table.")
        cursor = self._conn.cursor()
        cursor.execute(translate_sql(statement), tuple(params))
        if match:
            # Audit the mutation in the same transaction, including direct
            # legacy conn.execute write paths, and never log customer values.
            actor = str((current_user() or {}).get("username", ""))[:80]
            self._conn.execute(
                'INSERT INTO "ct_app"."audit_log" '
                '(username,role,action,table_name) VALUES (%s,%s,%s,%s)',
                (actor, role, match.group(1).split()[0].upper(), match.group(2).lower()),
            )
        return Result(cursor)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()


def pg_query_df(url, sql, params=()):
    import pandas as pd
    with CompatConnection(url) as connection:
        result = connection.execute(sql, params)
        columns = [c.name for c in result.description or []]
        records = [tuple(row) for row in result.fetchall()]
    return pd.DataFrame.from_records(records, columns=columns)


def pg_execute(url, sql, params=(), *, actor, role):
    """Single-transaction mutation + audit for legacy forms."""
    from scripts.postgres_operational_write import _REQUEST_LIVE_WRITES
    if not _REQUEST_LIVE_WRITES.get():
        raise PermissionError("Verified PostgreSQL live request required.")
    statement = str(sql).strip().upper()
    table_match = re.match(
        r"^(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([A-Z_]+)",
        statement,
    )
    if not table_match:
        raise ValueError("Unsupported PostgreSQL mutation.")
    table = table_match.group(1).lower()
    if table not in ALLOWED_TABLES:
        raise PermissionError("Unsupported business table.")
    with CompatConnection(url) as conn:
        conn.execute(sql, params)  # audit automatically committed atomically


ALLOWED_TABLES = frozenset((
    "customers", "opportunities", "tasks", "contacts", "activities",
    "opportunity_stage_history", "product_catalog", "customer_product_status",
    "quotes", "warehouses", "purchase_orders", "shipments", "inventory_lots",
    "inventory_policy", "cash_accounts", "receivables", "payables",
    "finance_transactions", "cash_events", "quality_cases", "quality_actions",
    "quality_recoveries", "compliance_documents", "regulatory_items",
))
