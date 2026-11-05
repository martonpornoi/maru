# Catalog route and read query-cost baseline

## Scope

This INT-001 review for [#36](https://github.com/martonpornoi/maru/issues/36)
used protected main at `e20e845b5c65654f835be6309c16a9e8d98053b8`.
Catalog owns the mounted adapters and queries. The capability and edition
boundaries in ADR 0003, edition commerce in ADR 0050 and the private API
reference in ADR 0056 apply.

## Mounted route parity

The Django resolver under `maru.urls` dispatches 11 explicit Catalog operations
across nine versioned paths. All path and method pairs resolve to the Catalog
adapter and match fresh OpenAPI generation, the checked-in schema, generated
Staff Console operation mappings and the module's documented route list.
OpenAPI operation IDs are unique and every operation declares authentication.
The 22 focused schema tests passed with two existing DRF warnings.

Route presence and response documentation are separate. Two edition operations
on protected main declare handled problem responses. The product and variant
candidate in [PR #241](https://github.com/martonpornoi/maru/pull/241) preserves
all 11 route and operation IDs and brings the total with documented handled
problems to four. Seven operations still need handled-response conformance work
after that increment.

## Read cost

One migrated, disposable PostgreSQL database held fictional catalogs, orders,
demo payment intents and activity. The in-process HTTP client supplied the
synthetic attendee or administrator principal. Each of the 12 scenarios ran
three times with identical SQL statement counts and response bodies for that
scenario. Counts include authorization, response construction and the activity
audit insert. Fixture setup and connection initialization were outside the
measurement.

| Read | Returned shape | SQL statements |
| --- | --- | ---: |
| Edition catalog | Empty draft projection | 4 |
| Edition catalog | One product with 1 or 12 stockless variants | 5 |
| Edition catalog | One product with 1 finite-stock variant | 7 |
| Edition catalog | 12 finite-stock variants across 1 or 4 products | 29 |
| Own orders | 0 orders | 3 |
| Own orders | 1 or 12 orders, each with two lines and a demo payment intent | 6 |
| Catalog activity | 1, 31 or 50 entries, with 53 available in the last case | 8 |

The finite-stock detail reads the latest stock adjustment and aggregates
committed order-line quantity for each finite variant. The 12-variant case
made 12 reads against each of those relations. The own-orders test also
confirmed that an order from a second account in the same edition was excluded.
Activity retained one audit insert per request and returned 50 of 53 eligible
events at its existing limit. The owned container was removed and all ten
preserved fixture states matched.

These figures describe SQL statement counts at the tested cardinalities.
Production latency, payload size limits, restricted-role database performance
and concurrent stock consistency require separate evidence. The
[Catalog conformance plan](../development/catalog-edition-api-conformance-plan.md)
tracks the decisions needed before specifying a bounded read or a stock snapshot.
