# Catalog API contract

Status: mounted versioned adapter contract
Last updated: 2026-08-09

All routes are organization- and edition-explicit. They require an active Maru
person session, reject query parameters and unknown JSON fields, and resolve
authorization inside the shared command/query service. Every mutation requires
one canonical UUID `Idempotency-Key`; versioned mutations also require the
current positive aggregate version. Whitespace-padded or otherwise non-canonical
keys are rejected rather than normalized. New resource commands return `201`;
an exact receipt replay returns `200`. IDs from another tenant or edition are
resolved through a non-disclosing unavailable boundary.

```text
GET|POST /api/v1/catalog/organizations/{organization_id}/editions/{edition_id}/
POST     /api/v1/catalog/organizations/{organization_id}/editions/{edition_id}/products/
POST     /api/v1/catalog/organizations/{organization_id}/editions/{edition_id}/products/{product_id}/variants/
POST     /api/v1/catalog/organizations/{organization_id}/editions/{edition_id}/activate/
POST     /api/v1/catalog/organizations/{organization_id}/editions/{edition_id}/variants/{variant_id}/stock-adjustments/
GET|POST /api/v1/catalog/organizations/{organization_id}/editions/{edition_id}/orders/
POST     /api/v1/catalog/organizations/{organization_id}/editions/{edition_id}/orders/{order_id}/payments/
POST     /api/v1/catalog/organizations/{organization_id}/editions/{edition_id}/payment-intents/{intent_id}/reconcile/
GET      /api/v1/catalog/organizations/{organization_id}/editions/{edition_id}/activity/
```

Product input distinguishes `merchandise`, `donation`, and `supporter`, plus
`convention` or `charity` beneficiary. Charity input names an exact confirmed
`charity_selection_id`. Variant price is in minor currency units. Finite stock
requires concrete `initial_stock` and `stock_ceiling` values together; stockless
variants omit both fields. Supplying only one field or JSON null is invalid.

Order creation accepts one to fifty strict `{variant_id, quantity}` objects and returns
the target order plus resulting catalog version. The service snapshots the
current product, variant, beneficiary, price, and fulfilment values under lock.
Order reads return only the caller's orders. Payment creation accepts `hosted`
or `demo`; provider reconciliation accepts a unique provider event ID and a
`succeeded` or `failed` result with a staff reason.

Activity is a bounded, audited projection of allowlisted catalog actions. It
returns action, minimized actor label, occurrence time, and target count; it
does not return command reasons, payment-provider payloads, attendee order
contents, or unrestricted audit records.

## Same-shell browser adapters

The app also owns these authenticated browser boundaries:

```text
GET  /my/catalog/
GET  /my/catalog/{edition_id}/
GET  /my/catalog/{edition_id}/orders/
POST /my/catalog/{edition_id}/orders/new/
GET  /my/catalog/{edition_id}/orders/{order_id}/
POST /my/catalog/{edition_id}/orders/{order_id}/hosted-payment/
POST /my/catalog/{edition_id}/orders/{order_id}/demo-payment/

GET  /admin/platform/organizations/{organization_slug}/series/{series_slug}/editions/{edition_slug}/catalog/
POST /admin/platform/organizations/{organization_slug}/series/{series_slug}/editions/{edition_slug}/catalog/create/
POST /admin/platform/organizations/{organization_slug}/series/{series_slug}/editions/{edition_slug}/catalog/products/new/
POST /admin/platform/organizations/{organization_slug}/series/{series_slug}/editions/{edition_slug}/catalog/products/{product_id}/variants/new/
POST /admin/platform/organizations/{organization_slug}/series/{series_slug}/editions/{edition_slug}/catalog/activate/
POST /admin/platform/organizations/{organization_slug}/series/{series_slug}/editions/{edition_slug}/catalog/variants/{variant_id}/stock-adjustments/
```

Browser mutations call the same services as the API and use post/redirect/get.
They reject unknown fields, repeated scalar fields, non-canonical UUIDs and
integers, foreign objects, stale versions, changed-digest retry-key reuse, and
invalid product or stock policy shapes. Staff capability checks happen before
request-body parsing. Authenticated GET responses are private and `no-store`.
HTML never renders restricted charity identity, selection or command reasons,
payment-provider payloads, or foreign catalog labels.
