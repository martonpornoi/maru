# Current project state

Last updated: 2026-08-25
Phase: Production consolidation and management-experience recovery.

Maru is an actively developed Django/PostgreSQL modular monolith. It is not a
supported hosted service, a production-ready release, or approved for
production personal data. The detailed capability inventory remains in the
[production-consolidation ledger](PRODUCTION_CONSOLIDATION.md); this file is the
concise handoff.

## Latest working outcome

The current branch now carries one coherent owner-facing Workforce planning
journey through deliberate Availability sharing:

```text
Organization structure
  -> Position management
  -> Assignment proposal
  -> independent approval or rejection
  -> personal Availability draft or deliberate sharing
  -> minimized organizer Availability planning view
```

Shifts retain a truthful next-stage place but are not yet interactive. The
unified management shell, Registration-to-Workforce handoff, purpose-based page
names, owner-safe Assignment lifecycle, and contributor-documentation baseline
remain intact.

### Availability belongs to the person

- [ADR 0077](../architecture/decisions/0077-person-owned-workforce-availability.md),
  HR-014, and the
  [Availability management contract](../product/page-contracts/availability-management.md)
  define one plan per person, organization, and edition. An open proposed or
  active Position relationship permits creation and replacement; the existing
  owner may still read or withdraw a plan after that open relationship ends.
- **My Workforce** now shows one Availability continuation per related edition.
  The personal page distinguishes Not started, Private draft, Shared with
  organizers, Not available for this edition, and Withdrawn. It explains that
  periods are complete planning input rather than shifts or promises.
- The owner may replace up to 64 explicit non-overlapping half-open periods as
  a private draft or a deliberately submitted plan. A submitted empty set means
  explicitly unavailable; absence of a submitted plan remains unknown.
- Browser input uses the edition's IANA time zone and rejects daylight-saving
  gaps and folds. API timestamps require `Z` or an explicit numeric offset.
  Preferred is a soft planning signal only.
- Withdrawal requires explicit confirmation and deletes every current exact
  period immediately. Superseded exact periods are also removed rather than
  retained as calendar history.

### Organizers receive a separate minimized projection

- `workforce.view_availability` is an exact-edition, delegable, persistable
  capability with a complete field ceiling for shared consequences, current
  windows, and operational display labels. It is independent from structure or
  assignment management.
- **Workforce availability** starts only from people with proposed or active
  assignments. It returns their display label, current Department/Position
  labels, assignment state, submitted consequence, and current submitted
  periods. It excludes drafts, prior periods, reasons, notes, onboarding,
  applications, authority provenance, unrelated people, and private HR data.
- Absent and private-draft plans both appear as **Not shared**, so an organizer
  cannot infer whether a person has started. Submitted zero-period plans appear
  as **Not available**; withdrawal exposes only its consequence.
- Every visible period and sharing timestamp is rendered in the edition's
  stated IANA time zone. The authenticated rehearsal caught and corrected an
  organizer-page UTC rendering defect before handoff.
- The organizer projection is bounded and complete-or-unavailable. It uses one
  repeatable read-only snapshot, repeats full authorization at response time,
  and appends a value-minimized sensitive-read audit before disclosure.
- The Staff Console exposes **Availability** only when the fresh structure API
  includes `can_view_availability`; otherwise it says **Access required**.
  Every destination authorizes independently.

### Shared strict commands and database ownership

- Browser and versioned API adapters call the same save and withdrawal
  commands. They authorize exact relationship or capability before parsing
  private input or loading names, reject unknown top-level and nested fields,
  require optimistic versions, and use UUID idempotency keys.
- Each committed command writes the current plan, complete current period set,
  immutable minimized receipt, audit, registered domain event, and outbox in
  one transaction. Receipts, audits, and events retain state/count/digests and
  command provenance but no exact times or free text.
- Authorization migration `0017_workforce_availability_capability` preserves
  the database scope catalog while adding the organizer capability and the
  relationship-derived self capability.
- Workforce migration `0012_person_owned_availability` adds one-plan scope and
  person-kind checks, current-version period guards, PostgreSQL interval
  exclusion, replacement-only period writes, deferred exact receipt/final-set
  evidence, protected deletion/truncate, IDN-011 enforcement, and a downgrade
  fence. Its extension operation does not claim ownership of the existing
  `btree_gist` installation used by other modules.
- Runtime ACLs permit select/insert/update on the plan, select/insert on
  receipts, and select/insert/delete but not update on replacement-only period
  rows. All new guard functions and trigger attachments are included in
  provenance readiness and are not directly executable by the runtime login.

### Assignment and unified framing remain in place

- [ADR 0076](../architecture/decisions/0076-owner-safe-position-assignment-lifecycle.md)
  and HR-013 continue to govern relationship-bounded proposal, genuinely
  independent stepped-up approval/rejection, retained ending, linked role and
  participation evidence, headcount, and directly inspectable organizer
  reasons.
- **Workforce assignments** remains the bounded organizer queue; **My
  Workforce** remains a separate reason-minimized subject view. Availability
  does not reinterpret assignment dates or authority.
- Administration continues to lead with durable Convention work and
  progressively disclose Organizations, Platform, and Specialist records. My
  Maru and Administration retain independent navigation projections and pins.
- Converted pages use one H1 and the host's single main landmark. Availability
  uses labelled fieldsets, text state labels, ordinary keyboard-operable
  controls, action-local alert errors, and responsive stacking within the same
  shell grammar.
- Living documentation names every surface by human purpose. Numeric filename
  prefixes remain only for stable ordering and incoming links, never as page or
  journey names.

## Established repository and product baseline

- PR #15, **Curate newcomer documentation and fictional examples**, merged to
  protected `main` as exact commit `2b78934` on 2026-08-23. GitHub Pages run
  `32624208484` deployed that commit successfully; the old pending statements
  are reconciled.
- Protected public collaboration retains pull requests, squash-only history,
  no-bypass `PR gate`, resolved conversations, immutable Action pinning,
  Dependabot security updates, dependency review, secret scanning, push
  protection, private vulnerability reporting, managed CodeQL, and
  protected-main Pages publication.
- Repository-owned examples use MaruCon, MaruDance, synthetic people, and
  reserved contact domains. The fixture identifier remains
  `maru-fictional-two-convention-v6`; the immutable Workforce starter remains
  `marucon-reference@1`.
- Maru retains one administration shell, deny-by-default scoped authorization,
  audit and outbox evidence, governed organization/edition/workforce records,
  Registration and profile slices, typed applications, catalog and admission
  commerce, charity, venue, and bounded Logistics capabilities. Consult the
  production-consolidation ledger before treating any slice as complete.

## Decisions

- ADR 0077 accepts explicit current intervals, complete replacement, deliberate
  owner sharing, draft isolation, minimized organizer reads, immediate exact-
  period withdrawal, and separation from Shift commitments.
- Unknown, explicitly unavailable, shared, and withdrawn are different facts.
  No assignment, registration answer, profile field, or organizer action may
  imply or overwrite Availability.
- Organizer reads need a separate capability and audit. Structure or Assignment
  authority alone is insufficient; a frontend action hint never grants access.
- Exact superseded periods have insufficient audit value to justify retained
  calendar history. Immutable keyed digests and count-only command evidence
  prove the transition without preserving old values.
- The code does not invent a jurisdiction-independent post-edition retention
  duration. An approved organization policy, legal-hold behavior, and disposal
  worker remain a deployment gate.
- Availability is not a Shift. HR-009 and SCH-001/SCH-005 still need demand,
  suitability, claim, confirmation, removal, overlap/rest, publication,
  completion, locking, and recovery decisions before scheduling gains controls.
- Purpose names such as **Organization structure**, **Position management**,
  **Assignment management**, **Availability management**, and **Registration
  setup and account onboarding** are canonical user language.

## Verification for this working outcome

Completed locally so far:

- all five Availability command/browser-adapter/API/database integration cases
  pass, covering draft privacy, sharing, explicit unavailability, withdrawal,
  retries, scope, authorization-before-parsing, read audit, and raw guards;
- all 271 PostgreSQL runtime-role integration cases pass across the updated
  period replacement ACL profile and provisioning artifact;
- the canonical unit suite passes 1,998 tests, including interval, DST,
  formset, navigation, and single-landmark regressions;
- the focused Assignment/Availability/Workforce regression selection passes
  after updating the structure decision-call contract for the new independent
  action hint;
- Staff Console Vitest passes 28 tests; generated TypeScript API types, strict
  type checking, and the production Vite build pass, with generated host assets
  refreshed;
- OpenAPI regenerates and validates with zero schema errors. Its 20 current
  deterministic enum-name warnings remain visible;
- Django system check passes with only the expected local `identity.W001`
  invitation-encryption warning; migration `0012` applies, reverses while
  unused without touching the shared PostgreSQL extension, reapplies, and
  `makemigrations --check` reports no drift;
- whole-tree Ruff lint, strict mypy over 361 source files, and Ruff formatting
  for source/tests pass;
- documentation policy passes across 328 Markdown files and 204 unique
  requirement identifiers; full PyDocLint and the semantic Python-docstring
  validator pass across 371 source files;
- warning-fatal Sphinx/AutoAPI completes successfully;
- a second OpenAPI, generated TypeScript, and production Staff Console build
  leaves all six drift-controlled contract and host assets byte-for-byte
  unchanged; and
- an authenticated fictional owner/platform-oversight rehearsal passes at
  desktop and 390-by-844 narrow width. It covers explicit empty submission,
  dynamic-row keyboard focus, private draft isolation, deliberate sharing of
  two periods, organizer minimization, audited read evidence, edition-local
  rendering, one H1/main landmark, no duplicate IDs, and no horizontal
  overflow. Withdrawal is present with explicit confirmation and is covered by
  integration tests; it was not destructively activated against the retained
  shared demo state.

The latest canonical whole-tree acceptance on protected `main` remains 4,067
tests in 15,558.23 seconds at 90.78 percent branch-aware coverage. It predates
this branch and must not be represented as certification of Assignment or
Availability.

## Known risks and incomplete work

- The complete UX-029 matrix remains a release gate: 320, 390, 768, 958, 1,024,
  1,280, and 1,920 CSS-pixel states, 200 percent zoom, complete keyboard paths,
  representative screen-reader behavior, and every empty, failure, stale,
  read-only, disclosure, and mutation-role state.
- A destructive live withdrawal rehearsal still belongs in a disposable
  synthetic browser dataset. Automated browser-adapter, API, command, audit,
  and database tests already cover exact-period deletion and the minimized
  withdrawn consequence.
- A real two-human owner rehearsal must still operate Assignment approval from
  distinct authenticated accounts and cover step-up return behavior. Automated
  separate-session tests are strong implementation evidence, not owner
  acceptance.
- Exact Availability periods have no deployed post-edition disposal worker or
  approved organization policy yet. Production personal-data readiness remains
  blocked on that explicit retention decision and recovery rehearsal.
- Qualifications, Shifts, time records, assignment replacement/bulk operation,
  notifications, calendar import, recurrence helpers, and onboarding-review
  orchestration remain absent. Programme, inbox, and live operations are still
  planned product areas rather than available capabilities.
- Registration setup has a substantial lifecycle core, but writer retirement,
  readiness activation, complete builder parity, representative recovery and
  concurrency, and production cutover remain open.
- Representative deployment, stopped-writer cutover, restore/PITR, worker
  supervision, provider certification, load, telemetry, privacy, finance,
  safeguarding, operator training, and external acceptance remain production
  gates.

## Smallest sensible next actions

1. Complete UX-029's remaining widths, zoom, assistive-technology, error, stale,
   and read-only states, including destructive withdrawal in a disposable
   synthetic browser dataset.
2. Accept the Shift contract before implementation: demand, qualification,
   suitability, claim, independent confirmation, removal, capacity,
   overlap/rest, publication, completion, locking, current-Availability version
   comparison, and recovery.
3. Implement the smallest complete Shift journey from Position demand through
   personal suitable work and organizer coverage, without turning Availability
   into a commitment.
4. Define and rehearse the organization-approved post-edition Availability
   disposal policy, legal holds, worker observability, restore/PITR, and
   fix-forward behavior.
5. Finish UX-029's broader Registration, Organization structure, Position,
   Assignment, and Availability role/state matrix.
6. Apply the same page frame and task orientation to Venues and Logistics,
   prioritizing receiving, custody, schedules, and exceptions over model nouns.

## Resume instructions

Read `AGENTS.md`, this file, `ROADMAP.md`, the production-consolidation ledger,
the management-shell, Organization structure, Position management, Assignment
management, Availability management, and Registration setup contracts, and
ADRs 0019/0028/0039/0049/0055/0075/0076/0077. Use only synthetic data. Preserve
organization and edition scope, authorize before disclosure, keep My Maru
separate from Administration, keep draft and absent Availability
indistinguishable to organizers, and do not confuse a visible destination,
selected context, local demo record, passing browser rehearsal, or merged code
with authority cutover, release, or production approval.
