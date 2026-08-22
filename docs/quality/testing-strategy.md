# Testing strategy

Status: Active
Last updated: 2026-08-22

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

Page 9 structure contract tests additionally require recursive OpenAPI and
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
- Page 9 stopped-writer migration evidence that exercises additive workforce
  `0006`, compatible `legacy_existing` backfill and preflight in `0007`, clean
  empty reversal, populated downgrade refusal, exact command receipts, and
  fail-closed catalog tampering for all 14 helper definitions and 28 trigger
  attachments. Runtime-role tests must also prove those trigger-only helpers
  are not directly executable while ordinary structure commands remain live;
- load tests for registration opening, timetable publication, announcements,
  search, and bulk check-in;
- safe deployment with active jobs and supported database migrations.

## GitHub acceptance topology

Draft pull requests classify the submitted diff and validate only the locked
Python inputs and exact Actions policy. Their stable `PR gate` remains
explicitly non-green until the author selects **Ready for review**. That event,
plus ready-state opens, synchronizations, and reopenings, starts authoritative
acceptance. Converting a pull request back to draft cancels obsolete work and
restores the non-green draft result. Superseded runs are cancelled and one
stable `PR gate` remains the branch-protection target:

- documentation-only changes run static and warning-fatal documentation checks
  without PostgreSQL;
- ordinary Python changes run static/contracts/documentation, unit tests, and a
  PostgreSQL selection consisting of directly changed tests, tests named for or
  importing affected modules, and critical API/readiness smoke. The classifier
  promotes a missing, unmeasurable, or greater-than-30-minute selection to full
  acceptance instead of letting the targeted lane exceed its 45-minute limit;
- frontend and dependency work adds only the relevant generated-contract,
  build, and advisory checks. A ready graph-visible manifest, lock, or workflow
  diff first runs the pinned dependency-review Action inside `changes`, failing
  on an introduced moderate-or-higher vulnerability in runtime, development,
  or unknown scope before fan-out. `Dockerfile` keeps broader security routing
  but does not select this graph comparison. Checked-in Staff Console output is
  classified as frontend work,
  while Django templates and non-Staff-Console static assets are classified
  with their owning Python module. Every non-full quality run also executes the
  distribution-license and release-metadata contracts. When the diff changes
  root package metadata/legal files, frontend source, or `src/maru`, it also
  builds and inspects a wheel and source archive against every current Django
  template/static asset and both PEP 639 legal files. A root legal-file-only
  change therefore cannot bypass packaging evidence; and
- migrations, models, settings, locks, security/authority boundaries,
  cross-cutting top-level Django templates/static, workflows, test
  configuration, and CI harnesses fail closed to reusable full acceptance.

Deleting 25 or more paths, or deleting or renaming protected source, tests,
repository automation, governance records, or critical root policy/deployment
files requires `destructive-change-reviewed` and full acceptance. Under the
current sole-maintainer policy, only the repository owner's exact label-
application event for the current head conveys approval; every other pull-
request action treats an existing label as stale. A trusted, no-checkout
`pull_request_target` control removes the
stale UI label after head, readiness, draft, or reopen transitions, without
relying on its token-generated event to retrigger acceptance. The maintainer
must review the new scope before reapplying it. Repository safety passes before
selected work can fan out, and a
targeted selection that unexpectedly contains no tests fails instead of
silently passing.

This routing is a reviewed repository policy, not an independent server-side
classifier. A pull request can modify its candidate workflow and classifier, so
the present sole-maintainer model assumes that the only person with write and
merge authority reviews such changes. Before granting that authority to another
person, enable stale-dismissing approval and CODEOWNER review or introduce a
separately designed trusted-base policy check.

Both frontend paths reject tracked diffs and untracked files after rebuilding
the checked-in Staff Console output, so a newly emitted chunk or legal asset
cannot disappear from the submitted change.

Reusable full acceptance runs static analysis, strict NumPy documentation,
Django/OpenAPI/client contracts, Staff Console acceptance, dependency audits,
the unit suite, and every integration file. Static analysis, documentation,
contracts/frontend, and security run concurrently so one late category does
not delay the others or obscure its failure. It distributes integration files
across eight isolated PostgreSQL jobs; files remain whole and serialized within
a job. The checked-in timing map sums file-level JUnit durations from an
accepted run and gives new files a deterministic median fallback. The selector
validates non-empty unique assignment and uses deterministic path/index
tie-breaks. Static checks, including the focused distribution-license
contracts, and dependency security must pass before unit or integration work
starts, so an early policy or advisory failure does not spend database runner-
minutes.

The dependency-diff step and current-tree audits prove different things. The
former can reject a newly introduced vulnerable dependency before installation;
the latter can catch an unchanged lock entry after advisory knowledge changes.
The 2026-08-21 live graph contained 293 packages across PyPI, npm, GitHub
Actions, and the root repository document, and read-only comparisons recognized
Maru's uv, pnpm, project, and workflow inputs. Neither result covers an
unsupported or unparseable manifest or the `Dockerfile` base image. Automated
license enforcement remains deferred, and OpenSSF Scorecard output and
pull-request comments remain disabled.

The unit suite is explicitly non-database; its only former PostgreSQL receipt
test now belongs to integration. Unit and integration jobs publish hidden
coverage parts and JUnit diagnostics for seven days. One job combines them and
enforces branch-aware 90-percent coverage. Accepted main-run timings balance
seven shards near 2,505 weighted seconds and the indivisible longest shard near
2,760 seconds. Matrix fail-fast is disabled, blanket retries are forbidden, and
external actions plus PostgreSQL and container bases are pinned to reviewed
immutable digests. `Full CI gate` certifies high-risk pull requests, manual
runs, and releases. Merge-queue support remains disabled until that event emits
the same required `PR gate`.

Since the 2026-08-20 public transition, every repository workflow uses standard
GitHub-hosted runners and the repository has no registered self-hosted runner.
Actions are limited to the exact immutable revisions in
`.github/actions-allowlist.json`, workflow tokens default to read-only, and
fork pull requests receive no publishing or environment authority. GitHub may
hold eligible contribution-code `pull_request` runs from a first-time fork
contributor until a maintainer approves execution. That starts isolated read-
only execution and is not approval of the pull request. The base-branch metadata
cleanup remains no-checkout trusted automation and is not subject to that fork-
code approval. Contributors still run `scripts/certify.ps1`
before review for complete local feedback, but the unsigned local receipt never
substitutes for GitHub's current merge-candidate result.
The pull-request workflow does not repeat acceptance on the identical-tree
squash push to `main`; managed CodeQL still owns its default-branch scan, and
release publication recertifies the exact current `main` commit.

GitHub Pages publication is not another full acceptance path. After a protected
pull request merges, its dedicated workflow rebuilds only the already-accepted
documentation surface from protected `main`, with point-in-time current-main
checks immediately before build and deployment: locked-input and Action-policy
preflight, PyDocLint, semantic docstring validation, maintained Markdown
validation, and warning-fatal Sphinx/AutoAPI. It starts no PostgreSQL service
and runs no application test matrix. A read-only build job produces one fresh
generated-HTML artifact; a separate `github-pages` job with only Pages write and
OIDC authority deploys it. Pull requests and non-main manual dispatches cannot
publish. First-deployment evidence additionally exercises one Mermaid page in a
real browser against its exact accepted script origins; that external behavior
is not inferred from a successful static build.

Managed CodeQL default setup does not analyze fork pull requests, and its native
merge protection does not cover Dependabot pull requests. `PR gate` remains the
required merge result for those changes; default-branch and weekly CodeQL scans
retain post-merge coverage. A cross-repository fork contribution still needs a
documented rehearsal before Maru calls that path fully proven.

The ephemeral Actions databases prove migrations, constraints, authorization,
and transactional behavior; they are not production restore/PITR or runtime-
credential evidence.

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
- synthetic previous-version restoration, production-shaped recovery rehearsal,
  and container runtime smoke in the release environment. The existing release
  workflow already supplies full source certification, an immutable OCI image,
  SBOM/provenance attestations, and signed-by-checksum evidence assets.

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
