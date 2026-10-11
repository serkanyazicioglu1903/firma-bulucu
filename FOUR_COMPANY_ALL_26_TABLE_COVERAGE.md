# Four-company database ownership inventory

This change reviews metadata for all 26 existing application tables.
It does not read customer or financial records or alter the production
database.

Eight finance and operational tables require reviewed, non-null
legal-entity ownership. The other 18 tables also require review:
CRM, quotations, product catalogue, warehouses, dependent records
and administrative data. Shared status is not presumed.

The result remains review_required even if the metadata looks correct.
Actual tenant authorization needs independently authenticated principals,
separate database permissions, a verified backup and restore rehearsal,
and reviewed legal-entity assignments before activation.

The scripts and tests are preparation only. No migration or live access
rules are automatically applied.
