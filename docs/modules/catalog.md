# Catalog and attendee orders module

Status: edition catalog, attendee order, governed stock, and hosted/demo payment vertical implemented
Last updated: 2026-08-09

## Purpose and boundary

`maru.catalog` owns edition merchandise, charity-support merchandise and
donations, limited supporter products, variants, attendee orders, stock
evidence, and catalog payment intent/reconciliation. It implements the current
slice of FUR-005, FUR-006, LOG-007, FIN-007, FIN-008, REG-003, REG-004,
REG-005, and REG-026.

Admission remains owned by `maru.registration`. A catalog product or order
cannot reference an admission product, registration, or admission entitlement,
and paying a catalog order cannot create or replace a ticket. Registration's
one-admission-entitlement rule therefore remains independent.

## Records and lifecycle

- `EditionCatalog` is one edition-owned, currency-pinned aggregate with draft,
  active, and closed states.
- `CatalogProduct` distinguishes convention merchandise, donations, and
  limited supporter products. It records the beneficiary, sale window,
  preorder rule, fulfilment mode, and per-order limit. A charity beneficiary
  must be one confirmed selection from the same organization and edition.
- `CatalogVariant` owns an immutable SKU, current configured price, optional
  finite initial stock, and optional hard stock ceiling.
- `CatalogOrder` and immutable `CatalogOrderLine` rows snapshot names, SKU,
  price, beneficiary, charity selection, and fulfilment at purchase time.
- `CatalogStockAdjustment`, `CatalogPaymentEvent`, order timeline entries, and
  command receipts are append-only evidence.

An active catalog definition is not edited in place. Stock changes append a
reasoned adjustment, lock the aggregate, compare the expected version, refuse
the configured ceiling, and refuse to reduce stock below committed order
quantity. Donation variants are stockless. Limited supporter products require
finite stock and cannot oversell through preorder.

## Commands, payments, and evidence

Configuration, activation, stock, order, payment-intent, demo-completion, and
provider-reconciliation commands are scope-bound, idempotent, optimistic-
versioned transactions. Successful commands append minimized audit, domain
event, outbox, receipt, and timeline evidence in the same transaction.
Attendee order lines are priced and reserved again under current locks; the
browser's displayed value is never authoritative.

The hosted adapter records a local intent and redirect target; a browser return
is not payment proof. Only the reconciliation command changes an order to paid.
The deterministic demo provider crosses the same command boundary and is for
synthetic/local rehearsal only. Catalog operational evidence is not a
statutory general ledger.

## Authorization and interfaces

Edition-scoped `catalog.manage`, `catalog.manage_stock`,
`catalog.manage_payments`, and `catalog.view_activity` capabilities govern
staff actions. `catalog.order_self` and `catalog.view_self` are code-owned
self-service capabilities and cannot be persisted as broad grants. Platform
administrator status alone does not make an account a convention subject.

My Maru exposes a bounded **Shop & orders** index, active catalog pages, order
history, checkout, and hosted/demo payment controls. Catalog discovery streams
only organization, edition, and catalog IDs through the exact self-service
authorization decision before fetching any edition or series labels. A denied
foreign prefix therefore cannot consume the visible result limit or disclose
its labels. Direct catalog, order-placement, order-history, checkout,
hosted-payment, and demo-payment routes repeat the exact profile and
self-capability decision before loading a catalog or owned order. A retained
catalog or order cannot revive Catalog or disclose its edition name or reference
after the exact profile omits that surface. Every authenticated catalog GET
surface is private and emits
`Cache-Control: no-store` semantics, including checkout, history, and the staff
workspace.

The selected-edition menu shows **Catalog commerce** only after fresh
`catalog.view_activity` authorization. The shared-shell staff page can create
the draft catalog, add product policies and price/stock variants, activate the
definition, append finite-stock adjustments, and inspect a bounded,
purpose-scoped activity projection. Browser inputs are closed, authorize before
parsing, use canonical idempotency keys and current aggregate versions, and
resolve charity choices only from confirmed selections in the exact edition.
Sale-window input is one exact, real, unambiguous minute in the edition time
zone. Payment reconciliation remains on the strict API documented in
[`catalog-api.md`](catalog-api.md).

## Migrations, rollback, and remaining scope

`catalog.0001` creates the bounded schema, `catalog.0002` pins the command
operation catalog, and `catalog.0003` installs immutable-evidence and
active-definition guards. `authorization.0015` adds the four persistable
capabilities and downgrade fences after venue authorization migration `0014`.
Rollback must first remove or deliberately migrate any catalog authority and
business evidence; operators must not bypass the guards or delete history.

Cancellation, refunds, exchanges, scheduled unpaid-order expiry, fulfilment
handover, shipping, accounting export, real provider credentials/webhook
verification, and stock locations/counts remain open. Do not production-enable
catalog sales until those applicable operating controls and provider
certification are approved.
