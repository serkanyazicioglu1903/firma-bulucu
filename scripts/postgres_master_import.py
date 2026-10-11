"""Preview-first, insert-only CSV import for ct_app master records.

No import runs on page load. This module never updates/deletes existing data,
imports financial transactions, invents company records, or touches ct_staging.
The caller must be an authenticated ADMIN and provide explicit per-batch
confirmation after taking a PostgreSQL backup.

All three master tables are allowlisted; the target table/columns are never
derived from uploaded CSV headers. Every batch is validated before any SQL,
then inserted atomically with an actor-specific audit entry per record.
"""
import csv
from io import StringIO
from pathlib import PurePath

from scripts.postgres_connection import sslmode_for
from scripts.staging_transaction_smoke import validate_test_url
from scripts.staging_validate import validate_staging_structure

MAX_UPLOAD_BYTES = 512 * 1024
MAX_ROWS = 150
APPROVAL = "ONAYLI_KALICI_AKTARIM"

# Explicit app-schema names, allowed columns and safe defaults.
DOMAINS = {
    "Müşteriler": {
        "table": "customers",
        "columns": ("name", "country", "sector", "status", "owner",
                    "contact_name", "contact_email", "phone"),
        "required": ("name",),
        "defaults": {"country": "Türkiye", "status": "Potansiyel"},
    },
    "Ürünler": {
        "table": "product_catalog",
        "columns": ("name", "category", "supplier", "supplier_country",
                    "target_sectors", "applications", "default_currency", "notes"),
        "required": ("name", "supplier"),
        "defaults": {"default_currency": "EUR"},
    },
    "Depolar": {
        "table": "warehouses",
        "columns": ("name", "warehouse_type", "city", "notes"),
        "required": ("name",),
        "defaults": {"warehouse_type": "Normal Depo"},
    },
}
LENGTHS = {
    "name": 180, "country": 100, "sector": 180, "status": 50,
    "owner": 80, "contact_name": 160, "contact_email": 200, "phone": 60,
    "category": 150, "supplier": 180, "supplier_country": 100,
    "target_sectors": 500, "applications": 1000,
    "default_currency": 3, "warehouse_type": 40, "city": 120,
    "notes": 1200,
}
CURRENCIES = frozenset(("EUR", "USD", "GBP", "TRY"))
WAREHOUSE_TYPES = frozenset(("Normal Depo", "Antrepo", "Soğuk Depo"))


def template_csv(domain):
    """Return a UTF-8 BOM CSV header only: never contain fictional demo rows."""
    if domain not in DOMAINS:
        raise ValueError("unknown_domain")
    output = StringIO(newline="")
    csv.writer(output).writerow(DOMAINS[domain]["columns"])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _clean_rows(domain, raw_rows):
    """Strictly verify in-memory rows independently of any Streamlit preview."""
    config = DOMAINS.get(domain)
    if config is None or not isinstance(raw_rows, list):
        return "invalid_domain", []
    if not raw_rows or len(raw_rows) > MAX_ROWS:
        return "invalid_row_count", []
    allowed = set(config["columns"])
    seen_names = set()
    records = []
    for row in raw_rows:
        if not isinstance(row, dict) or set(row) - allowed:
            return "invalid_columns", []
        cleaned = {}
        for field in config["columns"]:
            value = row.get(field, "")
            if not isinstance(value, str):
                return "invalid_values", []
            value = value.strip()
            if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
                return "invalid_values", []
            if len(value) > LENGTHS[field]:
                return "invalid_values", []
            cleaned[field] = value or config["defaults"].get(field, "")
        if any(not cleaned[field] for field in config["required"]):
            return "required_field_missing", []
        normalized_name = cleaned["name"].casefold()
        if normalized_name in seen_names:
            return "duplicate_in_file", []
        seen_names.add(normalized_name)
        if domain == "Ürünler" and cleaned["default_currency"] not in CURRENCIES:
            return "invalid_currency", []
        if domain == "Depolar" and cleaned["warehouse_type"] not in WAREHOUSE_TYPES:
            return "invalid_warehouse_type", []
        if domain == "Müşteriler" and cleaned["status"] not in (
            "Potansiyel", "Aktif", "Pasif", "Müşteri",
        ):
            return "invalid_customer_status", []
        records.append(cleaned)
    return "ok", records


def parse_master_csv(payload, domain):
    """Validate CSV without a DB connection; return status and preview rows."""
    if domain not in DOMAINS:
        return "invalid_domain", []
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_UPLOAD_BYTES:
        return "invalid_file", []
    try:
        text = payload.decode("utf-8-sig", errors="strict")
        if "\x00" in text:
            return "invalid_file", []
        source = StringIO(text, newline="")
        reader = csv.DictReader(source, strict=True)
        columns = list(reader.fieldnames or [])
        # Unknown/duplicate column names are prohibited, not silently dropped.
        if (not columns or len(columns) != len(set(columns))
                or not set(columns).issubset(DOMAINS[domain]["columns"])
                or not set(DOMAINS[domain]["required"]).issubset(columns)):
            return "invalid_columns", []
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                return "invalid_csv", []
            if not any(str(value).strip() for value in row.values()):
                continue
            rows.append(row)
            if len(rows) > MAX_ROWS:
                return "invalid_row_count", []
        return _clean_rows(domain, rows)
    except (UnicodeDecodeError, csv.Error, ValueError, TypeError):
        return "invalid_csv", []


def import_new_masters(url, *, role, actor, domain, rows,
                       confirmation="", backup_confirmed=False):
    """All-or-nothing audited insert of *new* master records.

    Return (status, inserted_count): forbidden | not_confirmed | invalid_url |
    schema_mismatch | duplicate_existing | failed | ok | CSV validation error.
    Validated transactions run in PostgreSQL; no changes to unrelated rows.
    """
    if role != "ADMIN" or not isinstance(actor, str) or not actor.strip() or len(actor) > 80:
        return "forbidden", 0
    if confirmation != APPROVAL or backup_confirmed is not True:
        return "not_confirmed", 0
    valid, clean_rows = _clean_rows(domain, rows)
    if valid != "ok":
        return valid, 0
    if not validate_test_url(url):
        return "invalid_url", 0
    try:
        status, _ = validate_staging_structure(url, schema="ct_app")
        if status != "ok":
            return "schema_mismatch", 0
        import psycopg
        from psycopg import sql

        config = DOMAINS[domain]
        table = config["table"]
        fields = tuple(config["columns"])
        # Predictable lock acquisition prevents conflicting batch deadlocks.
        ordered = sorted(clean_rows, key=lambda row: row["name"].casefold())
        with psycopg.connect(
            str(url).strip(), connect_timeout=8, sslmode=sslmode_for(url),
            autocommit=True,
        ) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '25s'")
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    cur.execute('SET LOCAL search_path TO "ct_app", pg_catalog')
                    for row in ordered:
                        name = row["name"]
                        cur.execute(
                            "SELECT pg_advisory_xact_lock(7300, hashtext(lower(%s)))",
                            (table + ":" + name,),
                        )
                        # All three domains must be insert-only and idempotent
                        # even when the schema lacks a unique NAME index.
                        cur.execute(
                            sql.SQL("SELECT id FROM {} WHERE lower(name)=lower(%s) LIMIT 1").format(
                                sql.Identifier("ct_app", table),
                            ), (name,),
                        )
                        if cur.fetchone() is not None:
                            raise _DuplicateExisting()
                        cur.execute(
                            sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING id").format(
                                sql.Identifier("ct_app", table),
                                sql.SQL(",").join(map(sql.Identifier, fields)),
                                sql.SQL(",").join(sql.Placeholder() for _ in fields),
                            ),
                            tuple(row[field] for field in fields),
                        )
                        if cur.fetchone() is None:
                            raise ValueError("No returned ID")
                        cur.execute(
                            'INSERT INTO "ct_app"."audit_log" '
                            '(username,role,action,table_name) VALUES (%s,%s,%s,%s)',
                            (actor.strip(), role, "bulk_import_new", table),
                        )
        return "ok", len(clean_rows)
    except _DuplicateExisting:
        # Transaction context rolls back every preceding row in the batch.
        return "duplicate_existing", 0
    except Exception:
        return "failed", 0


class _DuplicateExisting(Exception):
    """Abort the complete batch if a matching name already exists."""
