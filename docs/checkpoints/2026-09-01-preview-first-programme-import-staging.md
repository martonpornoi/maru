# Checkpoint: Preview-first Programme import staging

- Date: 2026-09-01
- Issue: [#66](https://github.com/martonpornoi/maru/issues/66)
- Parent umbrella: [#48](https://github.com/martonpornoi/maru/issues/48)
- Phase: Progressive adoption and pre-production release evaluation
- Related requirements: IDN-014, PRG-001, PRG-002, PRG-006, PRG-009,
  PRG-010, AUD-001, AUD-003, AUD-005, PRI-001, UX-005 through UX-008,
  UX-019, UX-020, UX-027, UX-029, NFR-002, NFR-003, NFR-008 through
  NFR-010, and NFR-013
- Related decision: ADR 0083

## Outcome

Maru has a dormant Applications-owned, preview-first service kernel for
importing Programme calls and proposals from one deterministic incumbent-system
package. Staging validates and persists temporary private evidence without
creating a call, proposal, collaborator, host, occurrence, Shift, schedule, or
publication. Organizer preview exposes only opaque identifiers and closed
operational facts.

An organizer may adopt a ready call result only through the protected complete-
Draft call command. A staged proposal remains blocked until its imported call
is permanently bound and independently active. Its exact lead may then preview
only their own selection and normalized typed answers and explicitly claim the
proposal through the protected proposal/answer command chain. Successful apply
clears the item's private payload; explicit continuity disposal clears every
remaining staged payload without deleting applied domain state.

This does not make Programme import usable in a current edition. Neither
current profile pins the import adapter, capabilities, event, writer, target,
or self-service path. There is no page, upload, API/OpenAPI operation, route,
template, navigation destination, worker, cleanup schedule, external effect,
service actor, retention approval, or production-data authorization.

## Decisions

- The source is strict UTF-8 JSON schema version one, capped at 8 MiB, 1,000
  items, depth 16, 250,000 parsed values, 32 object members, 1,000 generic array
  elements, and 65,536 Unicode scalar values per generic string before narrower
  Programme limits.
- Parser diagnostics contain only fixed codes and safe schema locations.
  Reloaded at-rest evidence corruption is an internal dependency failure and
  becomes a correlation-only operation error, not a second parser surface.
- Proposal answers use the exact closed
  `question_key`/`field_type`/`value` shape. The declared type must equal the
  resolved call question type before any proposal mutation.
- Import adoption is independent from target/self adoption. The import pin can
  admit staging, organizer preview, retry, and continuity disposal; protected
  call/proposal apply and lead paths recheck their own purpose-specific gates.
- Organizer staging/preview requires a current Department and open private-
  planning writes. Lead-self preview is a sensitive read that remains available
  after planning closure while unexpired and authorized; claim still requires
  open writes. Disposal requires exact-Edition continuity authority but no
  current Department or open writes.
- Lead identity is resolved from the exact staged login email for every fresh
  preview and fresh claim, never persisted, and rechecked under locks. Retained
  receipt replay rechecks current adoption-scoped retry authority and releases
  only the minimized historical result.
- The lead supplies their own contributor profile, proposed-public choice, and
  consent. The import never asserts those facts on their behalf.
- Organizer preview never includes proposal values, lead email, identity-match
  state, source keys, digests, target identifiers, or permanent source-binding
  identifiers. Lead preview returns only its caller-supplied opaque item ID,
  current version, selection, typed answers, and fresh adoption digest.
- Source identity is permanent. Same source identity plus the applied digest is
  a no-op forever; a changed digest is a conflict forever. A no-op retains its
  private duplicate until explicit disposal.
- Call/proposal apply prelocks deterministic nested retry keys before import or
  edition rows. Each outer import command links one exact contiguous ADR 0082
  receipt chain. Any nested/evidence failure rolls the complete mutation back.
- Retention comes only from reviewed, versioned deployment configuration with
  no default lifetime. A substitute provider requires both an explicit test
  setting and an auto-created `test_` database.

## Changed areas

- Seven Applications models for batch/item staging, immutable preview results,
  permanent source binding, nested command links, and import receipts.
- Strict package parser, typed inputs, retention provider, authorization
  boundaries, writer latch, event schema, command services, safe projections,
  and shared retry namespace.
- Applications `0007` through `0009`, Authorization `0022`, and Workforce
  `0017`, including exact PostgreSQL guards, populated downgrade fence,
  readiness fingerprints, and runtime-role provisioning.
- Product requirement PRG-010, ADR 0083, Applications/security/operations
  documentation, deployment/recovery runbook, page non-surface contract, and
  current handoff.

## Verification

Candidate verification completed so far:

- Targeted Ruff formatting/lint and strict mypy pass for the changed Python
  boundary. A fresh warning-fatal Sphinx and AutoAPI build passes, as do
  `git diff --check` and Django migration-drift checking.
- The focused parser, authority, retention, persistence, migration-contract,
  and answer-normalization unit slice passes all 226 tests; the complete unit
  suite passes all 2,734 tests.
- Twenty-six PostgreSQL service and raw-integrity tests pass. Fresh-database
  runs prove the complete call/proposal lifecycle, exact source/Department/
  definition lineage, sealed nested-command counts and order, and database
  rejection of forged attribution or truncated evidence. Dedicated cases also
  prove re-resolution when lead identity changes after preview, serialization
  of concurrent same-source application, staged-only scrubbing after partial
  application, and exact-Edition disposal after owner Department retirement.
- The dedicated migration executor passes seven tests in 184.99 seconds,
  including all seven independently populated relation fences, empty
  reverse/reapply, both retained-authority fences, the lower schema preflight,
  and Workforce contract reversal. The historical integrity-function ACL
  reversal/reapply case passes separately in 204.86 seconds. Applications
  readiness passes all 48 focused cases against the fresh 33-relation catalog.
- Repository documentation policy validates all 374 Markdown files, four
  repository skills, and 214 unique requirement identifiers. Django reports
  no migration drift and only the expected local `identity.W001` warning.
- Independent contract and security reviews found no blocking mismatch after
  lifecycle, modular-adoption, result-projection, retention-provider, stored-
  evidence, retry-lock, and failure-disclosure repairs.
- The first complete non-database repository-gate attempt built and verified
  the package and restored locked frontend dependencies, then stopped at the
  live dependency audit: locked `djangorestframework==3.17.1` is now affected
  by CVE-2026-73228 and CVE-2026-73229. Issue #67 and PR #68 subsequently
  delivered the bounded 3.17.2 repair to `main`, and this candidate is now
  rebased onto that repaired mainline.
- After rebase, the complete current-tree non-database repository gate passes,
  including both dependency audits with no known vulnerabilities, package and
  locked-input verification, static analysis, documentation policy, warning-
  fatal Sphinx/AutoAPI, migration drift, Django/contracts, and 33 frontend
  tests.
- Exact clean-tree certification of rebased head
  `88dbb770dd4b2d1b371c668af126e79c4898aaf9` passed all 2,735 unit tests,
  all 2,861 PostgreSQL integration tests across eight isolated PostgreSQL 17
  instances, every repository gate, and combined 90-percent branch coverage.
- PR #69's first hosted run passed every non-database job and seven PostgreSQL
  shards. Shard 5 reached 98 percent and continued issuing database work with
  no assertion failure until the 120-minute job fail-stop cancelled it;
  the slowest completed peer took 112 minutes. Exact-head JUnit evidence showed
  that shard 5 actually needed 5,690.7 local seconds despite its 4,551.6-second
  projection. Refreshing all 178 file weights balances the deterministic
  schedule between 5,217.370 and 5,217.442 seconds while preserving the 120-minute
  fail-stop, all eight serialized whole-file shards, no retries, and combined
  coverage.

Final clean-tree certification and protected exact-head evidence are recorded on
the candidate's pull-request record before merge. A focused or hosted check
never activates the dormant adapter.

## Data, migration, and deployment notes

- Applications `0007` creates additive empty schema. `0008` installs exact
  scope, state, attribution, append-only, receipt-backed, chain-completeness,
  retry-collision, writer-latch, and truncate protections. `0009` refuses
  populated downgrade.
- Authorization `0022` adds closed capability vocabulary and no grant.
  Workforce `0017` recognizes the exact staging owner foreign key for deletion
  safety but does not implement retirement preflight or recovery.
- The production runtime role receives SELECT only on the seven import tables
  and no direct integrity-function execution or mutation privilege.
- Reversal is safe only while the evidence relations are empty. Populated
  rollback is fix-forward or a mutually consistent whole-database restore,
  including Applications, Authorization, Workforce, Audit, Effects, and
  migration history from one point.
- A reviewed deployment setting supplies policy code, approval reference/time,
  and a lifetime from one second through one year. Configuration alone neither
  adopts the adapter nor authorizes production personal data.

## Known risks and incomplete work

- The adapter and services are intentionally dormant and have no user-facing
  acceptance, production retention approval, cleanup worker, restore rehearsal,
  representative accessibility evidence, load evidence, or owner acceptance.
- The dependency-security blocker is resolved by issue #67 and PR #68. The
  candidate still requires authoritative protected evidence for its final exact
  head before merge.
- Department retirement still needs disclosure-safe preflight plus governed
  reassignment/disposal. Issue #64 owns that prerequisite.
- The staged package is not an Applications review or decision and cannot
  manufacture a seal, acknowledgement, accepted Programme item, host, public
  copy, occurrence, Shift, release, or publication.
- Structured review/decisions, the Applications-to-Programme acceptance
  adapter, interactive Scheduling, staffing, release, projections, offline
  continuity, profile activation, and integrated browser/recovery acceptance
  remain later umbrella children.

## Recommended next actions

1. Complete issue #64's Department retirement coordination, including exact
   unresolved-staging preflight and governed reassignment/disposal recovery.
2. Add Programme-specific review, recusal/conflict, revision-request,
   wait-list/reject/accept decisions, and the exact accepted-revision contract.
3. Implement the protected Applications-to-Programme adapter and only then
   create Programme-owned items and host/co-host relationships.
4. Continue through Scheduling, accessible timetable editing, Workforce
   staffing, atomic release/projections, and on-site continuity in umbrella
   order before profile activation.
