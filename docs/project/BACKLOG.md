# Implementation backlog

Status: Historical V00–V02 acceptance backlog; foundation is implemented
Last updated: 2026-09-01

This file preserves the original foundation acceptance contracts and is not
the current work queue. Use `PRODUCTION_CONSOLIDATION.md` for mounted,
API-only, preserved/unmounted, partial, absent, and deployment-gated status and
for the current milestone order.

This backlog makes V00–V02 executable. Later slices remain in the delivery plan
until their discovery and predecessor contracts are ready.

## Backlog conventions

- `P0` blocks the trustworthy walking skeleton.
- `P1` is required before a real partner pilot.
- Every item links requirements or an ADR.
- Acceptance includes tests and documentation even when not repeated.
- “Done” means the repository definition of done, not code written.

## V00 — engineering foundation

### MARU-FND-001 — Python project and dependency contract (`P0`)

**Requirements:** NFR-001, NFR-002, NFR-003  
**Deliver:** `pyproject.toml`, supported Python declaration, locked runtime/dev
dependencies, package layout, command shortcuts, and dependency update policy.

**Accept:**

- clean environment can install reproducibly;
- runtime and development dependencies are separated;
- all checks run through documented commands; and
- dependency and license inventory can be generated.

### MARU-FND-002 — Django configuration boundary (`P0`)

**Requirements:** NFR-004, NFR-006, NFR-008; ADR-0001  
**Deliver:** Django project, settings from validated environment, custom account
model from the first migration, UTC storage, localization, secure production
defaults, and explicit test configuration.

**Accept:**

- missing or unsafe production settings fail startup;
- debug, allowed origins/hosts, cookies, proxy headers, mail, database, storage,
  and telemetry settings do not have dangerous implicit production values;
- settings tests cover local/test/production validation; and
- `manage.py check --deploy` findings are resolved or documented.

### MARU-FND-003 — PostgreSQL development and test runtime (`P0`)

**Requirements:** NFR-001, NFR-008; ADR-0001  
**Deliver:** documented local PostgreSQL service, independent test database,
health check, migrations command, and representative CI service.

**Accept:**

- tests do not silently fall back to SQLite;
- database version and required extensions are explicit;
- a clean database migrates from zero; and
- connection failure is clear and non-destructive.

### MARU-FND-004 — Quality toolchain (`P0`)

**Requirements:** NFR-001, NFR-002  
**Deliver:** formatter, linter, type checker, pytest, coverage reporting,
security/static checks, migration drift check, and documentation/link checks.

**Accept:**

- one command runs the fast local gate;
- one command runs the complete CI gate;
- warnings do not disappear through blanket ignores; and
- generated or migration drift fails CI.

### MARU-FND-005 — Test architecture and synthetic factories (`P0`)

**Requirements:** NFR-001, NFR-006  
**Deliver:** unit/integration/API marker strategy, factories, time control,
property-test support, adversarial Unicode values, and initial two-tenant,
multi-edition reference fixture builder.

**Accept:**

- factories create no shared mutable tenant defaults;
- reference fixture is deterministic;
- tests can freeze edition-local time across DST; and
- production data is unnecessary.

### MARU-FND-006 — Build and health identity (`P0`)

**Requirements:** NFR-004, NFR-008  
**Deliver:** liveness/readiness endpoints, release/build metadata, correlation
middleware, safe structured logging foundation, and redaction tests.

**Accept:**

- liveness does not fail because a remote provider is down;
- readiness refuses traffic when safe serving is impossible;
- every request receives a correlation ID; and
- response/log metadata contains no personal payload.

### MARU-FND-007 — Development and operations documentation (`P0`)

**Requirements:** NFR-002, NFR-003  
**Deliver:** setup, commands, configuration, test, migration, troubleshooting,
release, and checkpoint instructions maintained with code.

**Accept:** a new contributor can reproduce the verified state using only
repository documentation.

## V01 — identity, tenant, and edition kernel

### MARU-IDN-001 — Custom platform account (`P0`)

**Requirements:** IDN-001, AUD-002, PRI-001  
**Deliver:** non-enumerable account ID, normalized verified contact boundary,
display preferences, locale, active state, security timestamps, and admin-safe
representation.

**Accept:**

- login identifier is not used as a cross-domain foreign identifier;
- account representation does not expose authentication internals; and
- account deletion cannot cascade blindly into tenant records.

### MARU-TEN-001 — Organization aggregate (`P0`)

**Requirements:** EVT-001, IDN-002  
**Deliver:** organization model, lifecycle, stable slug rules, ownership
metadata, locale defaults, and tenant manager/query primitive.

**Accept:** every tenant query requires explicit trusted context and tests fail
if an unscoped manager is used through the public application layer.

### MARU-TEN-002 — Convention series (`P0`)

**Requirements:** EVT-001, EVT-003  
**Deliver:** series aggregate scoped to organization with stable public identity
and template boundary.

**Accept:** duplicate aliases are prevented within their intended scope and
series cannot be reparented across organizations by ordinary mutation.

### MARU-EVT-001 — Event edition aggregate (`P0`)

**Requirements:** EVT-002, EVT-004, EVT-005, ARC-003  
**Deliver:** edition identity, series/organization scope, name/slug, time zone,
languages, currencies, dates, lifecycle, version, and transition service.

**Accept:**

- invalid date, zone, currency, and transition combinations fail;
- archive blocks ordinary writes;
- cancellation and correction are reasoned transitions; and
- organization/series/edition scope cannot disagree at the database boundary.

### MARU-IDN-002 — Membership and participation (`P0`)

**Requirements:** IDN-002, IDN-003, ARC-001, ARC-002, ARC-004  
**Deliver:** organization membership, edition participation, capacity/status
history, historical labels, and personal history query.

**Accept:**

- one account may have several capacities in one edition;
- organizer views cannot see other organizer participation;
- the account can see its own safe cross-organizer history;
- renaming a role or series does not rewrite an archived label; and
- public visibility defaults off.

### MARU-EVT-002 — Edition context API (`P0`)

**Requirements:** EVT-001 through EVT-005, UX-002, UX-008  
**Deliver:** list permitted organizations/series/editions, select explicit
context, distinguish live/draft/archive, and expose authoritative edition time.

**Accept:** a path, header, or token cannot override each other into a broader
tenant; ambiguous context is rejected.

### MARU-TEN-003 — Tenant isolation test matrix (`P0`)

**Requirements:** IDN-002, IDN-004, NFR-001  
**Deliver:** reusable test helpers exercising anonymous, self, same department,
same tenant, other edition, other tenant, expired, and archived contexts over
list/detail/search/count/write.

**Accept:** every V01 API uses the matrix and at least one deliberately unsafe
test fixture proves the harness detects leakage.

## V02 — authorization, audit, events, and jobs

### MARU-AUT-001 — Capability catalog (`P0`)

**Requirements:** IDN-004, IDN-005; ADR-0003  
**Deliver:** namespaced capability declaration with description, delegability,
maximum scope, field class ceiling, and high-impact obligations.

**Accept:** duplicate or undocumented capabilities fail checks and clients
cannot register capabilities at runtime.

### MARU-AUT-002 — Scoped grants and versioned role bundles (`P0`)

**Requirements:** IDN-004, IDN-005, HR-004; ADR-0003  
**Deliver:** principal, bundle/capability, tenant/edition/department scope,
effective interval, grantor, approver, source, review, delegation, and
revocation provenance.

**Accept:** root grants and role changes require two distinct authorized
controllers, cannot exceed either controller's scope or effective horizon, and
cannot turn relationship-derived capabilities into stored grants. Revocation
is immediate, tenant-scoped, reasoned, audited, and invalidates delegated
descendants.

### MARU-AUT-003 — Policy decision service (`P0`)

**Requirements:** IDN-002, IDN-004, QRY-003; ADR-0003  
**Deliver:** typed principal/resource/context input and allow/deny, fields,
obligations, safe reason codes, and policy version output.

**Accept:** deterministic unit/property tests cover scope intersection,
relationship, state, field projection, expiry, revocation, and monotonic
narrowing.

### MARU-AUT-004 — API/query enforcement (`P0`)

**Requirements:** IDN-002, IDN-004, QRY-001, QRY-003; ADR-0003  
**Deliver:** DRF integration, scoped queryset protocol, authorized serializer
projection, denial problems, bulk target freeze, and architecture check.

**Accept:** list, details, search, autocomplete, count, relationship, write, and
error shapes pass the isolation matrix without post-fetch filtering.

### MARU-AUD-001 — Audit writer and integrity batch (`P0`)

**Requirements:** AUD-001, AUD-002, AUD-005, PRI-001  
**Deliver:** append-only audit schema/API, safe event builder, sensitive-read
hook, correlation, integrity batches/checkpoint interface, and retention class.

**Accept:**

- normal application roles cannot update/delete audit events;
- protected values are rejected from the safe payload;
- privileged allow and deny events are correlated; and
- a modified/gapped test batch fails verification.

### MARU-EFX-001 — Domain event envelope and transactional outbox (`P0`)

**Requirements:** ANN-004, INT-002, NFR-004; ADR-0005  
**Deliver:** versioned event registry, outbox table, commit helper, claim/lease,
attempt/result, backoff, quarantine, correlation, and retention.

**Accept:**

- rollback produces neither state nor event;
- commit produces both;
- duplicate delivery is harmless;
- crashed claim becomes recoverable; and
- one tenant's backlog cannot bypass another tenant's bounds.

### MARU-EFX-002 — Worker and handler contract (`P0`)

**Requirements:** AUT-002, INT-002, INT-003; ADR-0005  
**Deliver:** typed handler registry, idempotency interface, retry taxonomy,
timeouts, workload pool, safe telemetry, and operator replay command.

**Accept:** tests cover success, transient failure, permanent failure, timeout,
duplicate, reordering, cancellation boundary, and poisoned payload.

### MARU-API-001 — API conventions (`P0`)

**Requirements:** INT-001, NFR-002  
**Deliver:** version namespace, problem details, pagination, filtering,
concurrency, idempotency, correlation, OpenAPI generation, and compatibility
check.

**Accept:** a reference resource exercises all conventions and generated schema
has stable operation identifiers and documented authorization.

### MARU-ACT-001 — Operational and security-history projections (`P1`)

**Requirements:** AUD-002, AUD-003, ARC-001  
**Deliver:** audience-specific timeline contract, user security-history query,
and participation-history projection separate from audit storage.

**Accept:** one action produces distinct safe user, staff, and audit renditions
with no unauthorized field or cross-tenant existence leak.

### MARU-OPS-001 — Baseline telemetry and runbooks (`P0`)

**Requirements:** NFR-004, NFR-005, NFR-008  
**Deliver:** service dashboards/alerts as code or documented definitions,
outbox and database health, failure injection, backup/restore skeleton, and
incident template.

**Accept:** a simulated database outage and worker poison item produce an
actionable alert, safe degraded response, and documented recovery evidence.

## Consolidated future slices

These items retain useful behavior learned from the owned legacy prototype.
ADR 0021 and the current module boundaries govern their implementation; the
prototype is an acceptance reference, not a code dependency.

Issue [#48](https://github.com/martonpornoi/maru/issues/48) is the accepted
Programme Operations delivery umbrella. Its first child,
[#57](https://github.com/martonpornoi/maru/issues/57), contracts
`programme_operations@1`, canonical ownership, and the ordered dependency
boundary without activating runtime behavior. Successor children must proceed
sequentially through exact-version profile enforcement, dormant Programme
items/readiness, intake/review, Scheduling core and editor, Workforce staffing,
release/projections, on-site continuity, and integrated recovery acceptance.
Each child remains independently tested, documented, reviewed, and protected-
merged before the next dependent child starts.

Issues #59, #61, and #63 complete the first three implementation prerequisites:
exact v1 manifest enforcement, a dormant private Programme item/readiness
domain, then dormant Applications-owned calls and acknowledged proposal
revisions. The active queue now continues with preview-first call/proposal
import. Review/decisions and the accepted Programme adapter follow; Programme
host/co-host relationships begin only after that accepted transition. Profile
activation remains last, after every mandatory continuation passes.

### MARU-PRG-001 — Proposal-to-programme lifecycle (`P1`)

**Requirements:** PRG-001 through PRG-009, AUD-003, SCH-001
**Deliver:** Applications-owned calls, exact acknowledged proposal revisions,
accountable review/revision requests and decisions, then an explicit accepted-
item transition into separately authorized Programme readiness work. Issue #63
completes the dormant call/proposal kernel only; import, review, decisions, and
the accepted adapter remain successor work.

**Accept:**

- every submitted revision and decision remains attributable and immutable;
- a proposal collaborator cannot reveal another proposal, private contributor
  profile, or review data and does not become a host;
- advancement is idempotent and cannot occur as a model/admin save side
  effect; and
- public projections contain approved programme fields only.

### MARU-SCH-001 — Shared versioned timetable (`P1`)

**Requirements:** SCH-001 through SCH-012, VEN-001, VEN-002, OPS-009
**Deliver:** edition-local service days, precision, ordered layers and groups,
recurring occurrences, draft/publication versions, room assignment, conflict
explanations, and attendee/person/department/venue/print projections.

**Accept:**

- all projections derive from one approved schedule version;
- person, room, combined-space, availability, setup, travel, rest, resource,
  and staffing conflicts are tested;
- locks and publication do not mutate historical versions; and
- reasoned warning overrides cannot bypass hard authorization or safety rules.

### MARU-HR-002 — Volunteer shift commitments (`P1`)

**Requirements:** HR-009, HR-015, SCH-003, SCH-005, AUD-003

**Current slice:** governed Position-specific demand, suitable personal claims,
organizer confirmation/removal, person-owned withdrawal, underfill-aware
locking, reopening, cancellation, and completion are implemented under ADR
0078. The backlog item remains open for the broader qualification, overlap,
maximum-hours, publication, check-in, and timekeeping model.

**Deliver:** separate shift demand and claimed, confirmed, removed, locked, and
completed commitments with qualification, availability, overlap, break,
capacity, and privacy-aware suitability explanations.

**Accept:**

- concurrent claims cannot exceed demand;
- volunteers see their own commitment state without seeing other applicants'
  private records;
- coordinators receive only fields justified by staffing work; and
- removal and completion preserve history and update future capacity
  transactionally.

### MARU-VEN-001 — Reusable venue catalogue (`P2`)

**Requirements:** VEN-001, VEN-002, VEN-008, PRI-001
**Deliver:** stable organization-owned properties, spaces, room combinations,
and governed floor-plan references with explicit edition selection and
edition-local names, opening, blocks, availability, and overrides.

**Accept:** omitting a property from an edition creates no implicit use;
combined spaces cannot conflict with components; an override does not rewrite
the source catalogue or another edition; and floor-plan access is authorized
and audited.

### MARU-INT-002 — Publication and read-projection credentials (`P1`)

**Requirements:** ANN-001 through ANN-006, INT-003, INT-008, QRY-007
**Deliver:** canonical versioned announcements, scheduled approval,
per-destination delivery evidence, and typed minimized website, timetable,
profile, shift, and signage projections using expiring, rotatable, revocable
credentials.

**Accept:**

- connector failure cannot erase or mutate canonical approved content;
- a credential is scoped to one tenant, audience, projection, and lifetime;
- rotation supports overlap and one-time secret display without routine URL
  credentials; and
- access telemetry excludes secrets and unauthorized personal fields.

## Foundation release acceptance

V00–V02 are complete only when:

1. zero-to-running and zero-to-migrated paths work from documentation;
2. full tests run on PostgreSQL;
3. two organizations, three editions, and several overlapping personas exist
   in synthetic fixtures;
4. tenant and field isolation are proven through API and queries;
5. archive state rejects ordinary mutation;
6. an authorized command commits audit and an outbox event atomically;
7. duplicate and failed background processing is visible and safe;
8. generated OpenAPI passes compatibility checks;
9. logs/traces pass redaction tests;
10. restore and migration smoke procedures run; and
11. current state and milestone checkpoint accurately describe limitations.

## Authorization boundary

Foundation acceptance does not by itself authorize production personal data.
The registration safety implementation now includes verified identity, hosted
payment and authenticated webhook boundaries, real SMTP projection, finance
evidence, privacy operations, and bounded offline check-in. A target deployment
still requires provider/infrastructure certification, representative load,
partner policy review, named operational owners, and edition go/no-go. Synthetic
principals, demo payment, test tokens, and rehearsal data must remain labelled
and disabled in production.
