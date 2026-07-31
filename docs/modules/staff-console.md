# Embedded Convention work

Status: API-backed convention workflows embedded in the original `/admin/`
shell
Last updated: 2026-07-31

## Purpose and requirements

Convention work is Maru's authenticated planning, setup, and operations area
under ADR 0006, ADR 0023, ADR 0026, and ADR 0027. It implements UX-001 through
UX-012, IDN-009, HR-010, and INT-001 with a coherent edition workspace while retaining
specialist Django records in the same administration product.

Source lives in `frontends/staff-console`. Django serves the production bundle
inside the original Django administration shell at `/admin/workspace/`.
Business behavior and authorization remain in the versioned API. The original
permission-filtered Django index stays at `/admin/`, and existing model routes
remain below it. `/manage/`, `/staff/`, and `/admin/records/` are not alternate
entry points.

The shell uses Maru's canonical navy, gold, and ivory platform identity and
owned square mark. The source bundle repeats the documented palette so the
standalone Vite development server works without a Django template; automated
checks keep those anchors aligned with `maru.core`. Convention-owned annual
public clients may use independent seasonal themes.

## Implemented experience

- local session sign-in for any active platform account;
- active-edition selection with remembered context;
- a safe empty-workspace state for every account without convention
  participation, with the administration home available to Django staff;
- a guarded workspace-less-superuser Setup guide ceremony that establishes the first
  convention controllers and Chair through the existing one-shot service,
  requiring current password, exact organizer slug, separate Chair, reason,
  and auditable scope;
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
- an edition-scoped **Organization structure** page with nested departments,
  positions, several holders, login handles, and each person's other roles;
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
- `GET|POST /api/v1/management/convention-bootstrap`;
- `GET /api/v1/organizations/{organization_id}/editions/{edition_id}/participations`;
- `GET /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/structure`;
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

The Danube 2026 fixture was also walked in a real browser at desktop and
390-pixel mobile widths. The action center opened real work, Registration showed
edition/template provenance and Front Desk state, the attendee form revealed a
conditional fursuit question, and no runtime errors or horizontal overflow
remained.

The original Django administration under `/admin/` uses the same orientation
pattern on sign in, index, application, list, add, and change pages.
Model-specific copy keeps
foundation records understandable without changing their authorization or
lifecycle rules. Its persistent convention-workspace selector was verified
with Danube 2027: edition-owned lists and choices stayed focused, eligible
registration sources remained explicitly reusable, mobile layout had no
horizontal overflow, and the browser reported no runtime errors.

## Limitations

Inbox, global search, command palette, arbitrary saved views, XLSX/background
exports, capability manifest, module
registration contract, production identity integration, and non-registration
actions remain V03 work. The Forms section currently contains implemented
registration/workforce entry points; a generic module-registration contract
will let future form modules add cards without editing the shell. Registration
draft content and workforce structure are edited in specialist records until
complete visual builders exist. Convention work is not yet a complete
convention operating surface.
