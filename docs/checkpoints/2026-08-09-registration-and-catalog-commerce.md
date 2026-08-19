# Registration and catalog commerce verticals

Date: 2026-08-09
Status: implemented and focused-verified; production integrations remain gated
Requirements: REG-003, REG-004, REG-005, REG-008, REG-010, FUR-005, FUR-006, LOG-007, FIN-007, FIN-008

## Outcome

Registration now supports governed default-to-higher admission replacement at
the currently configured exact price difference, with target-capacity hold,
one surviving admission entitlement, idempotent/versioned evidence, and safe
expiry rollback. Overall and product capacity changes are reasoned append-only
adjustments under immutable hard ceilings. Waitlist staff can offer only the
strict FIFO next eligible batch of configured size; there is no arbitrary
selection or skipping. My Maru, staff HTML, strict APIs, audit, domain events,
outbox, and the bounded activity projection expose those commands.

The separate `maru.catalog` bounded context adds convention merchandise,
charity-support products and donations, limited supporter variants, sale
windows, prices, finite stock/preorder rules, attendee orders, checkout and
history, governed stock changes, hosted/demo payment evidence, charity
beneficiary linkage, and purpose-scoped activity. Catalog lines cannot create
or replace admission tickets.

## Verification

- Registration commerce service matrix: passed.
- Registration commerce HTML controls: 2 passed; Page 10 definition matrix
  passed after the closed-helper compatibility correction.
- Catalog focused vertical matrix: 4 passed across service, charity/demo
  payment, stock/tenant/database guards, attendee/staff HTML, and API closure.
- Added My Maru catalog index/navigation regression: 3 passed in 3.82 seconds.
- Catalog and navigation Ruff: passed.
- Focused mypy: 10 source files passed with no issues.
- Django system check and root URL import/route/template resolution: passed,
  with only the documented invitation-encryption configuration warning.
- Migration drift: no model changes detected before final handoff.

## Recovery and remaining scope

Registration `0038`, catalog `0001`-`0003`, and authorization `0015` preserve
append-only evidence and refuse unsafe mutation/downgrade. Production still
requires hosted-provider certification, unpaid catalog-order expiry and
cancellation, refunds, fulfilment custody/shipping, accounting export,
retention decisions, monitoring, accessibility/browser evidence, and a
representative restore/reconciliation rehearsal.
