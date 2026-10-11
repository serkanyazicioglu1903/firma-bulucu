# PR #61 — Four-company stock, quality and settlement rehearsal

**Scope: CI-only, disabled in production. Nothing is wired to Streamlit or live Supabase.**

This PR extends the existing CI-only transactional writer from #60 with five
additional company-owned operations:

- `receive_shipment`: lock the purchase order *before* its shipment; verify
  the shipment, warehouse assignment and PO all belong to the same
  `legal_entity_id`; reject second receipt and over-receipts; create an
  owner-stamped stock lot and update status atomically.
- `hold_inventory_lot`: lock an owner-stamped stock lot and open an equally
  owned QA case, rejecting a different company's lot and excess held stock.
- `release_inventory_lot`: match the open QA case and stock lot to the
  exact same company before unblocking stock.
- `pay_supplier`: lock only the selected company's payable and bank
  account; reject active QA holds on that company's PO, currency mismatch,
  insufficient bank funds, overpayments and duplicate payment references.
  Update the payable, bank and company-owned finance transaction together.
- `collect_customer_payment`: lock only the selected company's receivable
  and bank; reject company/currency mismatches, excess collections and
  duplicate bank references. Update all three records together.

Every authorized call goes through **verified company ownership, an
independently authenticated principal, a suitable role, explicit read/write
DB grants, the same company entity and a same-transaction audit row**. Merely
selecting a different company or being labeled ADMIN does not confer access.
No bank transfer or settlement is initiated outside a disposable test DB.

New tests include fictional four-company A/B/C/D records, payments blocked by
QA holds, releases, two independent banks, wrong-owner denials, repeat
references, currency-specific records, and atomic rollback including temporary
schema additions. Existing test database is loopback-only and destroyed after
GitHub Actions.

## Remaining blockers to any live rollout

- Actual company registry/legal-name verification and ownership backfill,
  least-privilege account mapping, RLS across all legacy read/write routes
- Verified encrypted off-site backup and **isolated RESTORE** rehearsal
- Company-owned CRM, warehouse and inventory master model, stock issue/sales,
  inventory reservations, safe supplier payment confirmation integration
- Document/reconciliation workflows and full financial reporting sign-off,
  FX rules, holding eliminations and role-based mobile acceptance testing
- Explicitly approved production migrations, rollback and go-live window

**The new tests do not execute any SQL against the live database**, and
passing tests do not imply four-company production readiness.
