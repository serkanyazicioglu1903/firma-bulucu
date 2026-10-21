from unittest.mock import Mock

from scripts.four_company_live_preflight import assess_catalog_rows, inspect_on_cursor, SQL
from scripts.postgres_company_full_coverage import _catalog_tables


def inventory(*, secure=False):
    return [(name, 0, secure, secure, secure, 1 if secure else 0)
            for name in sorted(_catalog_tables())]


def test_unmigrated_production_is_blocked():
    report = assess_catalog_rows(inventory())
    assert report["status"] == "blocked"
    assert report["tables"] == 26
    assert report["private_tables"] == 23
    assert len(report["missing_owner_column"]) == 23
    assert len(report["missing_forced_rls_or_policy"]) == 23
    assert report["migration_authorized"] is False


def test_fully_protected_metadata_still_requires_review():
    report = assess_catalog_rows(inventory(secure=True))
    assert report["status"] == "review_required"
    assert report["migration_authorized"] is False


def test_missing_or_duplicate_table_fails_closed():
    assert assess_catalog_rows(inventory()[:-1])["status"] == "blocked"
    rows = inventory()
    rows[-1] = rows[0]
    assert assess_catalog_rows(rows)["status"] == "blocked"


def test_read_only_catalog_query_never_touches_business_rows():
    assert "pg_class" in SQL and "pg_policy" in SQL
    assert all(word not in SQL.upper() for word in ("ALTER ", "UPDATE ", "DELETE ", "INSERT ", "DROP ", "GRANT "))
    cur = Mock()
    cur.fetchall.return_value = inventory()
    result = inspect_on_cursor(cur)
    assert result["status"] == "blocked"
    cur.execute.assert_called_once_with(SQL)


def test_exact_count_baseline_only_reads_whitelisted_tables():
    cur = Mock()
    cur.fetchone.return_value = (0,)
    report = count_existing_rows_on_cursor(cur)
    assert len(report["counts"]) == 26
    assert report["total_rows"] == 0
    assert report["backup_verified"] is False
    assert report["owner_assignments_verified"] is False
    assert cur.execute.call_count == 26
    assert all(call.args[0].startswith('SELECT count(*) FROM "ct_app"."')
               for call in cur.execute.call_args_list)


def test_invalid_count_fails_closed():
    cur = Mock()
    cur.fetchone.return_value = (-1,)
    import pytest
    with pytest.raises(ValueError, match="row_count_unavailable"):
        count_existing_rows_on_cursor(cur)
