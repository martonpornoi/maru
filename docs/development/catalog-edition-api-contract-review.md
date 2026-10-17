# Catalog edition API contract review

**Audience:** Catalog maintainers and contributors planning API conformance work\
**Outcome:** Review exactly two operation contracts and identify the evidence
needed before changing them\
**Status:** Source review completed; behavioral decisions and native HTTP
conformance remain open

This review covers `CatalogDetailApi` at
`/api/v1/catalog/organizations/{organization_id}/editions/{edition_id}/`.
It is pinned to protected main
`c95bb69fe7b7cc308e030563fbd4856ea5201fd6`, reviewed on 2026-10-17.
It follows the [240-operation inventory](api-contract-inventory.md) and advances
[issue #36](https://github.com/martonpornoi/maru/issues/36) without closing it.
It changes no endpoint, schema, authentication, permission, test or gate.

The human outcome is predictable catalog reading and draft creation: a client
developer should understand who may call each operation, what a retry means and
which outcomes still lack an adequate declared contract. This is not a Catalog
sales launch, a new profile, an external integration credential, a new API version
or complete API safety acceptance. HEAD/OPTIONS, other Catalog operations and
consumer installations are outside this two-operation review.

## Traceability and ownership

INT-001 governs the API contract; NFR-009 governs closed, typed inputs and
concurrent validation; AUD-001 governs privileged mutation and sensitive-read
evidence; NFR-002/003 govern maintained documentation and handoff; NFR-013 governs
profile boundaries. FUR-005/006 and FIN-007 provide the underlying charity,
merchandise and reconciliation context. Read the
[requirements](../product/requirements.md),
[Catalog module](../modules/catalog.md) and
[mounted API contract](../modules/catalog-api.md) together.

Accepted ADRs [0001](../architecture/decisions/0001-python-django-modular-monolith.md),
[0003](../architecture/decisions/0003-capability-and-scope-authorization.md),
[0050](../architecture/decisions/0050-governed-admission-upgrades-capacity-and-edition-commerce.md)
and [0056](../architecture/decisions/0056-private-schema-backed-api-reference.md)
remain unchanged. Catalog owns the adapter, products, definition, command receipt
and business outcome. Authorization resolves trusted scope and decides capability;
Events owns the edition and exact adoption profile; Audit and Effects own their
append boundaries. No new architecture decision is made by this review.

| Operation | Purpose and current authority | Inputs and success | Owning execution and review outcome |
| --- | --- | --- | --- |
| `catalog_retrieve_edition_catalog` — GET | Read currently offered products through `catalog.order_self` for the exact person and edition. This is not the staff definition editor or order-history query. | UUID route scope; no accepted query fields. `200` contains `catalog_version`, `currency`, and `products` with variant projections. | `available_products_for_actor`, followed by an exact-scope `EditionCatalog` lookup. Closure, completeness, read-audit and failure/concurrency evidence require the follow-up below. |
| `catalog_create_edition_catalog` — POST | Create the edition's single draft catalog through `catalog.manage`, including the existing platform-administration policy path. | Closed JSON `currency` and `reason`; canonical UUID `Idempotency-Key`. A new result is `201`; an existing matching receipt is `200`, both with `target_id`, `resulting_version`, `replayed`. | `create_catalog` serializes creation on the edition row and commits receipt, event/outbox and audit with the draft. Input normalization, replay identity and authority timing need explicit conformance decisions. |

## Authority and disclosure

Both methods inherit DRF authentication and `IsAuthenticated`; the locked settings
resolve SessionAuthentication and BasicAuthentication. Session-authenticated unsafe
requests retain DRF's CSRF boundary. Listing Basic in the schema does not approve
third-party credentials, service principals or a general integration mechanism.
`_actor` requires an active `Account`. The service then resolves exact persisted
organization and edition scope, including the edition's series organization.

GET uses the code-owned self target. `resolve_self_target` requires a persisted
person account and seals that person's own ID; it does not require a registration,
purchase or membership. A platform-admin account kind is not a convention person.
The policy checks exact profile capability before accepting the self relationship.
POST resolves edition scope before parsing the body and repeats capability
authorization in `create_catalog`. `catalog.manage` is non-delegable and carries
reason/audit obligations. The general policy currently allows platform
administration for this capability; it is inaccurate to describe creation as
requiring only an ordinary staff grant.

At the reviewed revision, both capabilities are present in `full_convention@1`.
They are absent from every other registered profile: `workforce_only@1`,
`announcements_only@1`, `guidance_only@1`, and `announcements_guidance@1`.
Reading or creating a catalog does not adopt Catalog or expand any profile.
Neither reviewed service creates Registration, Participation or payment records.
This source finding is not a whole-workflow absence rehearsal or approval for a
standalone Catalog profile.

GET authorizes before querying product labels and before reporting unknown query
fields. It returns active products from an active catalog within sale windows,
ordered by position, name and ID, with active variants. Product and variant values
are explicit dictionaries: identifiers, public product description and beneficiary,
public charity name, sale/fulfilment limits, price and current stock projection.
No order, attendee, receipt reason or provider payload appears in that dictionary.
The response serializer is declared for schema generation; the adapter constructs
the response directly rather than serializing it through that class at runtime.

The later catalog lookup is exact-scope but not status-filtered. An authorized
person can therefore receive catalog version/currency with an empty product list
for a draft or closed catalog. Do not describe every successful GET as an active
sale. A missing catalog after successful authorization maps to `404`; a missing,
foreign or unadopted authorization target is denied before that lookup. Actual
status behavior at routing, authentication and dependency failures needs the
separate conformance cases below.

## Inputs, retry and concurrency

POST allows exactly `currency` and `reason`; unknown query/body properties are
rejected. The API preflight precedes JSON parsing. Currency is a DRF CharField of
length three; reason is a CharField of length 1–500. Blank and null are not allowed.
CharField trims whitespace, and the service uppercases currency and strips reason.
There is no ISO currency-membership validator in this command. Database-free
serializer probes also confirmed that numeric JSON scalars `123` and `456` become
strings for these fields, although OpenAPI declares strings. An alphabetic or
strict JSON-string currency contract must not be claimed from a length check.

`Idempotency-Key` must equal its parsed UUID's lower-case hyphenated representation;
missing, malformed, uppercase or padded values fail. It is not accepted in JSON.
Creation accepts no `expected_version`: it locks the exact edition row inside
`transaction.atomic()` and relies on the one-catalog-per-edition model constraint.
Later aggregate mutations have their own version contracts and are outside scope.

The creation digest contains operation, organization ID, edition ID and normalized
currency. It excludes reason, correlation ID and source channel. Receipt lookup is
scoped to catalog, actor and key. Same-actor/key/digest replay returns the original
target and resulting version without writing another receipt, event or audit.
A different normalized currency with that key conflicts; another key when a
catalog exists reports that the catalog already exists. Changing only a valid
reason does not change replay identity or replace the recorded original reason.
The result version is the original creation version, not a refreshed catalog
version after later work. These are observed semantics, not a newly approved
integration retry policy.

The edition lock serializes creation, but the command's capability check is before
the atomic block; no second decision is visible after the lock. GET also assembles
products, catalog version and stock across separate reads without an explicit
snapshot or reauthorization immediately before response construction. This review
does not establish behavior under simultaneous revocation, closure or stock change.
Those cases need controlled native evidence and an explicit owner decision, not
an optimistic concurrency claim inferred from the presence of a version field.

## Failures, cache and availability

`_execute` translates AuthorizationDenied to generic `403`, ObjectDoesNotExist to
generic `404`, and Django ValidationError to DRF validation `400`. Existing
creation and retry conflicts follow that `400` path, not a declared `409` contract.
The mapping passes messages/dictionaries rather than preserving all Django error
codes; clients cannot assume `catalog_idempotency_conflict` survives as the public
problem code. Invalid input and authentication/parser failures handled by DRF use
the configured `problem_exception_handler` with `application/problem+json` and
`type`, `title`, `status`, `detail`, `code`, plus applicable errors/request ID.

`PrivateCatalogAPIView` applies `never_cache` to dispatch; existing tests verify
private/no-store semantics on handled denial, validation and success responses.
The shared correlation middleware assigns a valid UUID or generates one and returns
`X-Request-ID`. The command uses that ID for evidence. Do not infer coverage of
unhandled exceptions, router-generated responses or every middleware failure from
those handled-response tests.

Neither operation declares problem responses or cache/correlation response headers
in OpenAPI. Only GET `200` and POST `200`/`201` are declared, with empty response
descriptions and no inline operation examples. POST does declare the required
canonical idempotency header and closed request object. Missing metadata is
documentation debt; it is not proof of missing runtime authorization or caching.

Catalog's adapter does not translate arbitrary database failures to
DependencyUnavailable. The shared DRF handler returns `None` for unrecognized
exceptions. Scope resolvers have some fail-closed handling, but this is not an
operation-wide, stable `503` contract. Do not add a `503` promise until dependency
failure paths have been exercised and their safe boundary agreed.

GET has no pagination, explicit product/variant maximum, or complete-or-unavailable
overflow decision. It materializes all eligible products and active variants and
computes stock per variant. The deterministic product order is not a resource
budget or a snapshot guarantee. A bounded response policy needs an explicit
compatibility decision before implementation; silently truncating results would
not meet the review's completeness requirement.

## Evidence, consumers and recovery

POST atomically writes the draft, CatalogCommandReceipt, minimized `catalog.create`
AuditEvent, `catalog.definition.changed.v1` DomainEvent and outbox work. The receipt
retains the normalized reason; the response omits it. Event payload contains only
creation action, target kind and draft state. The event is in the Effects internal
acknowledgement set; creation is not notification delivery, catalog activation or
payment. Replay returns before these writes.

GET's `catalog.order_self` decision carries an `audit` obligation, but the product
query does not call the Catalog audit helper or another read-audit service. Whether
this merchandise projection needs purpose-specific read evidence must be resolved
against AUD-001 and the capability obligation. Do not equate code-owned self access
with an audited sensitive read, or add person-activity collection without its
purpose, visibility and retention contract.

The generated staff-console `src/api/schema.d.ts` contains the operation types.
A source search found no handwritten frontend call site naming either operation
or Catalog API path. This is a repository observation, not proof that no external
consumer exists. Same-shell Catalog pages invoke the shared services directly;
their UX and browser acceptance are not evidence of HTTP/schema equivalence.

Creation's transaction protects synchronous evidence from partial commit; it does
not establish outage/retry/recovery certification. Existing Catalog migration and
rollback fences remain as described in the module document: retained business and
authority history cannot be deleted or guards bypassed to reverse adoption.
No migration, role privilege, readiness fingerprint or recovery policy changes
in this review. Operating controls for refunds, fulfilment and real providers
remain outside this slice and are still required before applicable sales use.

## What was checked and what remains

Source paths below are relative to the repository root and bound to the revision
above. The ignored evidence bundle hashes the principal source/test files and records exact
schema fragments, profile capability membership, resolved authentication classes,
five data-free serializer probes and creation digest fields. It invokes no domain
service or database and creates no account, grant or business record.

| Evidence | What it supports | Limit |
| --- | --- | --- |
| `src/maru/catalog/{api,serializers,services,models,urls}.py` | The two route adapters, input/output shape, receipt digest, lock and write sequence. | Source inspection is not concurrent native execution. |
| `src/maru/authorization/{policy,catalog}.py`, `src/maru/events/adoption.py` | Trusted target, person/self and platform paths; exact profile capability membership. | No new real-account grant or revocation test was run. |
| `src/maru/core/{api_input,serializers,problems,middleware}.py`, settings and Effects handlers | Closed inputs, handled problem/cache/correlation behavior and internal event acknowledgement. | No universal outage, middleware or external-consumer guarantee. |
| `tests/unit/test_catalog_venues_api_contract.py` | Typed success declarations, anonymous denial before malformed input/query, create/replay HTTP status, canonical keys. | Command/auth calls are mocked in adapter cases; the schema test currently expects success-only response sets. |
| `tests/unit/test_catalog_charity_api_runtime.py` | Dispatch/projection, known domain error mapping, identity/key helpers and scalar/model checks. | Empty mocked product projection is not a full nested-product or recovery case. |
| `tests/unit/test_private_api_preflight.py` | GET denial before unknown-query validation and handled private/no-store responses. | Does not prove every dependency or routing path. |
| `tests/integration/test_catalog_commerce.py` | Existing native lifecycle, tenant/owner/profile boundaries, same-service browser commands and immutable evidence separation. | Adjacent order/browser tests are not complete native HTTP tests for this GET/POST pair. No new native run was performed for this source review. |

The four existing unit files for Catalog/venues contracts, Catalog/charity runtime,
private preflight and mounted-domain schema passed **115 cases in 1.64 seconds**.
All 14,285 database-free unit cases also passed in 77.51 seconds. Documentation
policy (760 Markdown files) and whitespace passed. Source review and serializer
probes agree with the facts above. The preceding
inventory PR passed its own exact local and hosted acceptance; those receipts do
not certify this new documentation candidate. Final delivery checks belong in
CURRENT and the [checkpoint](../checkpoints/2026-10-17-catalog-api-contract-review.md).

## Bounded follow-up and stopping rule

The next proposed outcome is a reviewed **two-operation conformance plan**, not an
API-wide rewrite. Catalog owns the following decisions with Authorization, Audit
and Core consulted only for their boundaries:

1. Agree accepted currency/scalar normalization and whether reason belongs in
   retry identity; retain existing behavior until compatibility is assessed.
2. Specify a complete bounded GET projection, draft/closed visibility and the
   relevant concurrency/authority moment; decide the audit obligation deliberately.
3. Name public validation/conflict/dependency outcomes and their safe HTTP/problem
   codes, headers and examples; distinguish router/auth/parser responses from
   adapter results. A schema declaration must describe actual supported behavior.
4. Define native HTTP cases for same/foreign scope, unadopted profile, malformed and
   unknown inputs after denial, exact and changed retry, two concurrent creates,
   revocation/closure timing, complete projection, dependency rollback and cache/
   correlation on each supported outcome. Then update narrowly scoped schema and
   generated-type assertions without weakening existing negative coverage.

Stop after those decisions and their acceptance criteria are explicit. Any behavior
change, new audit collection or compatibility policy belongs in a separately
reviewed implementation scope with requirements/ADR changes when needed. This
document closes the two-row source review only. Issue #36, production acceptance,
service-principal design, compatibility/version policy and consumer-complete
OpenAPI across other operations all remain open. Existing demos are unaffected.
