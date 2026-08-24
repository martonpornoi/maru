# Embedded Convention work

Status: API-backed workflow mounted in the focused unified shell with shared
page framing, an owner-rehearsed Registration desk, accessible modal drawers,
and a read-oriented Workforce journey; complete mutation-role, width/zoom,
deployment, and production evidence remains gated
Last updated: 2026-08-23

## Purpose and requirements

This module carries forward the pre-reset API-backed Convention work implementation
under ADRs 0006, 0023, 0026, and 0027. ADR 0039 selects its record-oriented
grammar and mounts it inside the one `/admin/` shell without making
its client the domain authority. Its source, generated client, tests, and
backend contracts remain evidence; current route and authorization tests now
cover the changed default resolver.

Source lives in `frontends/staff-console`. The default `maru.urls`
configuration serves it at `/admin/workspace/`, embedded in the administration
base template. Business behavior and authorization remain in the versioned
API. The permission-filtered Django index stays at `/admin/`, purpose-built
platform records use `/admin/platform/`, and existing model routes remain below
`/admin/`. `/manage/`, `/staff/`, and `/admin/records/` are not alternate entry
points.

The current backend verifies its route, authorization, and sidebar boundaries;
the current frontend passes type checking, 28 Vitest tests, production build,
focused automated axe checks, and an owner-role 390-pixel smoke without console
errors or horizontal overflow. The final consolidated suite and coverage gate
now pass. Complete width/zoom, representative screen-reader, failure-state,
mutation-role, recovery/deployment, and production-owner evidence remain
release gates.

The shell uses Maru's canonical navy, gold, and ivory platform identity and
owned square mark. The source bundle repeats the documented palette so the
standalone Vite development server works without a Django template; automated
checks keep those anchors aligned with `maru.core`. Convention-owned annual
public clients may use independent seasonal themes.

## Selected interaction grammar and preserved workflows

- local session sign-in for any active account, followed by policy-filtered
  shell content;
- active-edition selection with remembered context;
- a safe empty-workspace state for every account without current convention
  authority, plus exact self-service governance invitations;
- one collapsible administration sidebar for Convention work and specialist
  records, with no nested React sidebar or duplicate workspace selector;
- host-owned embedded edition context: if no host edition is selected, the
  client submits its authorized initial edition through the existing context
  form before releasing scoped records;
- one page-local compact **Access** disclosure after each active view heading,
  with the Django host suppressing its default copy for the embedded workspace;
- record-oriented inner pages whose spacing, forms, tables, buttons, and
  responsive behavior match specialist record pages;
- a distinct home-page Forms section linking attendee registration,
  staff-assisted intake, volunteer applications, and onboarding documents;
- an ordered setup guide that links low-frequency organization, series,
  edition, registration, access, and readiness records without pretending to
  be a completion tracker;
- an edition lifecycle panel with current state, valid next states,
  consequences, reason, terminal-action acknowledgement, and capability-aware
  denial;
- a capability-scoped edition closeout readiness review for privacy, finance,
  operations, security, and safeguarding evidence; the operator enters only a
  human evidence reference and review summary while Maru supplies scope,
  reviewer, and server time;
- contextual **Manage access** in the workflow toolbar and administration
  sidebar, with exact-person sharing, familiar convention groups, recommended
  groups by page, optional expiry, reason, independent approval, atomic
  replacement, and immediate reasoned removal;
- human display names, emails, labels, slugs, and references in primary UI
  instead of UUID strings;
- Today overview with real edition lifecycle, dates, time zone, language,
  currency, participation count, and role distribution;
- current account role labels;
- a typed action center for registration configuration review and
  arrival-ready Front Desk work;
- role-aware denial when staff People summaries are unavailable;
- no duplicate Organization structure destination: the shared Django sidebar
  links the exact edition to canonical Department management instead;
- **Workforce**, which reads that exact Organization structure projection and connects
  Structure, Positions, Assignments, Availability, and Shifts in one ordered
  owner-safe journey; authorized managers continue into purpose-built Position
  creation/edit/opportunity/closure, while the last two stages are explicitly
  unavailable and have no controls;
- People search, capacity/status filters, bounded pagination, and counts;
- a side person workspace that preserves the current list and filter context;
- one shared modal-drawer interaction for person, attendee, and access detail,
  with labelled dialog semantics, initial close focus, Escape, Tab containment,
  inert/accessibility-hidden background, scroll locking, and focus return;
- `My registration`, with edition-defined products, conditional questions,
  purpose/classification disclosure, payment state, entitlements, and personal
  operational timeline, plus attendee-writable post-submission profile
  extensions;
- **Registration desk**, with a bounded attendee-first name/reference search,
  lifecycle filter, count, pagination, preserved detail drawer, check-in,
  staff-assisted registration with explicit missing-account creation, and
  one coherent handoff to the Workforce journey;
- lower-frequency registration provenance, template and prior-edition copy,
  review/activation, and template publication after the service queue, plus a
  direct **Registration setup** link to the canonical edition-owned workspace;
- a capability-scoped profile-media queue with audited previews, an exact-file
  explanation, mandatory review reason, and approve/reject actions;
- `Reports & badges`, with confirmed/checked-in attendance totals, country and
  authoritative attendee-level breakdowns, badge-data preview, search/filter
  controls, pagination, and an audited minimized CSV download;
- `Security history`, with the signed-in account's security-history projection;
- concise purpose-and-example guidance directly below every active page title,
  including empty, denied, and failure states;
- semantic headings, labels, table structure, skip link, focus indicators,
  reduced-motion treatment, and responsive navigation; and
- one setup-guide **Planned capabilities** panel for Programme & schedule,
  Team inbox, and Live operations, each labelled **Not available yet** and
  rendered without a dead link. Availability and Shifts now occupy the same
  truthful state inside Workforce, where their prerequisites are visible.

The initial host uses the built-in local email/password verifier. It is a
bootstrap identity path, not the production identity-provider or recovery
decision.

## API boundary

The frontend generates TypeScript types from checked-in `openapi.yaml` and uses:

- `GET /api/v1/me/context`;
- `GET /api/v1/me/security-history`;
- `GET /api/v1/organizations/{organization_id}/editions/{edition_id}/participations`;
- `POST /api/v1/organizations/{organization_id}/editions/{edition_id}/transition`;
- the edition-scoped access workspace and assignment routes documented in
  [`authorization.md`](authorization.md);
- the edition-scoped closure-readiness and readiness-gate review routes
  documented in [`events.md`](events.md);
- the edition-scoped registration configuration, self-service, staff-service,
  check-in, attendee-reporting, badge-export, and action APIs documented in
  [`registration.md`](registration.md); and
- the public opportunity, volunteer application, and self-service agreement
  APIs documented in [`workforce.md`](workforce.md); and
- the existing session/CSRF boundary.

The API remains authoritative. Client navigation and denial states improve
clarity but never grant access. People results contain exactly account ID,
display name, participation status, and active/proposed capacity labels.
The selected edition is working context, not proof of authority.

The generated schema contains the strict workforce structure GET plus template
application and Department create/update/retire/delete operations for supported
API consumers. Template application and creation require a caller-supplied
canonical UUID `Idempotency-Key`; generated helpers retain rather than invent
that retry identity. The DELETE operation has a required JSON body. The React
client now consumes the GET in a `workforce` task destination but still does
not declare a duplicate `structure` destination or support the retired
`?view=structure` route. The canonical Department browser writer remains the
server-rendered Department management route and same-shell child forms. The shared holder
projection omits the login handles that the retired duplicate view exposed.

## Development

Use Node 22.12 or newer and pnpm:

```powershell
cd frontends/staff-console
pnpm install --frozen-lockfile
pnpm run generate:api
pnpm run typecheck
pnpm run test
pnpm run build
```

The build writes fixed host assets to
`src/maru/core/static/staff-console/app.js` and `app.css`. Restart a Django
development process that was already running before this static directory was
first created.

For a Vite development loop, run `pnpm dev`; `/api`, `/accounts`, `/admin`,
and `/static` proxy to Django at `127.0.0.1:8000`.

## Verification

Frontend tests cover active-edition choice, truthful Today content,
tenant/edition-scoped People search, context-preserving person detail, model
helpers, convention-defined conditional questions, typed actions, and complete
count/filter suppression after policy denial. They also cover loading a pending
profile image and sending a reasoned approval command. They also cover the
Reports orientation, country metrics, attendee labels, and export path.
Navigation tests cover the embedded mode without a second global navigation or
workspace selector, server-context synchronization before scoped rendering, one
access summary after the active H1, the attendee queue before setup, its query
parameters and mobile labels, modal focus/Escape/background behavior, the
ordered guide, the separate Forms area, absence of visible UUIDs, the
exact-email/independent-approver access interaction, and readiness review
without manual scope, reviewer, or timestamp fields. Workforce tests cover all
five stages, current positions and active holders, exact structure routing,
non-staff specialist-link exclusion, non-disclosing denial, and automated axe
analysis for both the Registration and Workforce views.
Backend tests cover session login, anonymous redirect, staff field
minimization, tenant/edition isolation, unknown targets, registration
lifecycle, report denial, CSV minimization/formula neutralization, and
sensitive-read audit.

The MaruCon 2026 fixture was also walked in a real browser at desktop and
390-pixel mobile widths. The action center opened real work, Registration showed
edition/template provenance and Front Desk state, the attendee form revealed a
conditional fursuit question, and no runtime errors or horizontal overflow
remained.

The focused 2026-08-23 walkthrough additionally proves that Registration desk
loads the attendee queue before configuration, lifecycle labels use human
wording, narrow rows become complete labelled cards, canonical Registration is
readable from the fictional fixture's honest legacy setup control, and setup
links resolve to the exact organization/series/edition routes. It also checks
one H1, one `main`, one page-local Access disclosure, the 1,100/1,101-pixel
navigation breakpoint, Escape/focus return, and the absence of page-level
horizontal overflow at the 390-pixel viewport. This remains focused evidence,
not the complete UX-029 acceptance matrix.

The later owner-role pass signs in as the fictional non-staff MaruCon
Convention Chair and verifies Registration through arrival at 390 CSS pixels.
The host context converges on MaruCon 2026 without a second React selector; the
attendee modal receives close focus, exposes `dialog`/`aria-modal`, isolates the
background, closes on Escape, and returns to the exact attendee. The same pass
follows the Registration handoff into Workforce, confirms the complete five-
stage sequence and current vacancy projection, excludes staff-only record
links, and reaches canonical Organization structure. The focused frontend gate
is now 27 passing tests including axe checks; 28 related shell/navigation host
tests, TypeScript, and the production build also pass.

The original Django administration under `/admin/` uses the same orientation
pattern on sign in, index, application, list, add, and change pages.
Model-specific copy keeps
foundation records understandable without changing their authorization or
lifecycle rules. Its persistent convention-workspace selector was verified
with MaruCon 2027: edition-owned lists and choices stayed focused, eligible
registration sources remained explicitly reusable, mobile layout had no
horizontal overflow, and the browser reported no runtime errors.

Current route-collision, shell-permission, and frontend evidence now passes:
active scoped non-staff accounts can use Convention work, inactive or unscoped
accounts cannot, and specialist records still require Django staff/model
permission. Type checking, 28 Vitest tests, and the production build pass. A
709-test backend run had one stale administration-home expectation; that exact
test passed after **Manage access** was restored. Desktop and 390-pixel smoke
now also pass without console errors or horizontal overflow. The complete
consolidated suite/coverage rerun after all later integrity work now passes;
keyboard and automated accessibility, complete visual states, mutation-role,
recovery/deployment, and owner evidence remain required.

After removing the duplicate structure destination, TypeScript type checking,
20 Vitest tests, and the production Vite build pass. OpenAPI regeneration
retains the workforce structure types for API consumers without reintroducing
the React page.

The final canonical current-tree repository gate passed all 4,067 tests in
15,558.23 seconds (4:19:18) at 90.78 percent coverage. A later authenticated
read-only rehearsal covered the Logistics workspace and Stage Tech receiving
projection at 1920- and 390-pixel widths. Each rendered exactly one `main`
landmark and one H1, had no horizontal overflow, and exposed no mutation
controls to the rehearsed role. This is read-only responsive evidence, not
mutation-role, keyboard, automated-accessibility, recovery, deployment, or
production acceptance.

## Limitations

Inbox, global object search, command palette, arbitrary saved views, XLSX/background
exports, capability manifest, module
registration contract, production identity integration, and non-registration
actions remain V03 work. The Forms section currently contains implemented
registration/workforce entry points; a generic module-registration contract
will let future form modules add cards without editing the shell. Registration
draft content is edited in specialist records until complete visual builders
exist. Department management belongs to the server-rendered Organization
structure workflow, not a return to the retired React destination. Workforce
uses the strict projection for orientation and links authorized managers to
server-rendered Position management. Purpose-built assignment proposal and
independent approval, person-owned availability, and transactional shifts
remain incomplete, as does the wider Convention work operating surface.
