# Current project state

Last updated: 2026-08-27
Phase: Progressive adoption and management-experience recovery.

Maru is an actively developed Django/PostgreSQL modular monolith. It is not a
supported hosted service, a production-ready release, or approved for
production personal data. The detailed capability inventory remains in the
[production-consolidation ledger](PRODUCTION_CONSOLIDATION.md); this file is the
concise handoff.

## Latest protected-main outcome

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
- Live [issue #21](https://github.com/martonpornoi/maru/issues/21),
  [issue #22](https://github.com/martonpornoi/maru/issues/22),
  [issue #23](https://github.com/martonpornoi/maru/issues/23), and
  [issue #24](https://github.com/martonpornoi/maru/issues/24) track the first
  curated immutable candidate, Workforce-only continuity, the Workforce/Shift
  accessibility matrix, and the next attendance/handover/actual-time contract.
  Requirements, ADRs, the roadmap, and this handoff remain authoritative rather
  than being replaced by those issues.
- PR #25 merged this outcome as exact squash commit `5d84ca1` on 2026-08-27.
  Pull-request run `33054662739`, managed CodeQL run `33054564446`, exact-main
  CodeQL run `33064605109`, and Pages run `33064605358` passed.

## First release candidate preparation

Dedicated draft PR #26 prepares `Maru 2026.08.26 release candidate 1` from the
exact protected-main repository experience above.

- `CHANGELOG.md` moves the complete curated set into
  `## [2026.08.26] - 2026-08-27` and retains **Unreleased** for later work.
- Project and lock metadata use PEP 440 version `2026.8.26`; the intended public
  tag is `v2026.08.26-rc.1`.
- The candidate remains explicitly pre-production and synthetic-data-only. It
  is not a gold release, deployment, hosted-service promise, production
  personal-data approval, or completion of external operational gates.
- The protected release PR, exact-current-main check, immediately preceding
  administrator immutability readback, complete release certification, verified
  draft boundary, immutable publication, and post-publication attestations all
  remain mandatory.

The preparation record is in the
[first immutable release candidate checkpoint](../checkpoints/2026-08-27-first-immutable-release-candidate.md).

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

### First release candidate preparation

Completed before exact-commit certification:

- `uv lock --check` resolves the locked 108-package graph with project version
  `2026.8.26`;
- a simulated pull-request #26 candidate-1 metadata preflight accepts the
  `2026.08.26` dated changelog and derives `v2026.08.26-rc.1`;
- 47 focused release-metadata, release-evidence, workflow-contract, and public-
  material tests pass;
- documentation policy validates 349 Markdown files, four repository skills,
  and 207 unique requirement identifiers; and
- `git diff --check` passes.

The exact final release pull-request head still requires clean-tree local
certification and authoritative hosted acceptance before merge. Publication
also requires exact current `main`, a fresh administrator immutability
readback, full release-workflow certification, verified draft assets, and
post-publication immutable evidence reconciliation.

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

- The GitHub Releases tab remains empty while draft release PR #26 is prepared.
  It becomes populated only after protected merge, the immediately preceding
  administrator immutability readback, and the explicitly authorized immutable
  `v2026.08.26-rc.1` dispatch. Preparation alone creates no tag, image, Release,
  deployment, or production claim.
- The new header is a repository README asset only. GitHub's live social preview
  remains unchanged; adopting the asset there must wait for this branch to merge
  and requires a separate setting mutation plus readback.
- Issues #21 through #24 start in `triage`. They expose bounded work but do not
  promise priority, response time, implementation, or acceptance of an
  unreviewed design.
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

1. Complete draft release PR #26 through protected review, then perform
   [issue #21](https://github.com/martonpornoi/maru/issues/21)'s immediately
   preceding immutable-release readback, authorized `rc.1` dispatch, and full
   public evidence reconciliation.
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
