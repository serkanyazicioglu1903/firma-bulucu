# Four-company server-side scoped read prototype — NOT live

This PR prepares a **separate, unused** read-only data access adapter,
`scripts/postgres_scoped_company_read.py`. It is not wired into the current
Streamlit dashboard, finance screens, SQL compatibility façade or export paths.
**Do not use the existing unscoped screens to mix four companies' ledgers.**

## Explicit permission model

A future **approved migration** would create
`ct_app.company_read_grants` with rows keyed by:

- `principal_id`: independently authenticated, **server-derived** account ID;
  never accept a phone/URL/form-supplied username as verified identity.
- `legal_entity_id`: foreign key to a verified `legal_entities` master.
- `can_read`: defaults to **FALSE**. No ADMIN or holding shortcut.

The offline migration plan **does not insert any grants or users**. It does
not change live PostgreSQL. A strict fixed-list reader checks:

1. Exactly **eight** critical operation/finance tables require
   `legal_entity_id NOT NULL` before it can read any company record.
2. A valid and active legal entity exists for the requested registered code.
3. An **explicit, non-revoked DB grant** exists for that authenticated principal
   and exact entity.
4. Its SELECT repeats both the matching entity owner and the DB grant,
   uses bound SQL parameters, returns only a reviewed subset of columns,
   and limits results to 100.

Missing owners, grants or invalid principal => no records, without exception
details, secrets or financial figures in logs.

**The principal argument is a *trusted backend API input only*.** It will
not be safe for end users until actual account identities, company memberships,
database grants, role permissions and session enforcement have been designed
and independently reviewed. A DB service account able to read all records
still requires correct server authorization on every path. RLS is not yet
implemented or certified.

## Disposable PostgreSQL verification

Only GitHub CI on local ephemeral PostgreSQL:

- Adds fictional companies A/B/C/D and temporary owner columns within an
  explicitly rolled-back transaction.
- Creates a fictional grant table and gives a dummy principal access to only
  A and D. Read functions cannot show B/C orders, cash or finance rows.
- Confirms exact A and D records are visible individually, zero cross-company
  records appear, an "admin" string confers no access, and revocation
  immediately blocks a further read.
- Confirms **both all inserts AND DDL are rolled back** and no table remains.

## Still required before real go-live

Verified registry names and tax data; audited tenant identity mapping;
least-privilege server roles; row-level or equivalent isolation across **all**
legacy SQL, CRM, storage, user search, downloads, exports, finance, dashboard,
audit and background tasks; tenancy-aware transactional writes and composite
FKs; company-specific bank reconciliation and consolidation eliminations;
AES-encrypted independent backup with isolated restore; legal/accounting
sign-off; migration and rollback approvals.

No production migration, credential changes, backup activation, real company
record import, or application deployment are authorized by this PR.
