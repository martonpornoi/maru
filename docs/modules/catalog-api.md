# Catalog API contract

Status: mounted versioned adapter contract
Last updated: 2026-11-03

The [dated edition GET/POST review](../development/catalog-edition-api-contract-review.md)
records exact observed behavior, authentication modes, normalization, retry identity
and remaining conformance decisions for that pair. This overview is not complete
native HTTP acceptance. The [conformance plan](../development/catalog-edition-api-conformance-plan.md)
records the protected-delivered adapter baseline, the next bounded creation-retry
evidence increment and remaining compatibility decisions. The new cases exercise
original receipt retention, scoped keys, concurrent creation and late evidence
rollback. They do not introduce a supported external-client retry policy or a
public dependency-failure guarantee; see the
[checkpoint](../checkpoints/2026-10-19-ci-delivery-and-catalog-retry-conformance.md)
for verification actually completed.

All routes are organization- and edition-explicit. They require an active Maru
account and the operation's exact capability/relationship; the edition pair also
inherits Basic authentication as detailed in the review. They reject query
parameters and unknown JSON fields, and resolve authorization inside the shared
command/query service. Every mutation requires
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

## Edition catalog responses

The generated OpenAPI reference documents these responses for the edition
Catalog route. The two operations have separate authority requirements.

| Operation | Successful responses | Handled problems |
| --- | --- | --- |
| Read the edition catalog | `200` with the version, currency and products available to the caller. A catalog can have no available products. | `400` for an unsupported query, `403` for denied access, and `404` for a catalog unavailable after scope authorization. |
| Create the edition catalog | `201` for a new draft and `200` for replay of the original creation receipt. | `400` for invalid input or conflicting creation intent, and `403` for denied access. |

These handled problems use `application/problem+json`. The documented success
and problem responses include `Cache-Control` with `private` and `no-store`
directives and an `X-Request-ID` UUID for correlation. A matching creation
retry uses the same key, actor, edition and normalized currency. It returns the
original target and creation version and preserves the original reason even
if a later valid retry supplies different wording.

The generated examples use fictional data. The native HTTP tests validate the
documented statuses, media types, headers and body schemas against actual
responses. The [conformance plan](../development/catalog-edition-api-conformance-plan.md)
tracks separate decisions about read completeness, read-audit policy and
dependency failures.

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
