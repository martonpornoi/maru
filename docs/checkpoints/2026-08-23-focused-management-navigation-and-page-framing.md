# Checkpoint: Focused management navigation and page framing

- Date: 2026-08-23
- Phase: Production consolidation and management-experience recovery
- Related requirements: UX-019, UX-020, UX-026, UX-027, UX-029, REG-001
- Related ADRs: 0039, 0049, 0055

## Outcome

Maru's canonical management shell now presents a focused task hierarchy rather
than exposing product workflows, platform setup, personal work, and technical
records at equal weight. Personal and administrative destinations are separate,
technical records remain available through a searchable progressive gateway,
and converted pages use one title followed by one compact computed-access
summary.

Registration is oriented around the person at the desk. The high-frequency
**Registration desk** starts with a searchable, filterable, paginated attendee
queue; edition configuration remains the canonical **Registration** record and
capacity policy remains **Capacity & waitlist**. At narrow widths, attendee rows
become labelled cards instead of requiring horizontal panning.

The setup guide now links to exact purpose-built organization, series, edition,
registration, access, and readiness routes. Planned programme, shift, inbox,
and live-operation areas have one truthful non-interactive home rather than
dead links.

## Decisions

- Apply ADRs 0039, 0049, and 0055; do not add another shell, writer, route
  family, authorization policy, or ADR.
- Search leads with matched tasks and reports authorized technical records
  separately. Specialist matches stay collapsed until requested.
- Pin actions are customization and remain hidden until **Customize
  navigation** is opened.
- My Maru and Administration project independent authorized item sets and pins,
  with one explicit surface switch for accounts entitled to both.
- Place one compact Access disclosure immediately after each page heading.
  Embedded Convention work renders its own effective-access projection so the
  Django host cannot duplicate it before the React root.
- Treat **Registration desk**, **Registration**, and **Capacity & waitlist** as
  different user tasks even though they cooperate over the same edition.
- Give unavailable product areas one labelled roadmap panel and no link until
  their workflow and authorization contracts are implemented.
- Preserve fixture provenance honestly: canonical Registration reads directly
  seeded configurations through `legacy_existing`/`legacy_unknown` controls
  and never fabricates Page 10 command evidence.

## Changed areas

- Core navigation registry, grouping, terminology, search presentation,
  progressive pin controls, personal/admin filtering, and responsive drawer
  background isolation.
- Shared Django administration context selector, title/access mount, help
  framing, Administration home, My Maru home, and all affected purpose-built
  workflow templates.
- Embedded Convention work headings, effective-access placement, Registration
  desk queue/filter/pagination, mobile record-card treatment, setup links, and
  planned-capability panel.
- Synthetic demo fixture and integration coverage for deterministic honest
  registration setup controls.
- Product requirements, information architecture, shell and Page 10 contracts,
  Core/Staff Console/Demo module guidance, roadmap, and current handoff.

## Verification

- Selected Ruff checks over changed Python and regression files: passed.
- Focused shell/access/responsive unit tests: 13 passed.
- Affected PostgreSQL integration tests across account step-up, applications,
  navigation/My Maru, representation, Pages 5–7, Staff Console host, and unified
  routing: 78 passed in 71.85 seconds.
- Complete synthetic demo seed/idempotency and canonical Registration reader:
  1 passed in 66.93 seconds.
- Staff Console TypeScript check and production build: passed.
- Staff Console Vitest: 21 passed.
- Django system check: passed with expected local-only `identity.W001`
  invitation-encryption warning.
- Authenticated fictional-data browser review: task/technical search hierarchy,
  Escape clearing, pin customization, My Maru/Admin separation, compact
  context, exact setup links, truthful planned panel, canonical Registration,
  human lifecycle labels, one H1/`main`/Access disclosure, the
  1,100/1,101-pixel breakpoint, Escape/focus return, and a no-overflow
  390-pixel Registration desk passed.
- Documentation policy: 318 Markdown files and 204 requirement identifiers;
  passed.
- Repository whitespace validation: passed.
- Fresh warning-fatal Sphinx/AutoAPI build using the public Pages base URL:
  passed.

## Data, migration, and deployment notes

No migration or production-data operation is introduced. The local-only
fixture creates six deterministic setup controls, one for each configured
fictional edition. Existing compatible controls are reused; incompatible
reserved identity or provenance fails closed. The controls expose legacy
reader continuity only and do not make the demo fixture a Page 10 command
writer.

The earlier public-documentation outcome is now hosted: PR #15 merged as exact
main commit `2b78934`, and GitHub Pages run `32624208484` deployed that exact
commit successfully. This management branch has no hosted acceptance yet.

## Known risks and incomplete work

- The complete UX-029 width/zoom, keyboard, automated-accessibility,
  screen-reader, mutation-role, state, and owner matrix remains open.
- Workforce positions/assignments/shifts, Venues, Logistics, applications, and
  other management journeys are not yet converted to the same task hierarchy.
- Page 10 writer retirement, readiness, complete builder parity, concurrency,
  recovery, and production cutover remain independent gates.
- Programme, shifts, inbox, and live operations are intentionally unavailable.
- Deployment, restore/PITR, provider, worker, load, privacy/legal/finance/
  safeguarding governance, training, and release evidence remain open.

## Recommended next actions

1. Conduct an owner-role registration-through-arrival rehearsal and close the
   complete responsive/zoom/keyboard/accessibility/state matrix.
2. Convert Workforce structure -> positions -> assignments ->
   shifts/availability as the next coherent operational journey.
3. Apply the same page-frame and task-first treatment to Venues and Logistics.
4. Keep unavailable product areas non-interactive until accepted end-to-end
   contracts make them real.
