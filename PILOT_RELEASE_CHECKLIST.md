# AS Control Tower — pilot release checklist

This is an **integration candidate**, not a production deployment.

## Implemented and exercised in CI

- Company acquisition search and manufacturer/supplier discovery are exposed in the Streamlit app.
- CRM, product/customer matching, quote and margin, purchasing, shipments, inventory, quality, receivables, payables, cash and management sections are present.
- Demo records are not inserted automatically. Fictional fixtures require `AS_CONTROL_TOWER_DEMO_SEED=1`.
- Empty product/warehouse workspaces show guidance rather than crashing on the affected forms. An isolated Streamlit smoke test also checks startup without fictional master data.
- Isolated SQLite tests exercise purchase order → shipment → inventory receipt → quality HOLD/release → supplier payment.
- Inventory receipts reject cancellation, excess quantity and repeated receipt.
- Payment/collection operations reject a repeated nonblank reference **within the same invoice**, and check amount and bank currency. Blank references have no replay protection.
- Separate offline fake-PostgreSQL staging tests cover procurement/stock/quality/payment guard and rollback logic.
- System Health offers a single explicitly confirmed PostgreSQL acceptance action: schema audit, rollback-only CRUD, and rollback-only fictional CRM/quote/purchase/stock/HOLD/finance workflow. The coordinator fails closed and does not reveal credentials. The action must be run in the target Streamlit environment; successful CI mocks **do not** prove connectivity to the user's Supabase instance.

## Release blockers (do not skip)

1. Validate real PostgreSQL schema and integration against an **isolated, non-production** database. The offline adapter test is not a live PostgreSQL test.
2. Confirm persistent storage/backups. The default Control Tower uses a local SQLite file. To use a pre-mounted persistent disk, set `AS_CONTROL_TOWER_DB_PATH=/mount/persistent/as_control_tower.db` before startup; the target directory must already exist and be writable. A Streamlit cloud instance's ephemeral local filesystem is not an adequate durable production database. Changing the path does not migrate old data.
3. Perform manual phone and MacBook browser testing, including narrow viewport and authentication/role restrictions. Streamlit AppTest is not a physical device test.
4. Check real import duties, exchange rates, credit terms and margin calculations against approved sample invoices before financial decisions.
5. Validate product sourcing results manually against official manufacturer sites and commercial documents.
6. Verify authentication, secrets, backup/restore and concurrent write behavior with the target hosting configuration.
7. Obtain explicit owner approval before merging PR #27, deploying or writing any production data.

## Safe review procedure

- Review draft PR #27, including changes brought in from PR #25 and PR #26.
- Run GitHub Actions on the PR head and confirm **both** checks pass.
- On an isolated machine or environment with dependencies installed, run:
  `python -m unittest discover -s tests -p 'test_control_tower_sqlite_integration.py' -v`
  `python -m unittest discover -s tests -p 'test_staging_ops_adapter.py' -v`
- Launch Streamlit only against an empty, disposable workspace during acceptance testing.
- Never point an unreviewed pilot at the production database.

## Known scope limit

The application UI's operational persistence remains SQLite-based. The staging PostgreSQL adapter is an isolated pilot, **not** a drop-in PostgreSQL backend for the entire app. The candidate should not be described as fully production-ready until the above release blockers are cleared.
