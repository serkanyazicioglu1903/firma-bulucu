"""Read-only PostgreSQL ct_staging structure audit against checked-in SQLite schema.

No business rows, data changes, or passwords are read or returned.
"""
from collections import Counter, defaultdict
from urllib.parse import urlsplit

from scripts.build_pg_schema import column_type, sqlite_schema


SCHEMA = "ct_staging"


def expected_structure():
    """Derive authoritative table, column, PK, UNIQUE and FK metadata offline."""
    tables = {}
    with sqlite_schema() as source:
        names = [
            row[0] for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
            )
        ]
        for name in names:
            info = source.execute('PRAGMA table_info("' + name + '")').fetchall()
            primary = sorted((row for row in info if row[5]), key=lambda row: row[5])
            identity = (
                len(primary) == 1 and primary[0][2].upper() == "INTEGER"
            )
            columns = {}
            for row in info:
                _, col, kind, notnull, _, pk = row
                columns[col] = (
                    column_type(kind).lower(),
                    "NO" if notnull or pk else "YES",
                    "YES" if identity and pk else "NO",
                )
            constraints = []
            if primary:
                constraints.append(("p", tuple(r[1] for r in primary), None, ()))
            for index in source.execute('PRAGMA index_list("' + name + '")'):
                if index[3] == "u":
                    cols = [
                        row[2] for row in source.execute(
                            'PRAGMA index_info("' + index[1] + '")'
                        )
                    ]
                    constraints.append(("u", tuple(cols), None, ()))
            groups = defaultdict(list)
            for key in source.execute('PRAGMA foreign_key_list("' + name + '")'):
                groups[key[0]].append(key)
            for group in groups.values():
                ordered = sorted(group, key=lambda r: r[1])
                constraints.append(
                    (
                        "f",
                        tuple(r[3] for r in ordered),
                        ordered[0][2],
                        tuple(r[4] for r in ordered),
                    )
                )
            tables[name] = {"columns": columns, "constraints": constraints}
    return tables


def compare_structure(expected, actual_columns, actual_constraints):
    """Return only structural discrepancies, never business records."""
    differences = []
    for table, specification in expected.items():
        cols = actual_columns.get(table, {})
        if not cols:
            differences.append(table + ": tablo/sütun bulunamadı")
            continue
        for col, wanted in specification["columns"].items():
            found = cols.get(col)
            if found is None:
                differences.append(table + "." + col + ": sütun eksik")
            elif found != wanted:
                differences.append(table + "." + col + ": veri tipi veya zorunluluk uyumsuz")
        for col in set(cols) - set(specification["columns"]):
            differences.append(table + "." + col + ": beklenmeyen sütun")
        expected_keys = Counter(specification["constraints"])
        actual_keys = Counter(actual_constraints.get(table, []))
        for definition, count in (expected_keys - actual_keys).items():
            differences.append(
                table + ": " + definition[0] + " kısıtı eksik (" + str(count) + ")"
            )
        for definition, count in (actual_keys - expected_keys).items():
            differences.append(
                table + ": beklenmeyen " + definition[0] + " kısıtı (" + str(count) + ")"
            )
    for table in set(actual_columns) - set(expected):
        # migration_check is the previously authorized connection-test table.
        if table != "migration_check":
            differences.append(table + ": beklenmeyen tablo")
    return sorted(differences)


def validate_staging_structure(url):
    """Read-only metadata check with safe, bounded public diagnostic messages."""
    if not url or not str(url).strip():
        return "missing", []
    try:
        parsed = urlsplit(str(url).strip())
        if parsed.scheme not in ("postgresql", "postgres") or not parsed.hostname:
            return "invalid_url", []
    except ValueError:
        return "invalid_url", []

    try:
        import psycopg

        expected = expected_structure()
        actual_columns = defaultdict(dict)
        actual_constraints = defaultdict(list)
        with psycopg.connect(
            str(url).strip(), connect_timeout=8, sslmode="require"
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(
                    "SELECT table_name, column_name, data_type, is_nullable, is_identity "
                    "FROM information_schema.columns WHERE table_schema = %s "
                    "ORDER BY table_name, ordinal_position",
                    (SCHEMA,),
                )
                for table, col, kind, nullable, identity in cur.fetchall():
                    actual_columns[table][col] = (
                        kind.lower(), nullable, identity
                    )
                cur.execute(
                    "SELECT tbl.relname, con.contype, "
                    "(SELECT array_agg(att.attname ORDER BY k.ord) "
                    " FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord) "
                    " JOIN pg_catalog.pg_attribute AS att "
                    " ON att.attrelid = con.conrelid AND att.attnum = k.attnum), "
                    "ref.relname, "
                    "(SELECT array_agg(att.attname ORDER BY k.ord) "
                    " FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord) "
                    " JOIN pg_catalog.pg_attribute AS att "
                    " ON att.attrelid = con.confrelid AND att.attnum = k.attnum) "
                    "FROM pg_catalog.pg_constraint AS con "
                    "JOIN pg_catalog.pg_class AS tbl ON tbl.oid = con.conrelid "
                    "JOIN pg_catalog.pg_namespace AS ns ON ns.oid = tbl.relnamespace "
                    "LEFT JOIN pg_catalog.pg_class AS ref ON ref.oid = con.confrelid "
                    "WHERE ns.nspname = %s AND con.contype IN ('p', 'u', 'f')",
                    (SCHEMA,),
                )
                for table, kind, columns, referenced, reference_columns in cur.fetchall():
                    actual_constraints[table].append(
                        (
                            kind,
                            tuple(columns or ()),
                            referenced if kind == "f" else None,
                            tuple(reference_columns or ()) if kind == "f" else (),
                        )
                    )
        differences = compare_structure(expected, actual_columns, actual_constraints)
        return ("mismatch", differences) if differences else ("ok", [])
    except Exception:
        # No raw DB exception should reach UI; these can contain the connection URI.
        return "failed", []
