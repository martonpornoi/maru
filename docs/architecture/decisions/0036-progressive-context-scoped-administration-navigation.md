# ADR 0036: Progressive context-scoped administration navigation

- Status: Accepted
- Date: 2026-08-01
- Supersedes: ADR 0034 and ADR 0035 only for administration-navigation
  placement and current-state behavior
- Requirements: UX-013, UX-017, UX-018, UX-019, IDN-011, PRI-001

## Context

Pages 1 through 4 were introduced one at a time, but their shared menu still
represented only Organizations and its creation action. Page 4 was reachable
from Page 3 content, yet absent from the menu, and the entire two-column shell
was centered inside an 88-rem container. On a wide display this left a large
empty margin before the sidebar and made the controlled rebuild feel unlike
the compact preserved administration shell.

ADR 0035 correctly rejected a global Convention series row: a series is owned
by an organization and must never look like a second tenant or an unscoped
collection. That ownership rule does not require hiding organization-scoped
pages from navigation once an organization has been selected.

## Decision

The administration menu grows progressively with mounted pages. Global pages
remain in the global section. When a view has an authorized organization in
context, a second section names that organization and exposes:

- **Organization record**, linking to Page 3; and
- **Convention series** with an adjacent **+ Add**, linking respectively to
  Page 3's series section and Page 4.

Closed organizations retain the record and series-section links but do not
show the unavailable Page 4 creation action. Page 3 marks Organization record
current and Page 4 marks the scoped Series add action current. Pages 1 and 2
show only the global Organizations row. Each later mounted page must add its
own destination or action at its real global, organization, series, or edition
scope as part of that page's definition of done.

The desktop grid uses full available width with the same bounded horizontal
padding as ordinary administration chrome. Its content column stays bounded,
but the sidebar is no longer centered with the content as one large card. At
the existing narrow breakpoint the sidebar and content stack with one-rem
padding and no horizontal overflow.

The organization comes only from the already-authorized view context. The
menu does not enumerate organizations or series, infer tenant context, grant
authorization, accept an organization selector, or change the Page 4 route or
command boundary.

## Consequences

Every current setup page has a predictable menu location, creation actions
remain visually paired with their destinations, and wide screens no longer
place the sidebar behind a large artificial left gutter. The selected
organization stays visible while moving between its record and series
creation without creating an unscoped Series administration surface.

Future page contracts and tests must account for menu placement and current
state. Views that cannot provide authorized scope must omit contextual menu
sections rather than guessing or querying broadly.

## Alternatives considered

- Keep Page 4 reachable only from the Page 3 content panel: rejected because
  a mounted administration page should not disappear from the shared menu.
- Add one global Convention series collection: rejected because it obscures
  organization ownership and invites unscoped tenant presentation.
- List every organization and its pages in the global sidebar: rejected
  because it scales poorly and exposes unnecessary tenant names.
- Keep the centered 88-rem grid: rejected because its left gutter grows with
  viewport width and recreates neither the compact preserved shell nor a
  useful reading constraint.
