# ADR 0039: Use one unified administration shell and reserved platform routes

- Status: Accepted
- Date: 2026-08-01
- Supersedes: ADR 0030 for the default URL configuration and mounted browser
  shell
- Clarifies: ADR 0037
- Requirements: UX-001, UX-005 through UX-013, UX-014 through UX-023,
  NFR-001 through NFR-004, NFR-008, NFR-009

## Context

ADR 0030 deliberately made `maru.baseline_urls` the default while the owner
re-established the purpose and placement of management pages. That reset
succeeded: Pages 1 through 7 now form a bounded organization -> series ->
edition journey with explicit page contracts, strict inputs, non-participating
platform administration, audit evidence, and shared HTML/API services.

Keeping that journey in a separate minimal shell now works against ADR 0037's
one-product goal. Maru already retains the richer pre-reset Django
administration shell, embedded Convention work, specialist records, Maru
identity, and record-oriented interaction grammar. Reintroducing each of those
capabilities through another navigation system would create the split product
the consolidation is intended to remove.

The former Page 1 route also occupied `/admin/` and the Pages 2 through 7 routes
began with `/admin/organizations/`. Django administration owns the same
namespace and uses application labels below `/admin/`; mounting purpose-built
platform routes in that unreserved space risks route ambiguity with the
`organizations` application and future specialist records.

Repository archaeology established that the pre-reset checkpoint and every
local page branch are ancestors of the current line. Their source does not need
to be merged. The two remote legacy refs have unrelated histories and
incompatible tenant, identity, authorization, and migration assumptions.

## Decision

### Default shell

`maru.urls` becomes the intended default URL configuration. Authenticated
platform and organizer management uses one coherent `/admin/` namespace:

- `/admin/` is the permission-filtered administration home and global shell;
- `/admin/workspace/` hosts API-backed Convention work inside that shell;
- `/admin/<app-label>/<model-name>/...` retains specialist record routes; and
- the accepted Pages 1 through 7 use the reserved `/admin/platform/` route
  space.

The canonical page spine is:

```text
/admin/platform/organizations/
/admin/platform/organizations/new/
/admin/platform/organizations/<organization-slug>/
/admin/platform/organizations/<organization-slug>/series/new/
/admin/platform/organizations/<organization-slug>/series/<series-slug>/
/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/new/
/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/
```

Delete and edition-context POST actions remain below their owning record
routes. Explicit purpose-built routes are registered before Django's model
administration resolver. `platform` is a reserved management segment, not a
Django application label or tenant identifier. The former Page 1 through 7
paths are no longer canonical; compatibility redirects require a separate,
tested decision and must not shadow model routes or leak whether a record
exists.

`maru.baseline_urls` may remain temporarily as historical and focused-test
scaffolding, but it is no longer the intended development or deployment
surface. It must not become a second supported management product.

### One visual and navigation grammar

The unified shell uses Maru's owned logo and the stronger pre-reset
record-oriented grammar: one viewport-aligned, collapsible, permission-aware
sidebar; consistent title, purpose text, modules, forms, tables, buttons,
spacing, focus treatment, and responsive behavior; and one explicit edition
working context. Pages 1 through 7 retain their accepted purpose and domain
contracts while being presented inside this grammar.

This decision does not restore the removed global Quick Start strip, a second
React navigation, a duplicate workspace selector, page-local ACLs, or a
separate staff website. Only mounted destinations appear. Platform
administration remains visibly distinct from convention participation.

### Authority and domain ownership

Route placement and selected-edition state never grant authority. The platform
page spine continues to require an active platform administrator until M2 adds
canonical organization representation and scoped convention authority.
Specialist records retain Django staff/model-permission checks. Convention
work and every embedded workflow retain their capability, organization,
edition, field, and lifecycle policies.

Current module services, queries, versioned APIs, audit, and effects remain
authoritative. HTML and embedded clients call those boundaries; mounting an
old screen does not revive direct cross-domain model saves or make preserved UI
behavior canonical. The pre-reset source is a visual and interaction reference
where its behavior still satisfies current requirements.

The remote legacy refs remain behavior-only archaeology. Their models,
migrations, global `Project`, email-allowlist authorization, URL credentials,
and privacy assumptions are never ported into the current line.

### Delivery state

This is an in-progress consolidation milestone, not a completion or production
readiness claim. The shell migration is complete only after route-collision,
authentication, authorization, navigation, preserved-workflow, API, full-suite,
accessibility, responsive-browser, recovery, and documentation checks pass.
Prior M1 evidence remains evidence for the committed edition spine but does not
certify the changed default URL configuration.

## Consequences

- Operators get one recognizable administration home and menu instead of a
  minimal platform site beside a separate specialist application.
- Pages 1 through 7 gain stable, collision-resistant routes without competing
  with Django application labels.
- The controlled-reset discipline remains useful: page contracts, strict
  inputs, denial states, narrow-screen evidence, and truthful capability status
  are still required.
- Some existing tests, runbooks, bookmarks, and tutorial URLs must change.
- Switching the root URL configuration can expose preserved routes that were
  previously unavailable by default; every route must be re-audited rather
  than assumed safe because it had earlier tests.
- No production data may be introduced and no production-readiness statement
  may be made until the repository and external gates pass.

## Alternatives considered

### Keep the minimal shell indefinitely

Rejected. It preserves page clarity but forces specialist records and
operational workflows to return through a second visible product or to be
rebuilt solely for navigation reasons.

### Put Pages 1 through 7 directly below `/admin/organizations/`

Rejected. Django administration already uses application-label route segments;
the unreserved path is ambiguous and makes future collision behavior depend on
resolver order.

### Restore the entire pre-reset experience unchanged

Rejected. Its useful source is already present, but its complete information
architecture was not accepted. Current page contracts, services,
authorization, and capability ledger decide what is mounted.

### Merge a remote legacy branch

Rejected. Those histories are behavior references with incompatible domain and
security boundaries, not implementation dependencies.
