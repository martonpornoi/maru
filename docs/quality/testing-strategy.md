# Testing strategy

Status: Active
Last updated: 2026-09-07

Testing is part of product design. Coverage percentage alone is not an
acceptance criterion.

## Test layers

### Domain unit tests

Test state transitions, eligibility, pricing, entitlement, retention,
authorization policy decisions, schedule constraints, and archive behavior
without HTTP where practical.

Use parameterized and property-based tests for rule combinations and invariants.

### Database integration tests

Run against PostgreSQL for:

- constraints and indexes;
- transaction and rollback behavior;
- tenant and edition scoping;
- concurrent ticket, inventory, room, shift, and auction operations;
- outbox publication;
- archive immutability;
- migrations and representative historical data.

SQLite is not a substitute for PostgreSQL behavior.

#### Reusing historical setup without reusing test effects

Serial cases that exercise one transactional historical boundary may share a
module-scoped, committed historical baseline. Setup uses Django's real migration
executor to reach that baseline; teardown restores every current leaf through
the real executor. Each case still executes the migrations, preflights, forward
and reverse SQL, and assertions it owns. `rollback_migration_case()` discards
each case's rows, DDL, migration-recorder changes, and commit callbacks before
the next case. It checks deferred constraints before rolling back a successful
case so an invalid write cannot pass merely because cleanup discards it.

This is an explicit opt-in, not a global replacement for migration execution.
The helper requires PostgreSQL, a `test_` database, transactional DDL, and an
idle connection. `migrate_test_targets()` passes Django's native plan unchanged
and rejects non-atomic transitions inside a case. Do not use this pattern for
concurrency, other connections, commit visibility or callbacks, non-atomic
migrations, or recovery behavior. Those tests retain committed execution and
the ordinary full-graph restoration fixture. Never fake migrations, cache a
rendered Django model graph, disable guards, or skip historical cases for speed.

The initial adopters are the Workforce structure-write historical boundary,
historical organization governance, and historical authorization scope-v2
activation. Their current-state tests remain separate, all original cases are
retained, and PostgreSQL regressions prove schema/data/recorder isolation after
both success and failure, discarded callbacks, deferred-constraint enforcement,
and rejection of nested baselines. Unit tests reject unsafe database boundaries
and non-atomic plans in either direction.

The Registration profile-extension-value pilot applies the same opt-in boundary
to twelve serial ACL-retirement, backfill, and invalid-history cases. Its
module fixture creates synthetic Account, EventEdition, and Participation
parents while the schema is current, commits those parents before downgrading,
and gives each case their identifiers, not cached historical model classes.
Case-local records use the executor's actual historical models. Before real DDL,
Django's constraint checker validates deferred database constraints, matching
the original committed-input boundary without committing the case or disabling
checks. A regression rejects invalid deferred input at this boundary. Both schema
round trips and the populated durable-receipt downgrade fence stay in the
ordinary committed migration file. Real forward/backfill isolation regressions
exercise successful and failed case exits, and final teardown inspects all
current managed tables/columns and migration leaves without repair migrations.
See the [pilot checkpoint](../checkpoints/2026-09-06-registration-migration-test-pilot.md)
for comparable measurements and the limits of the speed claim.

When later migrations fence a full reverse plan before it reaches an older
guard, retain full-graph coverage elsewhere and exercise that older migration's
actual wired reverse operation separately. Scope-v2's retained-authority fence
tests include a clean control and expect its own `ADR 0041` refusal, not an
unrelated earlier Workforce error. This distinguishes the intended protection
from merely observing that some migration prevented downgrade.

Benchmark whole groups including shared setup and final restoration. A fast
case body alone is not a suite-speed claim. Refresh indivisible-group scheduling weights
from JUnit evidence after moving cases; compare full certification with the same
coverage and eight-worker topology before claiming an overall speedup. Keep the
120-minute fail-stop, complete selection, and branch-aware coverage gate intact.

The ADR 0044 no-truncate provenance and audit fences also apply in development.
Django's `TransactionTestCase`/pytest database flush is the sole exception: the
test settings pass `maru.authority_provenance_test_reset=on`, and each database
function independently requires the database name to begin with `test_`. Both
conditions are required. Production settings reject both a `test_` database
name and any appearance of the test-reset connection option. Tests must never
disable the trigger contract or reuse this escape against a development,
rehearsal, or production database.

ADR 0044 cutover tests additionally use real PostgreSQL to prove exact
function/trigger fingerprints (including older immutability and append-only
dependencies), absence of trigger predicates/arguments, fixed function and
connection schema order, temporary relation/function shadow resistance,
active-era timestamp bounds with clock-skew tolerance, concurrent stale-writer
and reverse-migration fences, and marker/audit atomicity. Health SQL receives
at least one unmocked PostgreSQL execution test. Every authority-derived shell,
navigation, tenant-name, and edition-selector projection repeats malformed
contract and revoked pinned-source denial tests; testing only destination
views is insufficient. A high-cardinality regression resolves 257 name-free
scope chains with a constant tenant-resolution query ceiling, while a separate
257-position exact-lineage batch proves the fixed 256-check SQL chunk limit and
stable positional results.

### API contract tests

Test:

- documented request and response schemas;
- status and error semantics;
- pagination, filtering, localization, and versioning;
- idempotency;
- OpenAPI generation and compatibility;
- field minimization for every audience.

Breaking API changes require an explicit migration and versioning decision.

Organization structure contract tests additionally require recursive OpenAPI and
typed read and mutation problems; denial before any name query; one captured
projection instant plus fresh final authorization; exact holder-role lineage
and active-person filtering; row, depth, and expanded-edge limit-plus-one
boundaries; an explicit no-partial overflow; malformed-graph/dependency `503`;
and stable query ceilings as row count grows. The implemented snapshot tests
also prove a short repeatable-read, read-only attempt, exact aggregate-version
comparison after the snapshot, one complete retry, and generic failure after a
second movement. The mounted mutation adapters additionally prove stale and
concurrent optimistic-version conflicts, exact retry/digest replay, atomic
template application, hierarchy races, normalized no-ops, dependency-safe
retirement/deletion, strict input and non-disclosure, and audit/event/outbox
rollback. Authenticated responsive, keyboard, automated-accessibility, and
complete rendered-state evidence remain separate acceptance gates.

### Authorization and isolation tests

Every endpoint and query must cover:

- anonymous user;
- owner or subject;
- authorized same-tenant role;
- unauthorized same-tenant role;
- authorized role from another department or edition;
- similarly privileged role from another organization;
- expired or revoked delegation;
- access to sensitive fields and exports.

List, count, search, autocomplete, export, audit, and error responses must not
leak the existence or attributes of protected records.

Reusable endpoint matrices assert status/reason stability, absence of protected
markers, and absence of collection metadata on denial. Each module supplies
real principals and records for anonymous, allowed, same-tenant denied,
other-tenant/edition, expired/revoked, field-ceiling, and resource-state cases.
A deliberately unsafe fixture must prove the harness notices both value and
count leaks. Bulk tests additionally mix authorized, denied, cross-tenant, and
unknown identifiers and verify zero partial mutation or effects.

### Workflow tests

End-to-end tests cover the smallest set of critical journeys:

- create account and join an edition;
- register, pay, receive entitlement, and check in;
- apply, onboard, qualify, select, work, and close a shift;
- submit, review, schedule, publish, and revise a programme item;
- create, approve, publish, retry, and audit an announcement;
- receive, assign, respond to, search, and archive a conversation;
- generate and securely download a report;
- close and archive an edition, then view personal history.

The registration-profile workflow matrix additionally covers:

- clearly sourced prior-profile suggestion and independent target snapshots;
- current-edition correction without mutable submission or prior-edition
  history;
- conditional `Other pronouns`, bio length, ISO language membership and the
  five-language maximum;
- fursuit opt-in, zero/multiple/maximum entries, replacement, removal, and
  cross-scope guards;
- new-image pending state, reasoned approve/reject, exact approved-file reuse,
  and cross-account/cross-organization denial;
- anonymous public-list minimization, confirmation and consent gates,
  withdrawal, unapproved-media suppression, and archive/cancellation removal;
- inactive-account and historical-profile mutation denial; and
- parity between the server-rendered reference client and headless
  suggestion/profile/upload contracts.

### UI tests

The attendee and staff clients require:

- component tests for shared patterns;
- keyboard and automated accessibility checks;
- browser tests for critical workflows;
- representative large tables and histories;
- visual regression tests for printable and repeated layouts;
- explicit loading, empty, partial failure, permission-denied, and offline states.

The canonical Organization structure page must also prove one current sidebar
link, no retired React `?view=structure` link, no rendered technical UUID or
email, semantic nested hierarchy, explicit overflow/dependency states, and
desktop plus reliable 390-pixel evidence. Desktop evidence alone does not
satisfy the narrow-viewport gate.

Registration profile UI checks include keyboard-accessible conditional pronouns,
searchable multi-language selection and count feedback, repeatable fursuits,
image status/replacement/removal controls, consent wording, moderation queue
empty/error states, and narrow-viewport overflow.

### Export tests

- CSV and XLSX structural validation;
- formula-injection prevention;
- locale and time-zone correctness;
- PDF rendering and page-level visual review;
- permission and expiry behavior;
- reproducibility metadata.

### Reliability and operations tests

- background-job retry and idempotency;
- external adapter timeouts, rate limits, duplicates, and partial failures;
- backup restoration;
- degraded network and reconciliation;
- real PostgreSQL runtime-role matrices that prove both denied control-plane
  privileges and required data-plane liveness, reject `PUBLIC`/extra function
  execution, persistent/non-origin trigger settings, parameter ACLs, sequence
  update, protected-relation table/column mutation, membership admin options,
  and database/schema/relation/column/sequence/function grant options;
- runtime-login evidence that treats `SET ROLE` and
  `SET SESSION AUTHORIZATION` only as negative impersonation regressions, then
  uses a fresh credential-bound connection to prove all three identities,
  exact policy/projection reads, SELECT-only migration-recorder/marker/latch
  access, and direct mutation denial without logging the credential;
- migration evidence that preserves pre-existing ACLs across reversal, proves
  ordinary audit and trigger-helper writes, rejects orphan or repeated reserved
  activation audits, fingerprints every runtime-executable helper, defeats
  hostile search paths and shadow objects, and refuses owning-module reversal
  after durable activation even without the convergence recorder row;
- Organization structure stopped-writer migration evidence that exercises additive workforce
  `0006`, compatible `legacy_existing` backfill and preflight in `0007`, clean
  empty reversal, populated downgrade refusal, exact command receipts, and
  fail-closed catalog tampering for all 14 helper definitions and 28 trigger
  attachments. Runtime-role tests must also prove those trigger-only helpers
  are not directly executable while ordinary structure commands remain live;
- load tests for registration opening, timetable publication, announcements,
  search, and bulk check-in;
- safe deployment with active jobs and supported database migrations.

The executable
[synthetic OCI runtime rehearsal](../operations/synthetic-oci-runtime-rehearsal.md)
adds the bounded release-environment smoke: digest/source binding, separate
owner and genuine runtime login, least-privilege SQL, absent-role and exact
health fences, stopped-process activation, web/database restart, and no-op
migration/bootstrap replay. Pure unit tests cover its ordering, validation,
redaction, isolation, and evidence contracts; PostgreSQL integration tests
cover the streamed minimal bootstrap's idempotence and collision boundary. A
recorded pass remains synthetic runtime evidence, not backup/PITR or
production approval.

The companion
[synthetic OCI static delivery rehearsal](../operations/synthetic-oci-static-delivery-rehearsal.md)
adds the bounded delivery smoke for the candidate's already-collected bytes: an
image-to-volume manifest equality check, read-only unprivileged edge, exact
static/dynamic routing, MIME and revalidation headers, private same-origin
Swagger/ReDoc sidecars, missing/mutation/media denials, and web/edge restart.
Unit tests protect its immutable-input, configuration, ordering, redaction,
resource-isolation, and evidence contracts. The separate visible browser step
proves one declared styled viewport and request-origin boundary only; it is not
the complete UX-029 responsive, zoom, keyboard, screen-reader, or accessibility
matrix and is not production approval.

## GitHub acceptance topology

[ADR 0090](../architecture/decisions/0090-risk-based-postgresql-acceptance.md)
owns risk-selected PostgreSQL acceptance. Drafts retain cheap locked-input and
Actions-policy feedback and an explicitly non-green `PR gate`. Ready-state
changes run the authoritative exact merge-candidate path; superseded runs are
cancelled. Documentation-only changes avoid PostgreSQL.

| Code change | Required PostgreSQL evidence |
| --- | --- |
| Ordinary source, template or frontend behavior | Every current-schema integration case |
| Domain models or migrations | Current cases, affected owner/dependent historical cases and committed whole-graph recovery |
| Direct historical-test changes | Current cases, the changed historical file and whole-graph recovery |
| Global authorization, identity, audit, runtime settings/readiness, dependencies, workflows, shared test helpers or inventory | Every current and historical case |
| Protected or mass deletion | Exhaustive evidence plus exact current-owner destructive review |

All code paths also run the unit suite, static analysis, NumPy and semantic
docstrings, warning-fatal documentation, Django/OpenAPI/client contracts,
frontend test/type/build validation and security audits. Combined branch-aware
coverage retains the 90-percent threshold, with no new exclusions. Two-decimal
reporting prevents a value such as 89.56 from passing as a rounded whole 90.
PostgreSQL execution uses `coverage run -m scripts.run_postgres_acceptance`
so recording includes Django initialization and graph planning before pytest;
do not nest a second pytest-cov recorder around this already-recorded process.
SQLite never
substitutes for PostgreSQL.

### Explicit membership and grouping

`scripts/ci_historical_tests.json` lists exact top-level historical functions
and migration owners. Everything unlisted remains current behavior, including
current permissions, raw-DML, concurrency and readiness cases in mixed files.
No speed-based or filename-based exclusion is allowed. Unknown files/functions,
owners, duplicate entries and unsafe fixture grouping fail before execution.
When adding a migration test, review its actual executor and recovery behavior
and declare its owners; merely importing a migration does not make a current
guard test historical.

The planner resolves changed nodes and their descendants from Django's actual
migration graph without a database connection. Model-only changes include their
owner's current leaves and dependents. Unknown or deleted schema nodes promote
to exhaustive history. New unrelated behavior tests remain current; actual
affected history additionally requires the committed full-graph recovery case.

Current cases in each file remain serial together. Independently restorable
historical functions can occupy different isolated databases; every
parameterized variant stays with its function. Four shared historical baselines
remain indivisible. The inventory separately reviews the one independently
repeatable module-scoped invitation RSA-key fixture; it is not shared database
state. New broad-scoped fixtures require another explicit grouping review.

Every worker collects the complete integration suite and checks it against the
source inventory before selecting its unique groups. Selection JSON records
actual case IDs. Empty, missing, duplicate, skipped or incompletely executed
required cases cannot pass. The complete partition covers each required group
exactly once. No tests run concurrently in a shared database; real migration
execution, commit visibility, downgrade fences and recovery assertions remain.

### Runtime and cost boundaries

Routine hosted acceptance uses eight shards. Exhaustive hosted acceptance uses
sixteen smaller groups, at most eight running concurrently, with the unchanged
120-minute per-job limit. Local acceptance uses eight isolated PostgreSQL
containers and the same selection/grouping rules. Two hosted waves incur some
additional setup overhead; they give individual jobs headroom, not a promise
that the complete historical suite becomes fast. Matrix fail-fast stays disabled
and blanket retries remain prohibited.

`scripts/ci_test_group_timings.json` contains scheduling estimates, not evidence
of acceptance. The initial estimates sum successful exact-head PR #82 local
JUnit observations for matching current-main groups; they are deliberately
labelled cross-revision estimates. New groups receive the largest known group
cost until measured; stale or invalid entries fail. Do not infer completeness
from timings: collection and executed-case evidence establish it independently.
The old file-level runner/map remain diagnostic tooling, not the PR selection
authority. Record comparable setup, execution and teardown, not only case bodies.

For a reviewed timing refresh, retain the exact receipt and all successful JUnit
reports before another local certification replaces them. Match each report's
file/function (all parameter variants included) through `case_group()` and sum
its JUnit case durations, including setup and teardown, per group. Reconcile
every executed case with the shard selection JSON, rejecting duplicates,
failures, errors, skips, missing or extra cases. Update only groups measured by
that complete scope; current-only evidence cannot replace historical weights.
Document the source revision and scope with the refresh. A timing edit changes
scheduling only and itself requires exhaustive harness acceptance.

### Nightly, release and failure handling

The full-acceptance workflow runs nightly for changed default-branch revisions.
Authenticated read-only run history deduplicates an already successful or active
exact-main run. Earlier failed/cancelled runs cause an actionable red selection
job, not another expensive blind retry. Repair the failure or deliberately
dispatch after inspecting its cause. Nightly failures block release and work
depending on that boundary; they must not become ignored background noise.
Manual dispatch requests full acceptance explicitly. Release publication always
recertifies its exact current-main revision independently of nightly deduplication.

This accepts that an unforeseen historical compatibility interaction may be
found after an ordinary merge, while keeping current safety evidence on every
code PR and exhaustive pre-merge evidence for global safety changes.
Historical-only release testing is not the adopted policy.

### Protected execution and retained evidence

Repository safety precedes expensive fan-out. Protected/mass deletion and
renaming retain the exact fresh owner-applied destructive-review requirement.
Dependency review remains a fail-fast, read-only diff check for graph-visible
manifest/lock/workflow changes; current-tree audits still detect later advisory
knowledge. Unsupported manifests, container images and deferred license policy
are not silently covered by dependency review.

Standard ephemeral hosted runners, immutable Actions/PostgreSQL digests,
read-only contribution tokens and no persistent self-hosted runner remain.
Workflow/classifier changes require the sole maintainer's review; before another
person receives merge authority, add mandatory CODEOWNER review or a separately
reviewed trusted-base policy. Generated frontend output must match tracked and
untracked build results. See [repository governance](../development/repository-governance.md)
for the unchanged trust, destructive-review and supply-chain boundaries.

Unit and integration jobs retain coverage parts, selection JSON and JUnit
diagnostics for seven days. The aggregate gate requires every selected job and
combined coverage. Local unsigned receipts never replace hosted acceptance.
No duplicate application acceptance runs on the identical-tree squash push.
CodeQL remains independent, with its documented fork/Dependabot limitations.
Pages publication builds documentation only and adds no application acceptance
or PR publication authority. CI is not deployment, production restore/PITR,
runtime-credential or production-readiness evidence.

### Next GitHub testing layers

The next expansion should add:

- a small pull-request Playwright matrix for platform administrator, Board or
  Department authority, attendee, and denial journeys at 390 and 1,280 CSS
  pixels, including keyboard completion and automated accessibility;
- nightly Python 3.12/3.13/3.14 unit and contract compatibility, migration-
  from-zero, concurrency repetition, randomized-order seed capture, and the
  broader responsive/visual-state matrix;
- monitor and tune the enabled GitHub-managed CodeQL default setup and merged
  dependency-review control, and verify secret-scanning/push-protection alert
  handling;
  and
- synthetic previous-version restoration and production-shaped recovery,
  target edge/TLS/WAF, provider, and worker-supervision rehearsals. The bounded
  runtime and static-delivery evaluators supply exact-candidate synthetic
  evidence; the existing release workflow separately supplies full source
  certification, an immutable OCI image, SBOM/provenance attestations, and
  signed-by-checksum evidence assets.

Automated accessibility is supplementary evidence. Representative keyboard,
screen-reader, owner, restore/PITR, and production-governance acceptance remain
human or production-shaped release gates.

## Test data

- Use synthetic factories with realistic distributions and edition sizes.
- Maintain a deterministic reference convention containing multiple editions,
  tenants, roles, languages, time zones, products, shifts, and conflicts.
- Never copy production personal data into development or CI.
- Include adversarial strings, Unicode, long histories, and daylight-saving
  boundaries.

## Quality gates

A change cannot merge when:

- required checks fail;
- a changed requirement lacks corresponding tests;
- authorization or tenant-boundary tests are missing;
- OpenAPI changes are unexplained;
- migrations are untested;
- generated artifacts or documentation are stale;
- a critical defect is hidden behind a blanket skip or retry.

High-risk modules should use mutation testing selectively to demonstrate that
tests detect altered authorization, pricing, entitlement, and scheduling rules.

## Traceability

Test names or metadata should reference requirement identifiers where useful.
Release notes link implemented requirements, ADRs, migrations, and operational
considerations.
