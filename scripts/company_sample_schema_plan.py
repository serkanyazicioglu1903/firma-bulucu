"""Offline DDL proposal for tenant-isolated sample records.

Not run automatically, no privileges granted, no seed data, no live connection.
An administrator must verify actual ct_app legal entity IDs, app role grants,
and PostgreSQL RLS behaviour on a disposable test DB before any deployment.
"""

SAMPLE_TABLE_SQL = """
CREATE TABLE ct_app.company_samples (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    legal_entity_id BIGINT NOT NULL REFERENCES ct_app.legal_entities(id),
    customer_name TEXT NOT NULL CHECK (length(btrim(customer_name)) BETWEEN 1 AND 200),
    contact_name TEXT NOT NULL DEFAULT '' CHECK (length(contact_name) <= 200),
    product_name TEXT NOT NULL CHECK (length(btrim(product_name)) BETWEEN 1 AND 200),
    supplier_name TEXT NOT NULL DEFAULT '' CHECK (length(supplier_name) <= 200),
    lot_number TEXT NOT NULL DEFAULT '' CHECK (length(lot_number) <= 100),
    quantity NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    unit TEXT NOT NULL DEFAULT 'kg' CHECK (unit IN ('kg','g','adet','L','mL')),
    sent_date DATE,
    courier TEXT NOT NULL DEFAULT '' CHECK (length(courier) <= 200),
    tracking_number TEXT NOT NULL DEFAULT '' CHECK (length(tracking_number) <= 200),
    trial_date DATE,
    application TEXT NOT NULL DEFAULT '' CHECK (length(application) <= 500),
    status TEXT NOT NULL DEFAULT 'Talep alındı'
        CHECK (status IN ('Talep alındı','Hazırlanıyor','Gönderildi',
                         'Teslim edildi','Denemede','Onaylandı',
                         'Başarısız','Siparişe dönüştü')),
    annual_consumption TEXT NOT NULL DEFAULT '' CHECK (length(annual_consumption) <= 200),
    notes TEXT NOT NULL DEFAULT '' CHECK (length(notes) <= 2000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (id, legal_entity_id)
);
CREATE INDEX company_samples_entity_trial_idx
    ON ct_app.company_samples (legal_entity_id, trial_date, id DESC);
ALTER TABLE ct_app.company_samples ENABLE ROW LEVEL SECURITY;
ALTER TABLE ct_app.company_samples FORCE ROW LEVEL SECURITY;
REVOKE ALL ON ct_app.company_samples FROM PUBLIC, anon, authenticated;
REVOKE ALL ON SEQUENCE ct_app.company_samples_id_seq FROM PUBLIC, anon, authenticated;
"""

# These are intentionally separated from the DDL. The runtime must not grant
# read/write access until company-scoped policies and integration tests pass.
SAMPLE_SECURITY_REQUIREMENTS = (
    "Resolve a server-verified principal using company_login_bindings",
    "Authorize the selected entity using company_read_grants",
    "Require company_write_grants for INSERT and UPDATE",
    "Use a dedicated least-privilege PostgreSQL role, never service_role",
    "Apply RLS USING and WITH CHECK for every company-scoped mutation",
    "Check isolation with two real roles and four legal entities",
    "Log every change to company_operation_audit",
    "Use idempotent request identifiers for retry safety",
)
