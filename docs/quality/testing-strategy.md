# Testing strategy

Status: Active
Last updated: 2026-08-02

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
- load tests for registration opening, timetable publication, announcements,
  search, and bulk check-in;
- safe deployment with active jobs and supported database migrations.

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
