# Current project state

Last updated: 2026-08-31
Phase: Progressive adoption and pre-production release evaluation.

Maru is an actively developed Django/PostgreSQL modular monolith. It is not a
supported hosted service, a production-ready release, or approved for
production personal data. The detailed capability inventory remains in the
[production-consolidation ledger](PRODUCTION_CONSOLIDATION.md); this file is the
concise handoff.

## Umbrella issue intake contract

Maru's checked-in issue intake now distinguishes one closable feature proposal
from one bounded end-to-end outcome that requires multiple child issues. The
new **Umbrella proposal** form records current boundaries, roles and states,
the complete journey, progressive adoption and side effects, ordered child
outcomes, integrated acceptance, non-goals, traceability, safety, recovery,
risks, and alternatives. It is planning evidence, not implementation authority.

Every child must use GitHub's native sub-issue relationship, cite the exact
umbrella checklist item and acceptance criteria it owns, state dependencies,
and preserve inherited non-goals. The native hierarchy records membership and
progress; the umbrella body remains the scope and dependency contract and
stays open through final integrated acceptance. Existing bug and feature
routes, private security reporting, support, and exploratory Discussions are
unchanged, and no new label or Project is introduced.

The issue-form schema and complete expected field/label set are repository-
tested. Contributor, repository-governance, operations, changelog, and
checkpoint documentation agree. This extends ADRs 0060 and 0068 under NFR-002,
NFR-003, and NFR-011 without a Django model, migration, API, runtime role,
production-data flow, live repository-setting mutation, or new ADR. All 20
focused tests, repository documentation validation, Ruff lint and formatting,
`git diff --check`, and a fresh warning-fatal Sphinx and AutoAPI build pass;
independent re-review found no remaining actionable issue. Exact-commit
certification and protected pull-request acceptance are evaluated as separate
delivery evidence; the form does not become part of the default-branch issue
chooser until protected merge.

## Profile-aware Position-assignment evidence contract

Issue [#41](https://github.com/martonpornoi/maru/issues/41), a bounded finding
from the first release-candidate evaluation
[#29](https://github.com/martonpornoi/maru/issues/29), now has one consistent
current contract. Position-assignment proposal remains side-effect free in
every profile. Approval always activates the scoped RoleAssignment, but
Participation evidence follows the immutable edition profile:
`full_convention@1` requires configured capacity evidence and a non-null
assignment pointer, while `workforce_only@1` creates no `Participation` or
`ParticipationCapacity` and requires that pointer to remain null.

Ending always revokes the linked authority and retains assignment history. It
completes only no-longer-needed full-convention capacities; Workforce-only
ending touches no Participation evidence and preserves the null pointer. The
opposite pointer shape in either profile is an integrity conflict requiring
stopped writes plus fix-forward or mutually consistent whole-database recovery,
not manufactured Workforce-only Participation or discarded full-convention
evidence.

ADR 0080 now explicitly partially supersedes ADR 0076 only where the older
decision made Participation activation and completion unconditional. ADR
0076's relationship-bounded proposal, dual control, role authority, headcount,
onboarding, retained ending, audit, and recovery boundaries remain accepted.
Requirements, roadmap, domain and workflow summaries, Assignment page
contract, Workforce module, Workforce-only runbook, ADR catalogs, and release
notes now agree. The
[profile-aware contract checkpoint](../checkpoints/2026-08-30-profile-aware-position-assignment-contracts.md)
preserves the correction without rewriting the historical Assignment
checkpoint.

All 18 documentation-policy tests pass. The existing full-convention and
Workforce-only PostgreSQL assignment journeys pass through approval and ending;
the full-convention case now also proves the database rejects clearing its
required pointer. No runtime implementation, model, schema, migration, API,
permission, or browser behavior changed. The protected pull-request gate
remains authoritative for the final exact head, and issue
[#42](https://github.com/martonpornoi/maru/issues/42) is the next bounded
candidate-evaluation finding.

## Reproducible release-consumer supply-chain verification

Issue [#40](https://github.com/martonpornoi/maru/issues/40) now has one
parameterized, fail-closed consumer verifier whose protected pull-request gate
remains authoritative. Independent repository, tag, source-commit, mutable
image-tag, and immutable-digest inputs drive the complete Release API,
Release-attestation, per-asset attestation, checksum, manifest, public Git tag,
actual merged release PR, OCI tag, digest-bound SPDX, and strict provenance
sequence. The CalVer tag independently supplies the expected release PR,
channel, candidate number, version, image tag, title, and prerelease state.

The verifier requires GitHub CLI 2.96.0 or later, a preauthenticated session,
Git, and Docker Buildx `imagetools`. It creates a new local directory, requires
the exact eight regular assets, verifies `SHA256SUMS` before trusting its exact
seven-payload inventory, reads the immutable Release again after asset
verification, and never executes or extracts downloaded content. It does not
log in, expose or persist a token, log or persist subprocess output or the
environment, or mutate a Release, tag, asset, image, attestation, repository
setting, or deployment. All networked GitHub CLI reads are pinned to
`github.com`; link, junction, and reparse components are rejected; and mutable
image plus local asset identities are rechecked immediately before success.

The live candidate path passed for tag `v2026.08.27-rc.1`, source `be0b21d`,
and OCI index digest `sha256:a44de03a4fe7bd5b3a5aaf73dd83b565b727a98bf895bf80416981e869eeb445`.
All eight assets and seven checksum payloads matched; manifest, actual merged
PR #27, and public tag/image relationships matched; the digest-bound SPDX 2.3
document contained 179 uniquely identified packages and the recorded
Syft/BuildKit generators; and one exact SLSA v1 result bound Maru's Release
workflow, `refs/heads/main`, exact source, and a GitHub-hosted runner while
denying self-hosted runners.

Focused release-consumer and producer-evidence coverage passes all 99 cases.
Whole-tree Ruff, full PyDocLint, the semantic docstring validator across 387
source files, strict mypy for the new verifier, documentation policy across 358
Markdown files and 207 requirement identifiers, and a fresh warning-fatal
Sphinx/AutoAPI build pass. The protected hosted gate remains the merge
authority for the final exact pull-request head.

The first live attempt failed safely when Windows decoded Docker's UTF-8 SBOM
as CP1252. Explicit UTF-8 decoding then passed from a fresh directory, leaving
the first partial directory local as designed. A final hardened fresh-directory
run also passed host-pinned PR reconciliation, UTC CalVer validation, unique
SPDX package identity, and end-of-run asset and mutable-image rechecks. The
[release-consumer checkpoint](../checkpoints/2026-08-30-release-consumer-supply-chain-verification.md)
also supersedes only the earlier #29 checkpoint's 62-character transcription
of the `SHA256SUMS` asset digest with GitHub's verified 64-character value; the
append-only historical file is unchanged.

No Django module, model, migration, API, browser behavior, permission,
runtime-role boundary, release publication, or new ADR is involved. This
implements NFR-002, NFR-003, NFR-011, and NFR-012 under ADRs 0060 and 0065. It
is bounded supply-chain evidence, not gold promotion, deployment, recovery,
accessibility, owner acceptance, or production readiness. Issue #41's
profile-aware contract correction is recorded above; issue
[#42](https://github.com/martonpornoi/maru/issues/42) follows it.

## Assignment controlling-authority interval recovery

Issue [#39](https://github.com/martonpornoi/maru/issues/39) now has a focused
implementation whose protected pull-request gate remains authoritative. A new
Position assignment proposal proves, after exact retry replay resolution and
before persistence or headcount reservation, that one exact current proposer
control source covers its complete interval. Equal
boundaries are accepted; a bounded source cannot cover an unbounded proposal.

Approval rechecks the original proposer and current independent approver under
the existing transaction and assignment locks. A failed horizon recheck leaves
the immutable proposal, version, and truthful headcount reservation intact and
retains no access, RoleAssignment, Participation, or successful mutation
evidence. HTML presents an action-local recovery message and the API returns a
typed, non-disclosing `409`; neither reveals controller identities, source or
grant identifiers, source timestamps, or raw provenance. Recovery is to reload,
reject the proposal, and create a new one within current authority, never edit,
backfill, or silently rebind it.

A synthetic browser rehearsal passed at 1,280 by 900 and 390 by 844 CSS pixels.
The conflict summary received focus as an alert; each rendering retained one H1
and one `main`, no duplicate IDs, and no horizontal overflow. Approval was
disabled after the conflict while reload and a fresh rejection action remained
available. Rejection retained version 2 and directly inspectable
history, and both journeys produced zero console warnings or errors.

Focused local acceptance passed all 38 Authorization command tests and all 20
Workforce assignment command tests. Repository-wide Ruff, mypy, PyDocLint, and
Python docstring validation passed; warning-fatal Sphinx rendered 357 Markdown
files; all 29 Staff Console tests plus its typecheck and build passed; and
OpenAPI validation and checked-in TypeScript regeneration were deterministic.
Migration detection reported no changes. The local system check retained only
the expected fail-closed invitation-encryption warning.

No model, migration, runtime-role boundary, or new ADR is required; the change
implements IDN-005 and HR-013 under ADRs 0044, 0076, and 0080. The rehearsal is
bounded implementation evidence, not full UX-029 coverage, two-human owner
acceptance, protected-branch certification, deployment, or production
approval. The
[assignment interval checkpoint](../checkpoints/2026-08-30-assignment-authority-interval-recovery.md)
records the recovery and disclosure contract. Issue #40 now owns the separate
consumer-verification outcome recorded above.

## Synthetic OCI static-delivery rehearsal

Issue [#38](https://github.com/martonpornoi/maru/issues/38) now has one
canonical deployment-shaped evaluator for immutable candidate
`v2026.08.27-rc.1`, exact source `be0b21d`, and application OCI digest
`sha256:a44de03a4fe7bd5b3a5aaf73dd83b565b727a98bf895bf80416981e869eeb445`.
It composes the unchanged candidate with a reviewed digest-pinned unprivileged
reference edge, an exact read-only collected-static volume, internal Gunicorn
and PostgreSQL, loopback-only publication, hardened containers, private API
documentation, restart boundaries, sanitized receipts, and exact-label
cleanup.

Final automated run `c38e0c7d2f93` passed all 12 stages on 2026-08-30. The
image and volume matched at 196 regular files, 14,846,309 bytes, and manifest
SHA-256 `4c8c346b`. Five landing assets, two manifest icons, 12 raw static and
nine raw media namespace-escape probes, MIME/cache/mutation/missing-path
boundaries, same-origin Swagger/ReDoc, OpenAPI 3.1, runtime hardening, and
Gunicorn/edge restarts passed. The run removed its exact resources and an
independent label-filtered readback found none.

Retained run `d38e0c7d2f94` then passed the same exact configuration and a
1,440 by 900 browser rehearsal. The landing applied the Maru brand with no
overflow; Swagger and ReDoc visibly rendered; each UI loaded its schema and
sidecars from the exact edge origin; ReDoc made no `cdn.redoc.ly` request; and
all three pages produced zero console warnings or errors. The authenticated tab
was closed, the edge, web, and database were stopped in that order, exact-run
cleanup succeeded, and zero containers, networks, and volumes remained.

The immutable ReDoc bundle contains a remote attribution-logo URL. The bounded
edge serves one deterministic representation that replaces only that URL with
an inert `data:` image while leaving candidate and volume bytes unchanged and
retaining visible attribution. Conditional, range, validator, and same-origin
tests protect that narrow compatibility boundary. The
[static-delivery runbook](../operations/synthetic-oci-static-delivery-rehearsal.md)
and [checkpoint](../checkpoints/2026-08-30-synthetic-oci-static-delivery-rehearsal.md)
record the exact contract and correct the earlier server-HTML-only inference.

No new ADR was needed: this bounded evaluator implements ADRs 0021, 0056,
0060, and 0065 without selecting production infrastructure. Passing it does
not certify a target edge/TLS/WAF/provider, edge-image advisories, production
settings, workers, telemetry, load, restore/PITR, full UX-029 accessibility,
policy, or human go/no-go.

## Synthetic OCI runtime rehearsal

Issue [#37](https://github.com/martonpornoi/maru/issues/37) now has one
executable public evaluator path for immutable candidate `v2026.08.27-rc.1`,
exact source `be0b21d`, and OCI digest
`sha256:a44de03a4fe7bd5b3a5aaf73dd83b565b727a98bf895bf80416981e869eeb445`.
The runner binds the image to exact-source runtime-role SQL, uses the currently
reviewed digest-pinned PostgreSQL 17.11 image, and creates an internal,
no-host-port synthetic network with separate cluster-administrator,
migration-owner, and genuine runtime-login credentials.

The full live rehearsal passed all 16 ordered stages on 2026-08-29. It applied
170 migrations, reproduced the absent-role Logistics `503`, reached
compatibility readiness `200` through the genuine runtime login, proved the
exact preactivation `503`, activated exact provenance with zero application
processes and zero blockers, then returned exact-mode readiness `200`. Web-only
and database-plus-web restarts retained the same build and governed state.
Migration replay was a no-op, the non-login synthetic bootstrap returned
`already_present`, and aggregate state remained one account, one activation
marker, and one reserved activation audit. The sanitized local receipt reported
successful label-verified cleanup with no remaining rehearsal resources.

The canonical procedure is the
[synthetic OCI runtime runbook](../operations/synthetic-oci-runtime-rehearsal.md).
It deliberately excludes the comprehensive educational demo fixture, which
contains ordinary authority examples that are not exact issuance history.
Unit and PostgreSQL integration coverage protect digest/source binding,
ordering, redaction, isolation, health interpretation, idempotence, collision
failure, and the non-login bootstrap. No new ADR was needed: this is bounded
evaluator tooling that implements accepted ADRs 0044, 0046, 0060, and 0065; it
does not select production infrastructure.

Passing the runtime rehearsal means its bounded synthetic topology is fully
ready. The separate issue #38 evaluator now owns static/edge evidence; neither
path certifies providers, workers, restore/PITR, load, accessibility,
production policy, or human go/no-go. Issue #39 owns the focused Assignment
repair; issue #40 owns the consumer-integrity evidence recorded above; issue
#41 owns the profile-aware contract correction above; and issue
[#42](https://github.com/martonpornoi/maru/issues/42) follows them.

## First release-candidate synthetic evaluation

Issue [#29](https://github.com/martonpornoi/maru/issues/29) completed the first
public-consumer and synthetic operator evaluation of immutable candidate
`v2026.08.27-rc.1`, exact source `be0b21d`, and OCI digest
`sha256:a44de03a4fe7bd5b3a5aaf73dd83b565b727a98bf895bf80416981e869eeb445`.

Fourteen recorded areas passed, two failed, none were blocked, and two broad
acceptance areas were deferred. Supply-chain integrity, fresh PostgreSQL 17
migration, liveness, the complete semantic Workforce-only journey, exact-edition
state isolation, and ordinary stop/restart persistence passed. Readiness failed
closed because the bounded local runtime had no named runtime database role;
the default Gunicorn topology also returned 404 for collected static assets.

The candidate remains immutable pre-production evidence, not a gold or
production-ready release. Issues #37 and #38 now supply the missing runtime and
static-delivery paths; issue #39 owns the focused Assignment recovery, issue
#40 owns reproducible consumer verification, and issue #41 owns profile-aware
assignment contracts. Issue
[#42](https://github.com/martonpornoi/maru/issues/42) retains the next finding
by remediation boundary. The complete evaluation evidence, exact
counts, and disposition are in the
[synthetic operator evaluation checkpoint](../checkpoints/2026-08-29-first-release-candidate-synthetic-operator-evaluation.md).

## Workforce-only protected-main outcome

Protected `main` now makes Workforce-only use an executable product profile
rather than a navigation promise.

- Every edition has an immutable, versioned adoption profile. Existing
  editions remain `full_convention@1`; the new bounded option is
  `workforce_only@1`.
- **Set up Workforce** creates or reuses only the minimum Organization,
  Convention series, and Event edition foundation. It asks for names, dates,
  and time zone, applies internal `en`/`XXX` defaults, and records one atomic,
  idempotent setup receipt.
- A new organization may use two truthful **Maru operators** instead of
  inventing an Executive Board. Invitation, self-acceptance, independent
  activation, provenance, recovery, and audit controls remain two-person and
  inspectable. Existing Board organizations and evidence are unchanged.
- Adoption is checked before platform policy, grants, or roles. Registration,
  payments, attendee Participation, attendance, unrelated access groups,
  public Registration discovery, and unrelated menu destinations are absent
  from a Workforce-only edition.
- Ordinary Workforce authority still requires exact edition scope. The
  canonical Maru-operator root is a database-guarded exception and applies only
  to Workforce-only editions, so a later full-convention edition grants no
  implicit operator access.
- Position assignment activation and ending now use profile-matched evidence:
  full-convention editions retain Participation capacities, while
  Workforce-only assignments never create Participation.
- A fresh Workforce-only organization can create one safe Volunteer Position
  template after its first Department. A different accountable operator must
  approve the minimal role meaning; the action grants nobody access and creates
  no Position, person relationship, Participation, or Registration.
- The Django management shell and Staff Console expose the profile and focus on
  Structure, Positions, Assignments, Availability, and Shifts. Specialist
  records require an explicit disclosure instead of dominating the landing
  page.
- Exact-edition links select and focus their routed workspace even without
  saved session context. Public volunteer pages use Volunteer navigation, and
  personal Workforce pages retain only purpose-matched My Maru and My
  Workforce destinations.

ADR 0080 records the durable profile, accountability, authority, coexistence,
and recovery boundaries. The complete implementation record is in
the [2026-08-26 Workforce-only adoption checkpoint](../checkpoints/2026-08-26-workforce-only-progressive-adoption.md).

PR #20 merged this outcome to protected `main` as exact squash commit
`b387748` on 2026-08-27. Pull-request run `33014664319` passed the full
high-risk acceptance path, including all eight PostgreSQL shards, combined
branch-aware coverage, and the stable `PR gate`. Protected-main CodeQL run
`33037058305` and Pages run `33037059040` then passed for that exact commit.

## Latest protected-main repository experience

Protected `main` now makes Maru's public GitHub surface easier to understand and
turns the existing secure release machinery into a curated human-facing
process.

- The restored Maru header leads a clearer README with the product promise,
  honest maturity warning, implemented evaluation slices, build/documentation
  status, and direct routes to Docs, Releases, Issues, Discussions, support,
  contribution, and security guidance.
- `CHANGELOG.md` now has a maintained **Unreleased** section. A release pull
  request must create one non-empty dated section matching the derived CalVer
  and exact merge date; the workflow validates and places that content before
  exact source/image evidence and GitHub's supplemental generated notes.
- Issue Forms now distinguish bounded defects/proposals from exploratory
  Discussions and request preparation, roles/states, acceptance, non-goals,
  traceability, safety, and sanitized evidence.
- Completed [issue #21](https://github.com/martonpornoi/maru/issues/21)
  records the first curated immutable candidate. Live
  [issue #22](https://github.com/martonpornoi/maru/issues/22),
  [issue #23](https://github.com/martonpornoi/maru/issues/23), and
  [issue #24](https://github.com/martonpornoi/maru/issues/24) track
  Workforce-only continuity, the Workforce/Shift accessibility matrix, and the
  next attendance/handover/actual-time contract. Requirements, ADRs, the
  roadmap, and this handoff remain authoritative rather than being replaced by
  those issues.
- PR #25 merged this outcome as exact squash commit `5d84ca1` on 2026-08-27.
  Pull-request run `33054662739`, managed CodeQL run `33054564446`, exact-main
  CodeQL run `33064605109`, and Pages run `33064605358` passed.

## First immutable release candidate

[Maru 2026.08.27 release candidate 1](https://github.com/martonpornoi/maru/releases/tag/v2026.08.27-rc.1)
is public, immutable, and explicitly pre-production.

- Release PR [#27](https://github.com/martonpornoi/maru/pull/27) merged as exact
  squash commit `be0b21d` after local certification and protected run
  `33096490372` passed the complete high-risk acceptance path.
- With explicit owner authorization, the live selected-Actions policy moved
  from the exact protected-main 16-entry state to the reviewed 18-entry state.
  Immediate readback proved exact parity while `github_owned_allowed` and
  `verified_allowed` remained `false`.
- Immediately before dispatch, immutable Releases were enabled, all three live
  security-alert classes were empty, remote `main` still equalled `be0b21d`,
  and the candidate tag, Release, package, and image tag were unused.
- Release run
  [`33103766556`](https://github.com/martonpornoi/maru/actions/runs/33103766556)
  passed all 19 jobs, including the complete exact-source certification matrix,
  and published `v2026.08.27-rc.1` at `2026-08-27T19:53:09Z`.
- The immutable tag resolves exactly to `be0b21d`. All eight Release assets and
  their attestations verify; all seven payload hashes match `SHA256SUMS`; and
  the exact release manifest records PR #27, the candidate identity, and image
  digest `sha256:a44de03a4fe7bd5b3a5aaf73dd83b565b727a98bf895bf80416981e869eeb445`.
- The GHCR tag resolves to that same digest. SLSA v1 provenance verifies with
  the signer constrained to `.github/workflows/release.yml`, source ref
  `main`, and exact source digest `be0b21d`.
- The public body leads with the curated changelog and exact evidence, then
  includes GitHub's categorized generated pull-request titles. Issue #21 is
  closed with the complete public verification record.

This candidate is for synthetic-data evaluation. It is not a gold release,
production deployment, supported hosted service, production personal-data
approval, or completion of external operational gates. The complete record is
in the
[candidate publication checkpoint](../checkpoints/2026-08-27-first-immutable-release-candidate-published.md),
with the failed earlier attempt retained in the
[initial preparation checkpoint](../checkpoints/2026-08-27-first-immutable-release-candidate.md)
and
[provenance-policy recovery checkpoint](../checkpoints/2026-08-27-release-provenance-policy-recovery.md).
The subsequent synthetic evaluation and retained-candidate disposition are in
the
[operator evaluation checkpoint](../checkpoints/2026-08-29-first-release-candidate-synthetic-operator-evaluation.md).

## Current product baseline

Protected `main` contains the first coherent Workforce journey from structure
through accountable scheduled work:

```text
Organization structure
  -> Position management
  -> Assignment proposal and independent decision
  -> person-owned deliberate Availability sharing
  -> organizer Shift demand and publication
  -> suitable personal work and claim
  -> independent confirmation
  -> locked coverage
  -> completed work record
```

The Shift outcome is governed by [ADR 0078](../architecture/decisions/0078-governed-workforce-shift-journey.md),
HR-009, and the
[Shift planning and My shifts contract](../product/page-contracts/shift-planning-and-my-shifts.md).
The complete implementation and verification record is in the
[2026-08-25 Shift checkpoint](../checkpoints/2026-08-25-governed-workforce-shift-journey.md).

### The journey now makes sense to both sides

- **Shift planning** lets an exactly authorized organizer create private
  Position demand with time, place, briefing, headcount, break, rest, and
  supervision expectations; publish it; review claims; confirm or remove them
  with reasons; lock, reopen, complete, or cancel coverage; and inspect reason
  history in the same workflow.
- **My shifts** shows one person only suitable unfinished work and their own
  retained claims and commitments. It includes operational instructions and
  current suitability warnings but excludes other people, organizer identity
  and rationale, private planning reasons, and exact Availability values.
- A person may withdraw an active open commitment with an affirmative checkbox
  and no explanation. Organizer history retains only the fixed fact that the
  person withdrew; Maru does not collect a private free-text reason.
- A claim is not a confirmation. Confirmation independently rechecks the exact
  Position assignment, current submitted Availability version and covering
  period, overlap, required rest, and transactional capacity.
- Coverage locks only when every active claim is current and confirmed.
  Underfilled locking needs an explicit acknowledgement and retained rationale.
  Completion is offered only after locked work ends.

### Navigation and page framing are unified

- The durable organizer sequence is **Structure**, **Positions**,
  **Assignments**, **Availability**, and **Shifts**. Staff Console action hints
  reveal only currently available continuations; each destination authorizes
  again.
- **My Workforce** is now a first-class personal Work destination. It is
  searchable, pinnable, and remains current across Positions, Availability,
  and Shifts rather than appearing only as a continuation from Administration.
- Purpose names are canonical user language. Numeric prefixes remain only in a
  few historical filenames, test module names, and accepted ADR chronology;
  they are not presented as product page names.
- All new pages retain one H1 and the host's single `main` landmark, ordinary
  links/forms, edition-local times, visible text state, and responsive stacking.
  The rehearsal corrected low-contrast card headings, oversized narrow action
  cards, singular coverage grammar, and premature completion affordance.

### Commands, privacy, and database ownership are explicit

- Browser and strict versioned API adapters call the same demand and commitment
  commands. They authorize before parsing private input or loading names,
  reject unknown fields and type coercion, require optimistic versions, and
  use UUID idempotency keys.
- Each committed mutation writes aggregate state, immutable minimized receipt,
  audit, registered domain event, and outbox message atomically. Organizer
  reasons are directly inspectable where the decision is made.
- Organizer reads require independent `workforce.view_shifts` authority and a
  complete field ceiling. They are bounded to 1,024 demands and 4,096
  commitments, use a repeatable read-only snapshot, reauthorize before
  disclosure, and persist minimized sensitive-read evidence. Browser POST
  adapters that load the protected projection for validation or rerendering
  now retain the actual POST method in that evidence instead of rejecting the
  valid workflow.
- Workforce migration `0013_shift_journey` installs aggregate, receipt,
  exact-scope, state-evidence, capacity, work/rest-overlap, protected-deletion,
  Position-dependency, and downgrade guards. Authorization migration
  `0018_workforce_shift_capabilities` installs the exact capability scope.
- Runtime ACL and provenance readiness include every new relation, function
  fingerprint, and exact trigger attachment while withholding direct guard-
  function execution from the runtime login.

## Established repository and delivery baseline

- PR #27, **Release Maru 2026.08.27 rc.1 with audited provenance policy**,
  merged as exact squash commit `be0b21d` on 2026-08-27. Protected run
  `33096490372` passed the complete high-risk acceptance path; release run
  `33103766556` then recertified exact `main` and published the first immutable
  prerelease with exact source, asset, OCI, and provenance evidence.
- PR #25, **Improve GitHub release and collaboration experience**, merged to
  protected `main` as exact squash commit `5d84ca1` on 2026-08-27. Pull-request
  run `33054662739` passed all eight PostgreSQL shards, combined coverage, the
  full acceptance jobs, and the stable `PR gate`; exact-main CodeQL run
  `33064605109` and Pages run `33064605358` then passed.
- PR #20, **Add Workforce-only progressive adoption profile**, merged to
  protected `main` as exact squash commit `b387748` on 2026-08-27. GitHub
  Actions run `33014664319` passed all eight PostgreSQL shards, combined
  coverage, the full acceptance jobs, and the stable `PR gate`; exact-main
  CodeQL and Pages publication then passed.
- PR #18 merged the governed Workforce Shift journey to protected `main` as
  exact squash commit `c4e04fe` on 2026-08-26. GitHub Actions run
  `32897740582` passed all eight PostgreSQL shards, combined coverage, the full
  acceptance jobs, and the stable `PR gate` for its exact head.
- PR #15, **Curate newcomer documentation and fictional examples**, merged to
  protected `main` as exact commit `2b78934` on 2026-08-23. GitHub Pages run
  `32624208484` deployed it successfully; the former pending documentation is
  reconciled.
- Protected collaboration retains pull requests, squash-only history,
  no-bypass `PR gate`, resolved conversations, immutable Action pinning,
  Dependabot security updates, dependency review, secret scanning, push
  protection, private vulnerability reporting, managed CodeQL, and
  protected-main Pages publication.
- Repository-owned examples use only MaruCon, MaruDance, synthetic people, and
  reserved contact domains. The demo fixture now creates its Position,
  opportunity, Assignment, Availability, and Shift through governed commands
  and leaves the Shift unclaimed for a human rehearsal.
- Organization structure, Position management, Assignment management, and
  Availability management retain ADRs 0075 through 0077 and their existing
  authorization, privacy, evidence, and database boundaries. A Shift does not
  reinterpret those facts.

## Decisions

- ADR 0080 accepts immutable edition adoption profiles, the first
  `workforce_only@1` profile, minimum guided setup, truthful Maru-operator
  accountability, profile-before-authority enforcement, no implied
  Participation, and explicit portability and removal limitations. It
  supersedes ADR 0040 only where that ADR assumed every organization must call
  its accountable root an Executive Board.
- ADR 0079 accepts one concise always-on `AGENTS.md` contract plus four focused,
  repository-scoped skills with progressive disclosure, user-facing metadata,
  deterministic validation, protected deletion, and human guidance.
- NFR-013 makes progressive modular adoption mandatory. A purpose-specific
  volunteer, event-host, bidder, or communications account does not imply
  attendance, registration, purchase, payment, or unrelated data collection.
- ADR 0078 accepts explicit Position demand and retained commitment aggregates,
  independent person claim and organizer confirmation, transactional capacity,
  work-plus-rest overlap exclusion, stale-evidence review, explicit underfill,
  locked coverage, post-end completion, cancellation, and fix-forward recovery.
- Availability is planning input, not a promise or reservation. Position
  Assignment is responsibility and authority, not scheduled time. Preferred
  Availability affects ordering only.
- Self-withdrawal deliberately collects no reason. Required administrative
  rationale remains visible in organizer workflows; routine personal privacy is
  not traded for unnecessary audit text.
- The first Shift slice does not silently invent qualifications, maximum-hours,
  lone-working or accommodation policy, public schedule publication,
  notifications, recurrence, check-in, timekeeping, handover acceptance, or
  automatic replacement staffing.
- Purpose names such as **Organization structure**, **Position management**,
  **Assignment management**, **Availability management**, **Shift planning**,
  **My Workforce**, and **My shifts** are canonical user language.

## Verification for this working outcome

### Synthetic OCI runtime rehearsal

Completed for issue #37 against the immutable candidate and reviewed
PostgreSQL 17.11 digest:

- 37 focused unit tests pass for immutable-reference validation, exact
  source/SQL binding, resource isolation, command ordering, credential-free
  arguments/evidence, exact health shapes, irreversible activation postflight,
  fail-closed retained-job discovery, foreign-collision refusal, and verified
  final cleanup;
- four focused PostgreSQL integration tests pass for the streamed bootstrap's
  first run, exact idempotent replay, unusable password, zero ordinary
  authority/organization side effects, collision rollback, and explicit
  local/test-only fence; and
- the real Docker rehearsal passes every one of its 16 stages in 173 seconds,
  produces a sanitized schema-v1 receipt, deletes its exact containers,
  internal network, data volume, and three secret volumes, and leaves no
  resource with the run label; and
- a second retained run proves all 19 web, PostgreSQL, and one-shot containers
  remain discoverable and stopped, then the standalone exact-run cleanup
  removes them, the internal network, and all four volumes with a final zero
  label inventory.

This is complete bounded synthetic runtime evidence. It is not production
deployment, static delivery, provider, recovery, accessibility, or owner
acceptance evidence.

### First immutable release candidate

Completed for PR #27, exact merge `be0b21d`, and release run `33103766556`:

- clean-tree local certification passed exact PR head `7873c52`: locked
  dependencies, package and legal verification, Ruff, mypy, PyDocLint,
  warning-fatal Sphinx/AutoAPI, dependency audits, 29 frontend tests, 2,061 unit
  tests, 2,357 PostgreSQL integration tests across eight isolated shards, and
  the 90% combined branch-coverage minimum;
- protected PR run `33096490372` passed all 22 jobs for that exact head,
  including the high-risk aggregate `PR gate`; CodeQL's Actions,
  JavaScript/TypeScript, and Python analyses passed on the same head;
- the authorized live selected-Actions reconciliation was proved as an exact
  16-to-18-entry append-only change with both broad trust flags disabled;
- the immediate pre-dispatch admin read reported immutable Releases enabled,
  exact remote `main`, zero Dependabot, code-scanning, or secret-scanning
  alerts, and unused tag, Release, package, and image identities;
- release run `33103766556` passed request/source validation and the complete
  exact-main certification matrix before publishing the candidate;
- GitHub reports the prerelease immutable, `gh release verify` succeeds, the
  tag resolves exactly to `be0b21d`, all eight downloaded assets pass individual
  attestation verification, and all checksum and manifest relationships match;
- GHCR resolves `2026.08.27-rc.1` to
  `sha256:a44de03a4fe7bd5b3a5aaf73dd83b565b727a98bf895bf80416981e869eeb445`;
  exact-workflow, exact-source, main-ref SLSA v1 verification succeeds; and
- the Releases tab visibly presents curated notes followed by categorized
  generated pull-request titles. Issue #21 is closed as completed with this
  evidence; and
- the post-publication handoff passes 19 focused documentation/public-material
  tests, documentation policy across 351 Markdown files and 207 requirement
  identifiers, and the complete warning-fatal Sphinx/AutoAPI build.

### Synthetic release-candidate evaluation

Completed for issue #29 against immutable candidate `v2026.08.27-rc.1`:

- an unauthenticated browser confirmed the public immutable prerelease, while
  authenticated GitHub CLI verification proved all assets, checksums, manifest,
  exact tag/source/image relationships, SPDX SBOM, and strict SLSA provenance;
- the exact non-root image migrated a fresh PostgreSQL 17 database, loaded only
  repository-owned fictional fixture data, returned exact build identity and
  liveness, and retained governed state through ordered stop and restart;
- distinct synthetic sessions completed Workforce-only setup, operator
  activation, Department, starter, Position, opportunity, application,
  Assignment, person-owned Availability, and Shift completion after its real
  scheduled end;
- organizer-only and unadopted Registration routes each returned a name-free
  403 to the wrong actor, while the final exact-edition audit recorded zero
  Participation, Registration, and directly scoped unadopted-module rows;
- readiness failed closed with Logistics unavailable because the local runtime
  role was unnamed, and five referenced brand assets returned 404 under the
  unsupported bare-Gunicorn topology; and
- six sanitized, bounded defects were opened as issues #37 through #42. The
  complete matrix records 14 passed, 2 failed, 0 blocked, and 2 deferred areas.

### Merged GitHub release and collaboration experience

Completed locally:

- 64 focused release-metadata, workflow-contract, public-repository-material,
  and documentation-policy tests pass;
- focused Ruff lint and formatting pass for the changed Python release code and
  tests;
- documentation policy validates 348 Markdown files, four repository skills,
  and 207 unique requirement identifiers;
- the broad `scripts/check.ps1 -SkipPythonTests` gate passes package build and
  verification, Python and JavaScript dependency audits, whole-tree Ruff and
  strict mypy across 373 source files, PyDocLint, semantic docstrings across
  383 source files, warning-fatal Sphinx/AutoAPI, migration and Django checks,
  production-settings validation, OpenAPI generation, TypeScript checking, 29
  frontend tests, and the production frontend build; and
- clean-tree `scripts/certify.ps1` passes for exact merged pull-request head
  `58b90ab9e8b0b31cb6547abcad89434494713e7e`: all 2,060 unit tests, 2,357
  PostgreSQL integration tests across eight isolated shards, 29 frontend
  tests, the complete static/documentation/security/package gates, and the 90%
  combined branch-coverage minimum pass; and
- `git diff --check` passes.

The Maru header was visually inspected at its original 1,280 by 640 pixels.
Authenticated readback confirms live issues #21 through #24 with their intended
titles and `proposal`/`triage` plus scoped classification labels. Hosted run
`33054662739` subsequently passed the complete high-risk path and stable
`PR gate`; PR #25 squash-merged as `5d84ca1`, and exact-main CodeQL and Pages
publication passed.

### Merged Workforce-only adoption evidence

Completed locally for the pull-request head:

- a fresh PostgreSQL database applies the complete migration graph and passes
  Workforce-only setup, two-person activation, raw authority-scope guards,
  immutable profiles, profile-isolated policy, and the legacy policy ceiling;
- 64 focused structure, assignment, adoption, and access-management unit and
  integration tests pass together;
- 100 edition, page, representation, navigation, and authorization regressions
  exposed one scope-ceiling regression; that regression was corrected and its
  fresh 14-test profile/policy proof now passes;
- the authorization readiness contract recognizes the new trigger functions
  and attachments; its focused 11-test unit/integration proof passes;
- all 29 Staff Console component and accessibility tests and strict TypeScript
  checking pass; and
- a consolidated 67-test browser-adapter and navigation regression passes after
  the first-use rehearsal corrections;
- whole-tree Ruff formatting/lint, strict mypy across 373 source files,
  PyDocLint, semantic docstrings, Django checks, and migration-drift checks
  pass;
- documentation policy validates 347 Markdown files and 207 requirement
  identifiers, and warning-fatal Sphinx/AutoAPI builds the complete site;
- the clean-tree `scripts/certify.ps1` gate passes the complete unit and
  eight-shard integration suite, combined branch-aware coverage, packaging,
  dependency audits, production settings, generated contracts, frontend build,
  and migration recovery for one exact commit; and
- a synthetic platform-administrator, two-distinct-operator, and volunteer
  browser rehearsal passes the entire setup-to-locked-Shift journey at 1,280
  and 390 CSS pixels. It shows no inspected console warning/error or page-level
  horizontal overflow, and database inspection confirms zero Participation,
  Registration, attendee membership, or other direct unadopted-module rows.

The visible rehearsal used separate synthetic accounts and a deliberately
created verified volunteer identity, not real convention owners or production
personal data. Pointer interaction verified the mobile drawer; automated tests
retain the keyboard/Escape/focus contract because the browser abstraction did
not provide reliable keyboard activation evidence. Representative screen-reader
acceptance remains open. Hosted run `33014664319` subsequently passed the full
high-risk acceptance path and stable `PR gate` for the exact PR #20 head before
protected-main squash merge `b387748`.

### Merged Shift implementation evidence

Completed locally before merge:

- 77 focused unit and integration regressions pass across Shift lifecycle,
  commands, browser adapters, strict API, projections, raw database guards,
  demo data, navigation, existing Assignment and Availability behavior, and
  responsive shell/style contracts;
- the expanded post-review acceptance set passes all 116 focused and
  cross-cutting regressions in 168.13 seconds. It covers 62 Shift command,
  strict-input, API, browser, privacy, recovery, concurrency, projection, and
  database cases plus the specialist-admin help registry, closed
  internal-event worker registry, and Organization structure's final Shift
  authorization checks and single-instant projection contract;
- GitHub Actions run `32897740582` passes every substantive job, all eight
  PostgreSQL shards, combined branch-aware coverage, and the stable `PR gate`
  for the exact Shift pull-request head after the earlier acceptance gaps were
  corrected;
- a real two-connection PostgreSQL claim race proves capacity cannot be
  oversubscribed;
- the expanded runtime-role, exact function-fingerprint, trigger-attachment,
  authority-provenance, Organization structure, and retired-Department
  readiness gate passes all 453 cases in 863.84 seconds;
- Staff Console generated API types, strict TypeScript checking, all 28 Vitest
  component/accessibility tests, and the production Vite build pass, with host
  assets refreshed;
- OpenAPI regenerates and validates with zero schema errors. Its 23 existing
  deterministic enum-name warnings remain visible;
- repeating OpenAPI generation, TypeScript client generation, and the
  production Staff Console build leaves all six generated contract and host
  artifacts byte-for-byte unchanged;
- Django system check passes with only the expected local `identity.W001`
  invitation-encryption warning, and `makemigrations --check` reports no drift;
- a fresh disposable PostgreSQL database applies all migrations, reverses the
  unused Shift schema and capability migrations, and reapplies them. A durable
  synthetic Shift then refuses downgrade at the intended fix-forward fence and
  leaves migration `0013` applied;
- whole-tree Ruff lint and formatting pass, and strict mypy reports no issues
  across 369 source files;
- documentation policy passes across 331 Markdown files and 204 requirement
  identifiers; full PyDocLint passes; the semantic Python-docstring validator
  passes 379 source files;
- warning-fatal Sphinx/AutoAPI builds the complete contributor site
  successfully; and
- an authenticated synthetic owner-and-volunteer browser rehearsal passes at
  1,280 and 390 CSS pixels. It covers discovery, claim, independent
  confirmation, explicit underfilled lock, pre-end completion guidance, reopen,
  reasonless self-withdrawal, minimized retained history, drawer background
  isolation, Escape/focus return, one H1 and one `main`, no duplicate IDs, no
  inspected unlabeled controls, no horizontal overflow, and no console warning
  or error.

The merged Shift journey's authoritative hosted evidence is run `32897740582`.
That result certifies the exact PR #18 head; it does not certify this repository
support branch, a deployment, or production readiness.

## Known risks and incomplete work

- `v2026.08.27-rc.1` is an immutable pre-production candidate, not a gold
  release or production-readiness claim. Provider certification,
  representative recovery, deployment, accessibility, policy, and owner
  acceptance gates remain open.
- The evaluation's exact-image runtime and static-delivery defects (#37 and
  #38) are resolved by bounded synthetic rehearsals. The Assignment
  authority-interval repair (#39) is its own focused protected outcome. Issue
  #40 now has the bounded consumer-integrity implementation recorded above,
  and #41 has the profile-aware Participation contract correction above. The
  missing reproducible end-to-end Workforce-only tutorial (#42) remains
  incomplete.
- The new header is a repository README asset only. GitHub's live social preview
  remains unchanged; adopting the asset there must wait for this branch to merge
  and requires a separate setting mutation plus readback.
- Issues #21, #29, and #37 through #40 are complete in protected repository
  behavior. Issue #41's focused contract correction and verification are
  recorded above; its pull-request gate remains authoritative. Issues #22
  through #24, #30 through #36, and #42 expose the remaining
  bounded work; none is accepted as complete before its own tests,
  documentation, and protected pull request pass.
- Workforce-only adoption is implemented for trustworthy evaluation, not
  production cutover. General partner bulk import, a complete continuity
  export, printable rota, offline/manual reconciliation pack, profile expansion
  or decommissioning workflow, and stopped-operation rehearsal remain absent.
- Existing scoped APIs and browser pages provide access to retained Workforce
  data, but they are not yet an accepted portability package. An organization
  must not decommission its incumbent system based only on this branch.
- Platform specialist records and direct database recovery remain privileged
  operational surfaces. Supported setup, policy, service, public discovery,
  and operator workflows enforce the profile; production deployment still
  needs role provisioning and runbook acceptance for those exceptional paths.
- UX-029 remains a release gate at 320, 768, 958, 1,024, and 1,920 CSS pixels,
  200 percent zoom, complete keyboard paths, representative screen readers,
  reduced motion, and every empty, failure, stale, read-only, disclosure, and
  mutation-role state.
- A two-human owner rehearsal must still cover stepped-up Assignment and Shift
  decisions with distinct real accounts. Synthetic browser sessions and
  automated session separation are strong implementation evidence, not owner
  acceptance.
- General qualifications, maximum-hours and lone-working policy,
  accommodation-sensitive decisions, schedule publication and change
  acknowledgement, notifications, recurrence, check-in, lateness or absence
  escalation, actual time, handover acceptance, and replacement staffing remain
  absent.
- Exact Availability periods still need an approved organization-specific
  post-edition retention policy, legal-hold behavior, disposal worker,
  observability, and representative recovery before production personal data.
- Registration writer retirement and readiness activation, task-oriented Venue
  and Logistics conversion, deployment, stopped-writer cutover, restore/PITR,
  worker supervision, provider certification, load, telemetry, privacy,
  safeguarding, training, and external acceptance remain production gates.

## Smallest sensible next actions

1. Publish the reproducible end-to-end Workforce-only operator-and-volunteer
   tutorial [#42](https://github.com/martonpornoi/maru/issues/42) as the next
   bounded release-candidate finding.
2. Complete [issue #22](https://github.com/martonpornoi/maru/issues/22)'s
   Workforce-only continuity package: preview-first
   import, scoped export, printable/manual fallback, reconciliation evidence,
   and explicit stop/expand procedures.
3. Complete [issue #23](https://github.com/martonpornoi/maru/issues/23)'s
   Workforce-only and Shift mutation-role, responsive, keyboard, zoom,
   disclosure, and representative screen-reader matrix.
4. Accept [issue #24](https://github.com/martonpornoi/maru/issues/24)'s
   scheduling contract before implementation: check-in, late/absent escalation,
   handover, actual-time boundaries, and the exact line between an internal
   commitment and a published personal schedule.
5. Contract the next standalone profiles by partner need: Programme and event
   submissions, Communications publishing, Charity art auction, and
   Registration without payments.
6. Define and rehearse the organization-approved Availability disposal policy,
   legal holds, worker observability, restore/PITR, and fix-forward behavior.

## Resume instructions

Read `AGENTS.md`, the
[agent-assisted workflow guide](../development/agent-workflows.md), this file,
`ROADMAP.md`, the production-consolidation ledger,
the management-shell, Position, Assignment, Availability, and Shift page
contracts, the Workforce-only adoption setup contract and runbook, and ADRs
0019/0028/0039/0041/0049/0055/0075 through 0080. Use only synthetic data.
Preserve exact organization and edition scope, authorization
before disclosure, My Maru/Administration separation, private Availability,
independent confirmation, privacy-minimized self-withdrawal, canonical lock
order, immutable command evidence, runtime-role containment, and fix-forward
recovery. Apply NFR-013 so one adopted workflow does not create unrelated
participation, payment, navigation, notification, or authority side effects.
Do not confuse a visible destination, passing local rehearsal, focused test
gate, or selected skill with authority cutover, release acceptance, or
production readiness.
