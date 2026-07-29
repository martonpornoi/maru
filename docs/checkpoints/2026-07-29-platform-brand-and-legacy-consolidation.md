# Platform brand and legacy consolidation checkpoint

Date: 2026-07-29
Phase: Registration production-safety complete; initial workforce onboarding
slice implemented; partner deployment readiness next
Requirements: UX-007, UX-008, UX-010, REG-014, FUR-010, HR-009, SCH-008,
VEN-008, INT-008, NFR-001, NFR-002
Decision: ADR 0021

## Outcome

Maru's owned cat-in-a-box identity and navy, gold, and ivory palette now form
the stable platform shell. Bootstrap administration, Staff Console, local
entry/sign-in, and the bundled registration reference client use the same
favicon, installed-app manifest, marks, and accessible palette. Annual
convention websites remain replaceable seasonal clients over the versioned
API.

The earlier private GitHub repository and its newer dirty local checkout were
reviewed read-only. Useful behavior was translated into requirements,
roadmap/backlog acceptance, and a capability map for programme revisions,
schedule layers/projections, volunteer shifts, venue reuse, announcements,
credentialed read feeds, preview-first imports, and archive views. Legacy
application code, migrations, database state, and runtime/personal media were
not imported.

## Decisions

- `maru.core` owns canonical platform brand assets and palette tokens.
- Original navy `#071B3A`, gold `#B9822E`, and ivory `#FAF3E3` anchors remain
  exact; darker gold carries small accent text where the original anchor does
  not meet WCAG AA on ivory.
- Semantic operational colors remain separate and always include text or icon
  meaning.
- Legacy Maru is a behavior reference only. Current tenancy, authorization,
  audit, privacy, modularity, and API decisions remain authoritative.
- No convention-owned annual artwork is treated as platform identity.

## Changed areas

- canonical image package, `brand.css`, and `site.webmanifest`;
- local home, sign-in, Staff Console host, registration reference, and
  bootstrap administration templates/styles;
- Staff Console source and checked-in production bundle;
- UX, schedule, workforce, venue, integration, and brand requirements;
- ADR index, roadmap, implementation backlog, product architecture, module
  documentation, and legacy capability map; and
- automated asset, manifest, palette, contrast, and template metadata tests.

## Verification

- 395 backend tests passed against PostgreSQL 17.
- Branch-aware coverage passed at 90.08%.
- Ruff formatting/lint and strict mypy over 172 source files passed.
- Django system check, migration drift, and OpenAPI 3.1 validation passed.
- Documentation validation passed for 100 Markdown files and 183 unique
  requirement identifiers.
- Generated Staff Console API types, TypeScript typecheck, 13 frontend tests,
  and the Vite production build passed.
- Browser QA verified owned assets and metadata on home, sign-in, and
  bootstrap-admin surfaces with no console errors or horizontal overflow.
  The home also passed at a 375-pixel mobile viewport.

## Data, migration, and deployment notes

This change adds no model or data migration. Brand assets are application
static files and must pass the normal static collection/deployment pipeline.
The legacy `media/` tree, databases, environment files, and other runtime
artifacts remain excluded.

## Known risks and incomplete work

The reviewed programme, schedule, shift, venue, announcement, and read-feed
behaviors are backlog inputs, not implemented capabilities. The original gold
anchor is unsuitable for ordinary small text on ivory and must remain an
accent unless paired with navy or replaced by the documented dark gold.

The stable Maru identity does not certify a seasonal frontend. Each annual
client still needs API conformance, accessibility, origin/CSRF, abuse, and
browser verification.

## Recommended next actions

Use the capability map with the first partner to select one bounded later
slice. Prioritize deployment/provider certification and the existing
production-readiness gates before treating future legacy-informed capabilities
as launch blockers.
