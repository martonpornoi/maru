# Initial Staff Console checkpoint

Date: 2026-07-27  
Requirements: UX-001, UX-002, UX-003, UX-004, UX-006, UX-007, UX-008, INT-001  
Decision: ADR 0006

## Outcome

Maru now has its first purpose-built Staff Console at `/staff/`. It is a
separate React/TypeScript/Vite application using OpenAPI-generated contract
types, hosted by Django during bootstrap deployment.

The MaruCon 2026 cockpit uses real fixture data for edition context, countdown,
lifecycle, person count, roles, languages, and currencies. The People workspace
supports server-side name, role, status, and pagination controls plus a
context-preserving person panel. It exposes only the staff-summary field
ceiling. An account without that capability receives no names, filters, or
counts.

Unimplemented action-center and module destinations are visibly labeled as
future foundation work; no invented task, registration, shift, or readiness
data is presented as operational fact.

## Security and data boundary

- Local login accepts active platform accounts without granting Django admin
  access.
- API policy remains authoritative and deny-by-default.
- People queries constrain organization and edition before target lookup.
- Staff list/detail allow, denial, and unavailable outcomes are audited.
- Search excludes email and output excludes contact, contribution, membership,
  credential, and internal participation identifiers.
- Unknown and cross-edition/cross-tenant targets do not disclose existence.

## Verification

- Nine frontend tests passed, including policy-denial suppression.
- Backend staff-console/auth and participation endpoint focused suites passed.
- Frontend typecheck and production build passed.
- Ruff and strict mypy passed after integration.
- Real-browser QA loaded the 40-person MaruCon 2026 fixture, exercised search and
  the person side panel, checked horizontal overflow at 1280 px, and confirmed
  no runtime console errors.

The complete repository gate is recorded in `CURRENT.md`.

## Limits and recovery

The local session form is not the final identity-provider design. Action
projection, global search, inbox, saved views, command palette, module
registration, and mutations remain V03 work. Rebuilding the tracked host assets
is deterministic through the pnpm lock and `pnpm run build`; Django can continue
serving the previous assets if a frontend build fails before replacement.
