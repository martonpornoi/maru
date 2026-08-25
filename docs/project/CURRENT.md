# Current project state

Last updated: 2026-08-25
Phase: Production consolidation and management-experience recovery.

Maru is an actively developed Django/PostgreSQL modular monolith. It is not a
supported hosted service, a production-ready release, or approved for
production personal data. The detailed capability inventory remains in the
[production-consolidation ledger](PRODUCTION_CONSOLIDATION.md); this file is the
concise handoff.

## Latest working outcome

The current feature branch completes the first coherent Workforce journey from
structure through accountable scheduled work:

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
  disclosure, and persist minimized sensitive-read evidence.
- Workforce migration `0013_shift_journey` installs aggregate, receipt,
  exact-scope, state-evidence, capacity, work/rest-overlap, protected-deletion,
  Position-dependency, and downgrade guards. Authorization migration
  `0018_workforce_shift_capabilities` installs the exact capability scope.
- Runtime ACL and provenance readiness include every new relation, function
  fingerprint, and exact trigger attachment while withholding direct guard-
  function execution from the runtime login.

## Established repository and product baseline

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

Completed locally:

- 77 focused unit and integration regressions pass across Shift lifecycle,
  commands, browser adapters, strict API, projections, raw database guards,
  demo data, navigation, existing Assignment and Availability behavior, and
  responsive shell/style contracts;
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

The latest canonical whole-tree acceptance on protected `main` remains 4,067
tests in 15,558.23 seconds at 90.78 percent branch-aware coverage. It predates
this feature branch and must not be represented as certification of the new
Shift journey.

## Known risks and incomplete work

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

1. Complete the Shift mutation-role and UX-029 acceptance matrix, prioritizing
   distinct claimant/confirmer accounts, stale evidence, full capacity,
   underfill, denied/read-only states, 200 percent zoom, and a representative
   screen reader.
2. Accept the next scheduling contract before implementation: check-in,
   late/absent escalation, handover, actual-time boundaries, and the exact line
   between an internal commitment and a published personal schedule.
3. Define and rehearse the organization-approved Availability disposal policy,
   legal holds, worker observability, restore/PITR, and fix-forward behavior.
4. Apply the same task-oriented page frame to Venues and Logistics, prioritizing
   receiving, custody, physical-space schedules, and exceptions over model
   inventories.
5. Finish Registration writer retirement, readiness activation, representative
   recovery/concurrency, and production cutover without creating a second setup
   path.

## Resume instructions

Read `AGENTS.md`, this file, `ROADMAP.md`, the production-consolidation ledger,
the management-shell, Position, Assignment, Availability, and Shift page
contracts, and ADRs 0019/0028/0039/0041/0049/0055/0075 through 0078. Use only
synthetic data. Preserve exact organization and edition scope, authorization
before disclosure, My Maru/Administration separation, private Availability,
independent confirmation, privacy-minimized self-withdrawal, canonical lock
order, immutable command evidence, runtime-role containment, and fix-forward
recovery. Do not confuse a visible destination, passing local rehearsal, or
focused test gate with authority cutover, release acceptance, or production
readiness.
