# Staff Console

Status: V03 interaction foundation with registration vertical  
Last updated: 2026-07-29

## Purpose and requirements

The Staff Console is Maru's first separate frontend application under ADR 0006.
It begins UX-001 through UX-009 and INT-001 with a coherent edition workspace
instead of extending Django admin into the product interface.

Source lives in `frontends/staff-console`. Django serves the production bundle
at `/staff/` during the bootstrap deployment phase. Business behavior and
authorization remain in the versioned API.

The shell uses Maru's canonical navy, gold, and ivory platform identity and
owned square mark. The source bundle repeats the documented palette so the
standalone Vite development server works without a Django template; automated
checks keep those anchors aligned with `maru.core`. Convention-owned annual
public clients may use independent seasonal themes.

## Implemented experience

- local session sign-in for any active platform account;
- active-edition selection with remembered context;
- transfer of the selected edition into bootstrap administration when an
  administrator follows the Bootstrap admin action;
- direct fallback to `/admin/` when a Django staff account has no convention
  participation to form a Staff Console workspace;
- Today overview with real edition lifecycle, dates, time zone, language,
  currency, participation count, and role distribution;
- current account role labels;
- a typed action center for registration configuration review and
  arrival-ready Front Desk work;
- role-aware denial when staff People summaries are unavailable;
- People search, capacity/status filters, bounded pagination, and counts;
- a side person workspace that preserves the current list and filter context;
- `My registration`, with edition-defined products, conditional questions,
  purpose/classification disclosure, payment state, entitlements, and personal
  operational timeline;
- `Commerce`, with registration provenance, template and prior-edition copy,
  review/activation, template publication, minimized service queue, check-in,
  staff-assisted registration with explicit missing-account creation, and
  direct workforce onboarding links;
- a capability-scoped profile-media queue with audited previews, an exact-file
  explanation, mandatory review reason, and approve/reject actions;
- `Reports`, with confirmed/checked-in attendance totals, country and
  authoritative attendee-level breakdowns, badge-data preview, search/filter
  controls, pagination, and an audited minimized CSV download;
- `Security`, with the signed-in account's security-history projection;
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

For a Vite development loop, run `pnpm dev`; `/api`, `/accounts`, and `/staff`
proxy to Django at `127.0.0.1:8000`.

## Verification

Frontend tests cover active-edition choice, truthful Today content,
tenant/edition-scoped People search, context-preserving person detail, model
helpers, convention-defined conditional questions, typed actions, and complete
count/filter suppression after policy denial. They also cover loading a pending
profile image and sending a reasoned approval command. They also cover the
Reports orientation, country metrics, attendee labels, and export path.
Backend tests cover session login, anonymous redirect, staff field
minimization, tenant/edition isolation, unknown targets, registration
lifecycle, report denial, CSV minimization/formula neutralization, and
sensitive-read audit.

The Danube 2026 fixture was also walked in a real browser at desktop and
390-pixel mobile widths. The action center opened real work, Commerce showed
edition/template provenance and Front Desk state, the attendee form revealed a
conditional fursuit question, and no runtime errors or horizontal overflow
remained.

Bootstrap Django administration uses the same orientation pattern on its sign
in, index, application, list, add, and change pages. Model-specific copy keeps
foundation records understandable without changing their authorization or
lifecycle rules. Its persistent convention-workspace selector was verified
with Danube 2027: edition-owned lists and choices stayed focused, eligible
registration sources remained explicitly reusable, mobile layout had no
horizontal overflow, and the browser reported no runtime errors.

## Limitations

Inbox, global search, command palette, arbitrary saved views, XLSX/background
exports, capability manifest, module
registration contract, production identity integration, and non-registration
actions remain V03 work. Registration draft content and workforce structure
are edited in bootstrap admin until complete visual builders exist. The Staff
Console is not yet a complete convention operating surface.
