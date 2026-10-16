# API contract inventory — 2026-10-16

**Audience:** Contributors planning API contract work

**Outcome:** Locate each declared operation, distinguish schema gaps from runtime
evidence, and select one bounded follow-up

**Status:** Dated read-only inventory; not API safety certification or production acceptance

This is one planning slice of [issue #36](https://github.com/martonpornoi/maru/issues/36),
under INT-001 and NFR-002/003/009/013. It does not complete the umbrella's uniform
safety inventory: purpose, audience, authority, lifecycle, audit, limits, consumers
and operational readiness still require per-operation review. It introduces no
endpoint, credential, supported API version, runtime rule or compatibility promise.

The source is protected-main commit
`979de2a0e97bd43a33198e0e46c1237376033b7e`. The LF-normalized SHA-256 of
`openapi.yaml` is
`6fcdcef07c109e3ae6a017610b319f8bd0d6ab6c96e27024739f4edbc9fbe6d8`.
The schema remains authoritative; this dated snapshot does not replace it.
Do not carry these counts forward as current facts after the source changes.

## Complete declared-operation index

Download the [240-row CSV](api-inventory-2026-10-16.csv). Every OpenAPI
path/method/operation ID appears exactly once, including 238 `/api/v1/` operations
and the two health operations. All paths resolved through the default Django
URL configuration without connecting to a database. The adapter column identifies
the resolved view's module and class; it is a source locator, not proof that the
view owns every underlying domain rule.

This inventory covers operations declared in the checked-in schema. It does not
prove that every mounted route is represented, that every declared HTTP method
works, or that dormant code is a supported API. HTML pages, the private schema
reference, unmounted adapters and workers are not inferred as additional API
capabilities. A later route-to-schema conformance check must test both directions.

| Resolved adapter module | Operations | Only success responses declared | Declares problem media type |
| --- | ---: | ---: | ---: |
| accreditation | 6 | 6 | 0 |
| applications | 10 | 10 | 0 |
| audit | 1 | 1 | 0 |
| authorization | 5 | 5 | 0 |
| catalog | 11 | 11 | 0 |
| charities | 10 | 10 | 0 |
| communications | 5 | 5 | 0 |
| core | 2 | 1 | 0 |
| events | 10 | 5 | 5 |
| identity | 22 | 16 | 6 |
| logistics | 32 | 32 | 0 |
| organizations | 3 | 0 | 3 |
| participation | 4 | 4 | 0 |
| privacyops | 9 | 9 | 0 |
| registration | 53 | 43 | 10 |
| venues | 21 | 21 | 0 |
| workforce | 36 | 18 | 18 |
| **Total** | **240** | **197** | **42** |

The index contains only transport/source metadata, no account or convention
records, credentials, tokens, request bodies or sensitive findings. Publication
does not change the private runtime documentation boundary in
[ADR 0056](../architecture/decisions/0056-private-schema-backed-api-reference.md).

## What was measured

| Observation | Result | Meaning and limit |
| --- | ---: | --- |
| Paths / operations / component schemas | 210 / 240 / 529 | The earlier issue snapshot had 528 schemas. Neither count proves completeness. |
| Unique operation IDs | 240 | No duplicate ID in this artifact. |
| Operations declaring only success responses | 197 | No explicit 4xx, 5xx or default response; this does not mean runtime cannot reject. |
| Operations declaring `application/problem+json` | 42 | A declared problem is not proof of all possible failures. Readiness declares 503 without a response media type, accounting for the other non-success operation. |
| Operations with at least one empty response description | 235 | A description may be missing even when a typed schema exists. |
| Inline operation example locations | 0 | No `example` or nonempty `examples` within operation metadata. Referenced component properties contain 12 examples, so the whole schema is not example-free. |
| Operations with declared request / response headers | 81 / 6 | These count parameter/response declarations, not actual HTTP traffic or all applicable headers. |
| Schema validation | 0 errors, 23 unique warnings | Enum-name warnings remain preserved; none was suppressed or fixed here. |

The CSV's JSON closure column reads only the root schema's explicit
`additionalProperties` after resolving a direct local component reference.
`false` says nothing about nested objects, composition, multipart fields, query
parameters or runtime rejection. `unspecified` is not a finding that runtime
accepts extra fields. An absent JSON body is recorded separately.

Security declarations are 222 `cookieAuth OR basicAuth`, 12 of those alternatives
also admitting an empty requirement, two empty requirements alone, and four with
no named scheme declared. These are schema expressions, not authentication tests.
In particular, the account-invitation acceptance operation declares no session
scheme but requires its real expiring single-use bearer challenge. A public path
prefix or an empty security list never establishes unrestricted authority.

## Source cross-checks and exceptions

The source review deliberately sampled different boundaries; it did not mark all
240 operations safe.

| Boundary | Evidence and consequence |
| --- | --- |
| Catalog read and creation | `CatalogDetailApi` in `src/maru/catalog/api.py` declares success schemas while its `_execute` maps authorization, absence and validation failures. `PrivateCatalogAPIView` uses `never_cache`; `_validated` rejects unknown query/body fields. Missing problem/header declarations are documentation debt, not permission to remove those guards. |
| Workforce structure read | `WorkforceStructureView` in `src/maru/workforce/api.py` declares typed 400/403/503 problems, loads a version-fenced snapshot, repeats final authorization and requires minimized read evidence. Its scoped module contract supplies context that the schema alone cannot prove. |
| Account invitation acceptance | `src/maru/identity/invitation_api.py` separates fresh privileged invitation management from public challenge acceptance. [Identity's contract](../modules/identity.md) and [the integration architecture](../architecture/integrations-and-extensions.md) describe the single-use bearer, password minimization and retry boundary. It must not inherit an ordinary staff-session template blindly. |
| Public projections, signed webhook and offline ingestion | Rows such as public Venue schedule, payment webhook and offline check-in are separate review classes. Their schema security notation alone proves neither public disclosure safety nor signature/device verification. Inspect their owner contracts and tests before proposing shared defaults. |

The shared `src/maru/core/problems.py` handler translates recognized DRF
exceptions to problem details; it returns `None` for exceptions DRF does not
handle. Merely finding that helper is not proof that every failure is translated
or that every operation has the same statuses. Keep failure evidence and
non-disclosure specific to the actual adapter and owning service.

Existing tests used for focused feedback were
`test_mounted_domain_api_schema.py`, `test_catalog_venues_api_contract.py`,
`test_private_api_preflight.py` and `test_api_documentation_assets.py` under
`tests/unit/`: 44 cases passed in 2.64 seconds. They cover selected generated
contracts, malformed-input preflight and private-cache boundaries. They do not
establish every native transaction, role, browser or production case.

## Next bounded contract review

The first proposed follow-up is exactly `catalog_retrieve_edition_catalog` and
`catalog_create_edition_catalog`, the GET/POST pair at
`/api/v1/catalog/organizations/{organization_id}/editions/{edition_id}/`.
This is a small read-plus-governed-mutation comparison, not a Catalog workflow
rebuild or completion of API safety. Review its contract before implementation.

The review should produce one evidence row per operation with:

1. Purpose, actor, required capability/relationship, adopted-profile eligibility
   and trusted organization/edition/resource resolution order.
2. Closed inputs and bounds, exact success/replay behavior, all supported safe
   problems, cache/correlation headers and an explicitly documented concurrency
   and idempotency choice.
3. Owning command/query and audit behavior, known consumers, availability and
   recovery limits, and tests for denial-before-input, foreign scope, stale state,
   retry, unknown fields, dependency failure and schema/runtime agreement.

Stop when those two rows are complete and reviewed, with unresolved behavior
marked explicitly. Any subsequent annotation or conformance repair is a separate
bounded implementation outcome with its own exact acceptance. Do not infer
statuses, widen a serializer, weaken authorization, or introduce a general client
framework to make this comparison easier.

After that, expand owner by owner, retaining separate public/self/bearer/webhook/
offline exceptions. Version/deprecation governance, a typed transport client,
service principals and operational acceptance remain later issue #36 stages.
No `/api/v2`, endpoint removal, Basic-auth support decision, public developer
portal, application installation or production rollout is authorized by this
inventory. Earlier requirements and accepted ADRs remain in force.

## Reproduce and interpret the evidence

Use the pinned source above with locked dependencies. Keep the database URL
unreachable for this read-only source/schema exercise; do not point it at a real
convention. In PowerShell, from the repository root:

```powershell
$env:MARU_DATABASE_URL = 'postgresql://maru:maru@127.0.0.1:1/maru_unit_no_database'
uv sync --locked --all-groups
uv run python src/manage.py spectacular --file .tools/api-inventory.yaml --validate --settings=maru.settings.local
```

Retain the warning summary and compare parsed YAML to `openapi.yaml`; generation
must not silently update the source artifact. Recount only HTTP methods
`get/post/put/patch/delete/head/options/trace`, excluding path metadata. The
inventory was sorted by path and method. A direct local component reference was
resolved only for the JSON-root closure column; response statuses, headers,
descriptions and inline example locations were read from their declarations.

Resolve each templated path using valid synthetic UUID/string placeholders and
the default Django resolver, without invoking the view. This binds the adapter
locator, not endpoint behavior. Compare the CSV's complete `(method, path,
operation_id)` set to the schema and verify there are no extra or duplicate rows.
Do not rank runtime security from these metadata counts.

Schema regeneration in this review reproduced the checked-in parsed contract
exactly. Logs and extraction diagnostics remain under ignored `.tools/api-inventory`.
The CSV is review evidence at a named source revision, not a second live schema
or a new required CI gate. Exact local and hosted delivery evidence is recorded
separately in CURRENT and the
[checkpoint](../checkpoints/2026-10-16-api-contract-inventory.md).
