# Checkpoint: Unified administration shell migration started

- Date: 2026-08-01
- Phase: Production consolidation M1.1, in progress
- Branch: `codex/full-platform-consolidation`
- Base checkpoint: `17b68a2`
- Related requirements: UX-001, UX-005 through UX-023, NFR-001 through
  NFR-004, NFR-008, NFR-009
- Related ADRs: ADRs 0030, 0037, 0038, and 0039

## Outcome

ADR 0039 establishes the crash-safe contract for leaving ADR 0030's minimal
default browser: Maru will use one coherent, record-oriented `/admin/` shell.
The permission-filtered administration home, embedded Convention work,
purpose-built platform spine, and specialist records share one navigation and
visual grammar. Pages 1 through 7 move to the reserved
`/admin/platform/organizations/...` route space so they cannot collide with
Django application-label routes.

This checkpoint starts the milestone. It does not claim that the changed root
URL configuration, route ordering, navigation, authorization, preserved
workflows, or browser behavior is complete or verified.

## Decisions

- `maru.urls` is the intended default configuration; `maru.baseline_urls` may
  remain temporarily as historical/focused-test scaffolding, not a second
  supported product.
- The richer pre-reset shell supplies Maru branding, one collapsible sidebar,
  record-oriented modules/forms/tables, and responsive interaction grammar.
  It does not restore Quick Start, duplicate navigation, or direct cross-domain
  model writes.
- Current services, policies, APIs, audit, and effects remain authoritative.
- Route placement and selected-edition state grant no authority. The platform
  administrator remains outside every organization and convention
  relationship.
- The pre-reset and local page refs are already ancestors. Remote legacy refs
  remain behavior-only archaeology; their histories, models, and migrations
  are not merged.
- Prior M1 verification supports the committed edition-spine behavior but does
  not certify this shell migration.

## Changed areas

This checkpoint changes documentation only:

- ADR index and ADR 0039;
- current handoff, production checklist, and roadmap;
- staff experience, architecture, requirement, module, and legacy-capability
  descriptions;
- Page 1 through 7 route contracts; and
- local setup and operator/tutorial documentation.

Concurrent implementation work in the same working tree is changing the root
URL configuration, explicit route ordering, and both administration navigation
templates. This documentation task does not edit or certify those runtime
changes.

## Verification

The repository documentation validator passed for 154 Markdown files and 195
unique requirement identifiers. `git diff --check` also passed for the shared
working tree at the checkpoint.

No runtime, database, migration, backend, frontend, route, authorization, or
browser check has been performed by this documentation checkpoint. Do not
reuse the previous M1 pass or the documentation result as evidence for ADR
0039's runtime behavior.

## Data, migration, and deployment notes

The documentation change adds no model, schema, or data migration and writes no
database records. Changing the deployment URL configuration can expose
previously preserved routes, so deployment must remain blocked until every
affected route is inventoried and authorized under current policy.

The M1 aggregate-version and downgrade-fence recovery boundary remains in
force. Do not roll back old application code after new M1 writes.

## Known risks and incomplete work

- Resolver ordering could send a purpose-built platform URL into Django's
  application/model resolver unless explicit routes remain first.
- A shared sidebar can reveal a destination label the viewer cannot use unless
  every section repeats its own permission boundary.
- Enabling the preserved URL set can remount more HTML than the intended shell
  milestone; reachability is not acceptance.
- Existing Page 1–7 tests, runbooks, bookmarks, and screenshots use old routes.
- Current Convention work and specialist-record integration, old-route
  behavior, responsive rendering, keyboard behavior, and accessibility are
  unverified.
- M2 governance, department/resource scope, and computed effective access are
  still mandatory before convention-owned mutation pages.
- No production personal data or production-readiness claim is permitted.

## Recommended next actions

1. Finish the exact URL and sidebar integration while preserving current
   service and authorization boundaries.
2. Add or update collision, anonymous/inactive/ordinary/staff/platform-admin,
   Convention work, specialist-record, and old-route tests.
3. Run focused checks, then the complete repository, generated-client,
   migration-drift, and deployment-shaped gates.
4. Repeat desktop and 390-pixel browser QA, axe analysis, keyboard traversal,
   and the relevant denied/error/stale state matrix.
5. Rehearse the updated hands-on tutorial with the owner before accepting M1.1
   or starting convention-owned M2 pages.
