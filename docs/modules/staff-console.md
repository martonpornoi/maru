# Embedded Convention work

Status: API-backed workflow mounted in the unified shell and accepted in the
canonical current tree; responsive read-only smoke evidence passes while
mutation-role, accessibility, deployment, and production evidence remain gated
Last updated: 2026-08-11

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
the current frontend passes type checking, 20 Vitest tests, production build,
and desktop/390-pixel smoke without console errors or horizontal overflow.
The final consolidated suite and coverage gate now pass. Keyboard, automated
accessibility, complete failure-state, mutation-role, recovery/deployment, and
owner evidence remain release gates.

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
  links the exact edition to canonical Page 9a.1 instead;
- People search, capacity/status filters, bounded pagination, and counts;
- a side person workspace that preserves the current list and filter context;
- `My registration`, with edition-defined products, conditional questions,
  purpose/classification disclosure, payment state, entitlements, and personal
  operational timeline, plus attendee-writable post-submission profile
  extensions;
- `Registration`, with registration provenance, template and prior-edition copy,
  review/activation, template publication, minimized service queue, check-in,
  staff-assisted registration with explicit missing-account creation, and
  direct workforce onboarding links;
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
- explicit disabled destinations that make the intended information
  architecture visible without pretending those modules exist.

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
that retry identity. The DELETE operation has a required JSON body. This React
client still does not declare a `structure` destination, fetch that projection,
or support the former `?view=structure` route. The canonical browser experience
is the server-rendered Page 9a.1 route and same-shell child forms. Its holder
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
workspace selector,
the ordered guide, the separate Forms area, absence of visible UUIDs, the
exact-email/independent-approver access interaction, and readiness review
without manual scope, reviewer, or timestamp fields.
Backend tests cover session login, anonymous redirect, staff field
minimization, tenant/edition isolation, unknown targets, registration
lifecycle, report denial, CSV minimization/formula neutralization, and
sensitive-read audit.

The MaruCon 2026 fixture was also walked in a real browser at desktop and
390-pixel mobile widths. The action center opened real work, Registration showed
edition/template provenance and Front Desk state, the attendee form revealed a
conditional fursuit question, and no runtime errors or horizontal overflow
remained.

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
permission. Type checking, 20 Vitest tests, and the production build pass. A
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

Inbox, global search, command palette, arbitrary saved views, XLSX/background
exports, capability manifest, module
registration contract, production identity integration, and non-registration
actions remain V03 work. The Forms section currently contains implemented
registration/workforce entry points; a generic module-registration contract
will let future form modules add cards without editing the shell. Registration
draft content is edited in specialist records until complete visual builders
exist. Department management now belongs to the server-rendered Page 9a.1
workflow, not a return to the retired React destination. Page 9b Position
management and the wider Convention work operating surface remain incomplete.
