# Current project state

Last updated: 2026-08-23
Phase: Production consolidation and management-experience recovery.

Maru is an actively developed Django/PostgreSQL modular monolith. It is not a
supported hosted service, a production-ready release, or approved for
production personal data. The detailed capability inventory remains in the
[production-consolidation ledger](PRODUCTION_CONSOLIDATION.md); this file is the
concise handoff.

## Latest working outcome

The current branch completes a focused, human-oriented recovery of Maru's
management hierarchy and shared page framing, proves the first non-staff owner
journey from Registration into Workforce, and implements the first complete
owner-facing Workforce mutation slice: governed Position management with its
paired volunteer opportunity. It adds shared HTML/API commands, aggregate
evidence, and stopped-writer database enforcement without granting assignment
authority or pretending that availability and shifts already exist.

### Focused navigation and surfaces

- Administration now leads with durable Convention work. Convention tools,
  Organizations, Platform, and Specialist records are progressively disclosed
  according to the current account and scope.
- **Workforce** is now a durable task beside People and Registration desk. Its
  description and search vocabulary cover Departments, Positions, assignments,
  availability, shifts, and rota without exposing an unavailable control.
- **Find a task or record** reports task matches separately from authorized
  technical records and keeps Specialist records collapsed. Escape clears the
  query; search text is not persisted.
- Pin controls are available only after **Customize navigation** is opened.
  Pins still resolve and authorize on every request.
- My Maru and Administration use independent navigation projections and pins.
  My Maru leads with registration, applications, and schedule, then presents
  lower-frequency self-service links under **More from Maru**. Accounts that
  may work in both contexts receive one explicit surface switch.
- The organization/series/edition workspace trail is compact and exposes its
  selector only through **Change**.

### One page frame

- Converted server-rendered workflows use one H1 and one compact **Access**
  disclosure immediately after the heading. The disclosure names the resolved
  scope and policy while collapsed, then explains permitted actions and
  authority sources in place.
- The embedded Convention work client owns that same disclosure inside each
  active React view. The Django host suppresses its default copy there, so the
  page has one title, one access summary, and one `main` landmark.
- Shared page templates no longer repeat a second content title or place access
  policy above the task heading.
- At 1,100 CSS pixels and below, navigation is a closed overlay drawer. While
  open, background header, breadcrumb, and content are inert and hidden from
  the accessibility tree; Escape closes the drawer and returns focus. Above
  1,100 pixels the persistent sidebar remains.
- Embedded Convention work uses the Django host's edition selector as its only
  visible context control. If the host starts at foundation scope, the client
  posts its authorized initial edition through the existing context action
  before releasing scoped records.
- People, attendee, and access side workspaces now share one modal drawer:
  labelled `dialog`/`aria-modal`, initial close focus, Escape and Tab handling,
  background isolation and scroll locking, and return to the exact opener.

### Registration is oriented around the attendee

- The high-frequency task is now **Registration desk**. A bounded attendee
  queue with name/reference search, lifecycle filtering, count, pagination,
  empty/denied states, and preserved detail context appears before
  configuration.
- Narrow screens render each attendee as one labelled record card containing
  attendee, reference, admission, state, and an explicit open action. Desktop
  keeps the semantic table.
- The exact edition configuration is **Registration** and remains at the
  canonical Registration setup and account onboarding route. **Registration setup** from the desk opens that
  purpose-built workspace; **Capacity & waitlist** remains a distinct policy
  task.
- Setup guide links organization, series, edition, registration, access, and
  readiness to their exact purpose-built routes instead of technical model
  pages.
- Programme & schedule, Team inbox, and Live operations have one **Planned
  capabilities** panel labelled **Not available yet**. They are intentionally
  not links. Availability and Shifts now have a more useful truthful place in
  the Workforce sequence.

### Workforce connects implemented work without faking scheduling

- The owner-visible **Workforce** workspace consumes the existing strict,
  bounded exact-edition structure projection. It presents one ordered journey:
  Structure -> Positions -> Assignments -> Availability -> Shifts.
- Structure, Position responsibility/reporting/state, approved headcount,
  vacancies, and minimized active holders are current read capabilities.
  **Open structure** leads to canonical Department management. Authorized
  managers now receive **Manage positions** and direct Position actions; a
  view-only organizer retains the minimized read projection.
- Availability and Shifts are each labelled **Not available yet**, have no
  controls, and explain their future person-owned and transactional boundaries.
  The workspace never infers availability from assignment or treats a Position
  as scheduled work.
- Non-staff owners receive purpose-built continuation links only. They are not
  sent into inaccessible PositionAssignment model pages; staff with independent
  advanced-record access may use a clearly labelled temporary assignment link.
- Registration configuration now has one coherent Workforce handoff instead of
  several specialist links with unrelated permission behavior.

### Position management is governed and owner-facing

- [ADR 0075](../architecture/decisions/0075-governed-position-and-opportunity-management.md)
  and HR-012 define one versioned Position/opportunity aggregate beneath the
  exact edition structure. Organization, edition, Department, Position
  template, immutable RoleBundle issuance, code, and capacity codes are fixed
  at creation; title, purpose, headcount, reporting, and applicant-facing
  opportunity details are explicit complete replacements.
- Creation selects only a published organization template with valid historical
  role provenance and an active exact-edition Department. One transaction
  creates the planned Position, private draft opportunity, exact typed resource
  binding, audit, event, outbox, structure version, and retained organizer
  reason. Canonical retry keys make creation idempotent.
- The opportunity may move through draft, published, closed, republished, and
  finally withdrawn states. Publishing opens a planned Position but creates no
  application, assignment, participation, RoleAssignment, or capability grant.
- Closure is one-way and requires the current title plus a reason. It refuses
  active/proposed assignments, current direct reports, and current or future
  Position-scoped authority instead of silently deleting or revoking them.
- Organization structure shows recent reasons, and Position detail shows its
  own newest-first command history. Administrative rationale is therefore
  inspectable in the workflow it explains, not hidden in an unrelated log.
- Position and Volunteer opportunity specialist records are inspection-only.
  Browser and strict API adapters call the same commands, and Workforce
  migration `0010` rejects direct identity/scope mutation, invalid lifecycle or
  reporting transitions, deletion, and changed governed rows without exact
  receipt evidence.
- Server-rendered mutation failures now focus one programmatically focusable
  action summary across Registration setup, Organization structure, and
  Position management, while retaining field-local errors and entered values.
- The preserved recovery bootstrap now creates its initial Convention Chair
  Position through the same governed command. Its non-HTTP provenance exception
  is bounded to that exact empty structure state; legacy rows can begin truthful
  governed history at their first real change without an invented creation
  actor, version, or receipt.

### Truthful demonstration continuity

- Each configured synthetic demo edition now has one deterministic
  `RegistrationSetupControl` with `legacy_existing` origin and
  `legacy_unknown` provenance.
- This makes the canonical Registration reader usable in the educational
  fixture without inventing source digests, actors, command receipts, or
  Registration setup and account onboarding writer-cutover evidence. Seeding
  remains idempotent and local-only.

## Established repository and product baseline

- PR #15, **Curate newcomer documentation and fictional examples**, merged to
  protected `main` as exact commit `2b78934` on 2026-08-23. GitHub Pages run
  `32624208484` then built and deployed that exact commit successfully. The
  previous handoff's pending hosted-acceptance and Pages statements are closed.
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
  registration and profile slices, typed applications, catalog and admission
  commerce, charity, venue, and bounded Logistics capabilities. Consult the
  production-consolidation ledger before treating any slice as complete.

## Decisions

- ADR 0075 accepts governed Position and volunteer-opportunity management as
  one exact-edition structure aggregate. Assignment proposal and activation,
  onboarding evidence, availability, and shifts remain separate workflows.
- The shell and page-frame work implements ADR 0039's one-shell boundary,
  ADR 0049's coherent personal/access presentation, ADR 0055's task-first
  responsive direction, and ADR 0028's separation of Workforce meaning from
  authorization.
- Living documentation now uses purpose names such as **Organization
  structure**, **Position management**, and **Registration setup and account
  onboarding**. Numeric filename prefixes remain only for stable ordering and
  links; accepted ADRs, append-only checkpoints, and frozen ledgers retain
  historical wording.
- UX-020, UX-027, and UX-029 now explicitly require page-local access
  placement, personal/admin separation, progressive pin customization,
  task-versus-technical search results, inert drawer backgrounds, truthful
  planned-capability placement, and labelled narrow-screen record cards.
- **Registration desk**, **Registration**, and **Capacity & waitlist** are
  deliberately different tasks. Naming does not create aliases, new authority,
  or a second registration writer.
- Unimplemented modules receive a labelled roadmap home, not disabled
  navigation rows scattered through the product and not links that fail.
- Availability and Shifts may occupy labelled places in the Workforce sequence,
  but they do not become available until HR-009/SCH-001/SCH-005 receive accepted
  transactional, privacy, authorization, and recovery contracts.
- Workforce uses the strict structure projection for orientation and the new
  purpose-built Position commands for authorized mutation. It does not silently
  implement assignment approval, person availability, or scheduling.
- Legacy demo setup controls preserve unknown provenance. They are reader
  continuity only and do not satisfy Registration setup and account onboarding readiness or writer cutover.

## Verification for this working outcome

Completed locally:

- Ruff and pydoclint checks passed; mypy found no issues across 353 source
  files; migration drift and repository whitespace checks passed;
- governed Position command/API/HTML, exact-edition lock, service, inspection-
  only admin, and clean-onboarding focus: 27 passed in 122.23 seconds;
- broad Workforce integration/unit regression gate, including authorization,
  tenant/edition scope, receipts, migrations, runtime readiness, onboarding,
  assignments, shifts, and availability: 361 passed with 3,916 unrelated tests
  deselected in 1,384.74 seconds;
- exact structure/readiness catalog and tamper matrix: 61 passed; the shared
  validation-focus asset plus Position HTML follow-up: 7 passed in 58.68
  seconds;
- current expanded Workforce projection/Department management plus
  shell/access/responsive/navigation/host gate: 65 passed in 63.39 seconds;
- affected account, applications, navigation, representation, convention-series and edition record,
  staff-console host, and unified-routing PostgreSQL integration tests:
  78 passed;
- complete synthetic demo seed/idempotency and canonical Registration reader:
  1 passed in 66.93 seconds;
- staff-console TypeScript check: passed;
- staff-console Vitest: 28 passed, including context synchronization, modal
  focus/Escape restoration, the five-stage Workforce journey, owner-safe links,
  non-disclosing denial and oversized-structure states, and axe scans of
  Registration and Workforce;
- production Vite build: passed; generated host assets refreshed;
- OpenAPI regenerated and validated with zero schema errors; its 18 existing
  enum-name collision warnings remain visible; generated TypeScript API types
  were refreshed;
- Django system check: passed with the expected local-only `identity.W001`
  warning because invitation-delivery encryption is intentionally unconfigured;
  migration drift check reports no changes;
- documentation policy: 322 Markdown files and 204 requirement identifiers;
- repository whitespace validation: passed;
- fresh warning-fatal Sphinx/AutoAPI build using the public Pages base URL:
  passed;
- authenticated browser review with fictional data: the non-staff Convention
  Chair's host context converged on MaruCon 2026; Registration rendered one H1,
  one `main`, labelled mobile attendee cards, and no 390-pixel overflow; the
  attendee modal received close focus, isolated the background, closed on
  Escape, and returned focus; Registration handed off to Workforce; all five
  stages, current Position/vacancy data, no staff-only links, no overflow, and
  the canonical Department management structure continuation passed;
- authenticated Convention Chair Chrome review of Position management: the
  purpose-named breadcrumbs, overview, detail, organizer/opportunity forms,
  authority explanation, and legacy-history empty state rendered with one H1,
  one `main`, and no desktop horizontal overflow. A deliberately invalid update
  changed no data, exposed summary plus field errors, and focused the summary.

## Known risks and incomplete work

- This is focused owner/read browser evidence, not the complete UX-029 matrix.
  The 320, 768, 958, 1,024, 1,280, and 1,920-pixel states, 200 percent zoom,
  complete keyboard paths, representative screen-reader behavior, every
  failure/empty/mutation state, and mutation-role rehearsals remain release
  gates. Automated axe coverage now guards the two focused React views but does
  not replace those rendered checks.
- Registration desk, the Workforce sequence, and Position management are the
  first high-frequency journeys reoriented around human tasks. Purpose-built
  assignment proposal/approval, person-owned availability, shifts, Venues,
  Logistics, applications, commerce, and specialist management journeys still
  need the same state and browser treatment.
- The canonical Registration setup reader and substantial lifecycle core exist, but direct
  writer retirement, readiness activation, complete builder parity,
  representative recovery/concurrency, and production cutover remain open.
- Programme, shifts, inbox, and live operations are planned product areas, not
  available capabilities.
- Representative deployment, stopped-writer cutover, restore/PITR, worker
  supervision, provider certification, load, telemetry,
  legal/privacy/finance/safeguarding governance, and operator training remain
  production gates.

## Smallest sensible next actions

1. Specify and implement the owner-safe assignment journey from one current
   Position: select a known person, show onboarding prerequisites, propose with
   reason and effective interval, then require a genuinely separate authorized
   approver session before activation. Do not promote a specialist model form or
   same-session identity selector as dual control.
2. Design person-owned Availability and transactional Shifts against
   HR-009/SCH-001/SCH-005, including privacy, overlap, rest, demand, claim,
   confirmation, completion, locking, audit, and recovery before enabling any
   control in the current Workforce stages.
3. Complete UX-029's remaining width/zoom, screen-reader, empty/failure, and
   mutation-role matrix for Registration, Workforce, and Organization structure.
4. Apply the same page frame and task orientation to Venues and Logistics,
   prioritizing receiving, custody, schedules, and exceptions over model nouns.
5. Design Programme & schedule, Team inbox, and Live operations only through
   accepted requirements and authorization contracts; replace their roadmap
   labels with links only when an end-to-end workflow exists.
6. Continue the separate deployment/recovery/governance gates before proposing
   a release candidate.

## Resume instructions

Read `AGENTS.md`, this file, `ROADMAP.md`, the production-consolidation
ledger, the management-shell, Organization structure, Position management,
and Registration setup contracts, and ADRs 0019/0028/0039/0049/0055/0075.
Use only synthetic data. Preserve
organization and edition scope, authorize before disclosure, keep My Maru
separate from Administration, and do not confuse a visible destination,
selected context, demo control, or successful local browser pass with
authority, writer cutover, release, or production approval.
