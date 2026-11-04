# Catalog stock projection in the attendee read

The [query-cost baseline](2026-11-04-catalog-route-and-read-cost-baseline.md)
found that edition Catalog detail used two additional SQL statements per
finite-stock variant. Under REG-026 and INT-001, the Catalog's authorized
product query now reads the latest adjustment and committed order quantities
inside the existing variant prefetch. The API and the attendee web page use
that projection. The order and adjustment commands continue to use the
existing live stock calculation under their locks.

The calculation uses the latest adjustment or initial stock, subtracts
payment-pending and paid order quantities and floors the result at zero.
Stockless variants return `null` in the API. Tenant and edition scoping,
capability, lifecycle, sale windows, ordering and response fields follow the
existing Catalog contract. This requires no migration or retained-data repair.

## Focused verification

- The 41 Catalog PostgreSQL cases passed on the disposable fixture. The new
  HTTP test observed five SQL statements for one finite variant and for a
  twelve-variant catalog with finite and stockless options. It checked exact
  stock values after successive adjustments and paid and pending orders.
- The 119 focused unit cases passed. Regenerated OpenAPI matched the checked-in
  bytes, with 23 existing enum naming warnings and zero errors. Ruff, mypy and
  the focused docstring checks passed.
- The owned test database was removed. All ten preserved fixture states matched.

The two stock inputs share the variant statement's database snapshot. The
product, variant and catalog metadata queries still run separately. The
statement-count test covers its specified fixtures. Production latency,
cardinality limits, restricted-role performance and concurrent changes across
the full response remain separate evidence under
[#36](https://github.com/martonpornoi/maru/issues/36).
