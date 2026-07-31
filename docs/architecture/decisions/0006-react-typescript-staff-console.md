# ADR 0006: React and TypeScript for the Staff Console

- Status: Partially superseded by ADR 0023 (separate visible console only)
- Date: 2026-07-27
- Requirements: UX-001, UX-002, UX-003, UX-004, UX-006, UX-007, UX-008,
  INT-001

## Context

ADR 0001 requires separately replaceable frontend applications over Maru's
versioned API. The first such application is the Staff Console. It needs a
persistent organization and edition context, role-aware navigation, dense but
accessible operational lists, and progressively richer workspaces without
turning Django templates or Django admin into the product interface.

The project also needs a small contributor-friendly toolchain and a way to
detect drift between the OpenAPI contract and frontend assumptions.

## Decision

Build the Staff Console as a separate React and TypeScript application under
`frontends/staff-console`, bundled with Vite.

- Generate TypeScript API contract types from the checked-in `openapi.yaml`.
- Keep network access behind a small typed client boundary.
- Use semantic HTML and native controls first, with WCAG 2.2 AA as the target.
- Let the API remain the authorization boundary. Navigation may hide
  unavailable destinations for clarity, but it never grants authority.
- During the local bootstrap phase, Django serves the built application at
  `/staff/` and provides session login at `/accounts/login/`. Vite proxies the
  same paths in development.
- Keep authentication replaceable. The local email/password form establishes a
  Django session; it is not the final external identity-provider design.
- Build the initial shell around edition context, a Today overview, and a safe
  People directory. Future modules register destinations rather than inventing
  separate shells.

## Consequences

React provides a familiar component model for persistent workspaces, while
TypeScript catches contract and state errors before deployment. Vite keeps the
local loop and production build small. The frontend can later be deployed
separately without changing its API contract.

The repository now has Python and Node dependency locks and both must be
maintained. Generated API types must be refreshed when `openapi.yaml` changes.
Session and CSRF behavior needs integration coverage even though authorization
continues to be enforced server-side.

Serving the first build through Django is a deployment convenience, not a
coupling of business behavior into templates. The HTML host contains only
bootstrap values and asset references.

## Alternatives considered

- Django templates with progressive enhancement: smaller initial toolchain, but
  poorly matched to the long-lived multi-pane operational workspace and the
  separate-frontend constraint.
- Vue: a strong option with comparable capabilities; React was selected for its
  contributor familiarity and broad accessibility-testing ecosystem.
- Next.js or another server-rendered framework: deferred because the Staff
  Console is authenticated, the API already owns server behavior, and an
  additional application server would add operational complexity without a
  current user benefit.
- A large component framework: deferred until the interaction system is proven;
  native controls and a small design-token layer preserve accessibility and
  visual ownership.
