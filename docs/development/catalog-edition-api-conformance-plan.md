# Catalog edition API conformance plan

**Audience:** Catalog maintainers reviewing the next API safety increment\
**Outcome:** Separate an executable existing-behavior baseline from decisions
that must precede compatibility or operating changes\
**Status:** The 20-case baseline was protected-delivered in PR #217. Twelve
additional creation-retry cases passed focused native verification; exact delivery
and behavioral decisions remain open

The [source review](catalog-edition-api-contract-review.md), delivered in
[PR #216](https://github.com/martonpornoi/maru/pull/216), identifies the two
operations at the edition Catalog route. This plan applies only to
`catalog_retrieve_edition_catalog` and `catalog_create_edition_catalog`.
Issue #36 remains a planning umbrella, not API-wide implementation or production
approval. This increment adds evidence for existing behavior without changing
runtime, schema, authentication, profiles, permissions or earlier assertions.

INT-001, NFR-009, NFR-013 and AUD-001 apply. ADRs 0001, 0003, 0050 and 0056
remain unchanged. Catalog owns its adapters and services; Authorization, Audit
and Core retain their existing boundaries. Demos are unaffected.

## First bounded evidence increment

The existing `tests/integration/test_catalog_commerce.py` gains 20 cases over
the real mounted adapter and migrated PostgreSQL models. Commands and policy
decisions are not mocked. An in-process DRF test client supplies an authenticated
principal directly where needed; anonymous cases do not. This does not exercise
password entry, real session authentication, HTTP Basic, CSRF, a network server,
restricted-runtime login, browser usability or independent-human acceptance.

| Case group | Required observation | Explicit limit |
| --- | --- | --- |
| Eight GET/POST denials | Anonymous, inactive, mismatched organization/edition and unadopted profile requests reject before malformed private input; no supplied private label is reflected. | Foreign scope means an inconsistent trusted tuple; a person is not denied a valid self projection merely for lacking organizer membership. |
| Nine invalid creates | Missing, empty, uppercase or padded retry key; unknown body/query; malformed JSON; short currency; blank reason all reject without creation or new evidence. | Does not choose strict scalar types or ISO currency membership. |
| Create and exact replay | A normal create returns 201 with a draft and one receipt/event/outbox/audit; the exact retry returns 200 with the original target/version and no duplicate writes; changed currency conflicts without mutation. | Does not decide changed-reason retry identity, simultaneous requests, revocation or outage recovery. |
| Self projection and distinct authority | A person's active-catalog response has exactly the expected nested public fields and stock; the person cannot create and the platform account cannot become a convention subject. | One bounded fixture does not prove cardinality limits or concurrent snapshot consistency. |
| Authorized absence and query rejection | Authorized missing catalog returns 404; an active catalog rejects unknown query fields with 400. | Does not normalize every router or dependency failure. |

Every response in these cases checks private/no-store caching and correlation;
handled errors check problem media type and required fields. State comparisons
cover the named Catalog, Audit, Effects, admission-product and entitlement tables.
They are not a complete catalog-derived unadopted-model inspection or a claim that
all modules are unchanged. The isolated test runner must preserve source identity,
every failure and exact owned-resource cleanup. Existing tests remain intact.

## Creation retry evidence increment

The next bounded increment adds 12 cases to the same native adapter module,
alongside all 28 existing cases. It records existing behavior without choosing
a new compatibility policy or changing an application command.

| Cases | Required observation | Limit |
| --- | --- | --- |
| Two metadata/version replays | A changed valid reason, request ID and trusted source channel preserve the original immutable receipt and creation version, including after a product advances the catalog. | The retained reason is not amended; future reason-digest policy remains open. |
| Three rejected retries | Another authorized actor, another key or a blank reason rejects with the existing private problem response and no new evidence. | No new public error-code/status contract. |
| Two scope cases | The same actor/key creates independent catalogs in separate editions of one or two organizations. | Both requests are authorized; this does not grant cross-tenant access. |
| Two evidence failures | Failure after a real event/outbox or audit write rolls back catalog and all evidence; retrying the same key creates a fresh result. | Existing unhandled dependency exceptions are observed, not a promised public `503`. |
| Three concurrent requests | Two independent requests demonstrably wait on the edition row before release; identical intent creates once and replays, while changed currency or key creates once and rejects its competitor. | Authority/profile remain stable; concurrent revocation and closure are not tested. |

Tests inspect exact response identities, cache/correlation headers, receipt
contents and named Catalog/Audit/Effects/admission counts. The original case
definitions and assertions remain unchanged. Commands and authorization are real;
only the two evidence append boundaries receive explicit late fault injection.
The [delivery and retry checkpoint](../checkpoints/2026-10-19-ci-delivery-and-catalog-retry-conformance.md)
records actual evidence and remaining gates. This does not close issue #36 or
resolve the behavior-changing decisions below. Demos are unaffected.

## Decisions before a behavior-changing increment

These are explicit unresolved choices, not newly accepted semantics. A later
review must select and document the intended behavior, consumer impact and
acceptance criteria before changing an adapter or schema promise.

| Owner decision | Alternatives to assess | Evidence required before acceptance |
| --- | --- | --- |
| Catalog input normalization | Retain observed CharField coercion and length-only currency, or introduce strict JSON strings and a supported-currency rule. | Inventory affected callers; test strings/numbers/null/blank/normalization; define compatibility and actionable failures. |
| Catalog retry identity | Retain normalized-currency identity with the original reason, or include reason in the digest. | Exact, changed-reason and changed-currency replay; actor/key scope; ambiguous response and concurrent-create recovery; documented consumer transition if needed. |
| Catalog read completeness and lifecycle | Retain current draft/closed empty projections, or define a changed visibility policy; choose pagination or complete-or-unavailable cardinality limits. | Zero/exact-limit/overflow and nested variant budgets; no silent truncation; deterministic ordering and query-cost evidence. |
| Authorization under concurrent change | Define the decision point for create/read when authority, profile, closure or stock changes. | Controlled two-connection interleavings and lock-order evidence; no claim that preflight alone proves race safety. |
| Audit purpose for self merchandise reads | Reconcile the current audit obligation with data classification; choose purpose-specific evidence or an explicitly reviewed policy correction. | Purpose, lawful basis, visibility, retention and minimization before collecting new activity; mandatory evidence failure must have defined disclosure behavior. |
| Core/Catalog public failures | Decide supported validation, conflict and dependency codes/statuses and headers for each actual path. | Native handled failures and rollback, router/auth/parser separation, safe dependency failures; no generic 503 promise before execution. |

Schema changes follow supported behavior, with synthetic examples and generated
type parity. A schema cannot grant authority or invent guarantees. Service
principals, credentials, public documentation, `/api/v2`, blanket URL cleanup,
payment providers, production operations and unrelated endpoints remain outside
this pair. The test fixture is not a workaround for the separate Workforce
recipient-password handoff.

## Completion and stopping rule

This increment completes when its 20 new cases and relevant existing cases pass
on unchanged source, resource cleanup is independently verified, the candidate
passes ordinary exact-head local and protected hosted acceptance, review findings
are resolved, and the merged tree and designated clean main match. Until then,
focused passing cases remain distinct from complete certification and delivery.

The decision table remains open after this baseline passes. Any chosen behavioral
change needs a separately reviewed implementation scope and requirement/ADR update
where applicable. Issue #36 stays open; neither this plan nor CI supplies complete
HTTP, concurrency, recovery, human or production acceptance. Current results belong
in [CURRENT](../project/CURRENT.md) and the
[checkpoint](../checkpoints/2026-10-17-catalog-api-conformance-baseline.md).
