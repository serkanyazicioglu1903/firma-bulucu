# AS Control Tower — Real Quote / Profitability Preview (No Demo Data)

This PR adds a fourth **🧮 Gerçek Teklif / Kârlılık** tab to the authenticated
application. It is a usable manual quote planning screen that **does not
require any master records**, sample customers, fictional products, SQLite
data or Supabase writes.

## How to use

1. Log in with an existing ADMIN, SALES, PURCHASING or FINANCE account.
2. Open **Gerçek Teklif / Kârlılık** and select the quote's company label.
3. Enter real quantity (kg), buy price/currency and optional sale price.
   If a currency differs from the chosen calculation currency, you MUST enter
   the independently checked manual FX rate. No fabricated live FX is used.
4. Enter actual total freight, customs/duty, other import and handling costs
   in the calculation currency. These are explicit totals, not invented
   country-specific customs classifications or percentages.
5. Enter supplier prepayment %, days from prepayment to goods arrival,
   remaining supplier payment days after arrival, stock waiting days,
   customer collection days, annual financing %, commission and desired
   net contribution margin.
6. Click **Hesapla** to see landed unit cost, finance cost, final unit cost,
   weighted goods finance days, break-even price, target sales price, and
   (if a sales price was provided) contribution/profit and net margin.
7. Optionally download a numeric CSV summary locally. Customer and product
   free text are intentionally excluded from that CSV.

**Every numeric input starts from zero, not a demo quote.** Company labels are
used for a human-readable quote only, not to grant cross-company access. No
database record is read/created/updated. Values exist only within the
logged-in user's current Streamlit session. Changing accounts or switching
company clears previous quote inputs; switching currency resets entered FX.

## Working capital assumption (preliminary)

Simple annual ACT/365 interest (no compounding):
- Prepaid merchandise: capital committed from prepayment until customer pays.
- Deferred balance: committed only from actual supplier payment to collection;
  if supplier due date falls after collection, financed merchandise days = 0.
- Freight/duties/handling: assumed paid at goods arrival and financed until
  collection. Real outflow dates should be confirmed independently.
- Sales commission is deducted from sales, *not* added to purchase costs.
  Target price solves net contribution margin after commission and finance.

VAT is **excluded**; nondeductible taxes/duties must be included in explicit
import costs, which should be verified with customs/accounting staff.

## Scope and live safety

This is a functional *uncommitted quote preview*, not a financial ledger,
quote number, sent quotation, invoice, customer CRM record, automatic
purchasing workflow, cash forecast or production four-company isolation.
An entered company code does not assert verified legal-entity registration.
The existing signed company REVIEW-only application-wide gate still
suppresses all unscoped tabs, including this calculation screen.

No user identity grants, Supabase schema, company permissions, demo
records, production database rows, environment settings or deployment
configuration are changed. Further real operational writes require an
approved tenant-isolated backend and independent go-live authorization.
