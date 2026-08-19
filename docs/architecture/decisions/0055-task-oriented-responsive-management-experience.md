# ADR 0055: Task-oriented responsive management experience

- Status: Accepted
- Date: 2026-08-15
- Supersedes: ADR 0039 only for treating the inherited Django administration
  information architecture and responsive breakpoints as sufficient product UX
- Clarifies: ADRs 0026, 0027, 0040, and 0049
- Requirements: UX-001 through UX-013, UX-019, UX-024, UX-026, UX-027,
  UX-029, NFR-001 through NFR-004

## Context

Maru's command, authorization, audit, and migration boundaries are substantially
more mature than its management experience. The unified `/admin/` namespace
removed competing products, and ADR 0049 supplied one permission-filtered
navigation registry, but the resulting interface still presents the complete
registry as the primary mental model. A platform administrator can receive more
than ninety visible destinations, creation actions compete with durable
resources, and literal label matching means ordinary terms such as `users` do
not find **Accounts**.

The responsive shell also treats 768 pixels as desktop even after a roughly
275-pixel sidebar has consumed the available width. A live 958-pixel inspection
produced a 1,315-pixel document because the convention-context form retained a
wide label and selector. The mobile sidebar override supplied no Maru-owned
backdrop, close control, focus containment, Escape behavior, or focus return.
Passing isolated screenshots at 1,920 and 390 pixels therefore did not establish
a professional reflow or keyboard contract.

The owner selected the account-to-governance journey as the first corrective
slice: find or invite a person account, understand the identity-only result,
then continue to the organization's explicit Executive Board handoff. The
existing identity and representation commands remain authoritative.

## Decision

### Keep one product and one security boundary

Maru retains the canonical `/admin/` namespace, the code-owned navigation
registry, selected context, existing purpose-built routes, Django specialist
records, and embedded API-backed workflows. This decision creates no second
shell, route namespace, role system, page ACL, or client-side source of truth.
Authorization and disclosure are evaluated before presentation; hiding or
grouping a link never grants or revokes access.

### Present tasks before the exhaustive record catalog

The default shell presents a small, role- and context-relevant set of durable
destinations. Creation and one-shot commands belong beside their owning
resource as contextual actions rather than equal-weight navigation rows.
Authorized Django model destinations remain in the same registry but are
collapsed behind one **Specialist records** disclosure and remain available to
global menu search.

Navigation search indexes code-owned labels, descriptions, and stable keywords.
Keywords contain generic task vocabulary only; they never contain hidden
tenant, person, or record values. Matching is token-based so ordinary terms such
as `users`, `staff`, `volunteers`, and `board` can find the relevant authorized
destinations. Pins remain reauthorized preferences, but only durable
destinations are pinnable and the control does not dominate every row.

The administration home prioritizes current work and a **Continue setup**
journey, followed by recent work. It does not repeat the full specialist model
directory. One explicit gateway remains for advanced inspection.

### Own responsive shell behavior

The convention-context control is compact, shrinkable, and subordinate to the
current page. The shell has three behavior modes:

- wide layouts retain the persistent sidebar;
- intermediate and narrow layouts use a closed-by-default overlay drawer; and
- content, forms, and record lists reflow without page-level horizontal scroll.

The drawer has an explicit labelled open control, a visible close control, a
backdrop, `aria-expanded` and `aria-controls`, Escape-to-close, focus
containment, background scroll locking, and focus return. Only explicitly
labelled data regions may scroll horizontally.

The required reflow matrix is 320, 390, 768, 958, 1,024, 1,280, and 1,920 CSS
pixels plus 200 percent browser zoom. The inherited 767-pixel Django breakpoint
is an implementation input, not Maru's complete responsive contract.

### Establish the first reusable journey grammar

The first slice is:

```text
Administration home -> User accounts -> find or invite person
  -> invitation outcome -> Representation & access
```

It uses one consistent page header, status and primary action hierarchy,
results before long boundary explanations, explicit next actions, and a visible
three-step governance progression. Account creation continues to grant no
convention relationship. Executive Board provisioning, exact-account
invitation, invitee-owned response, two-controller activation, and disclosure
rules remain exactly those of ADR 0040.

Task-specific history and rationale appear beside the managed resource when an
authorized projection exists; users are not redirected to an unrelated generic
security-history page merely because both retain evidence.

### Treat experience evidence as a release gate

Every converted journey needs representative empty, populated, denied,
validation, stale, dependency-failure, and success states; keyboard completion;
automated accessibility analysis; and rendered evidence across the reflow
matrix. A top task must be reachable from the relevant home in at most two
navigation decisions without a direct URL. Owner rehearsal and a representative
screen-reader pass remain required before broad browser acceptance is claimed.

## Consequences

- Platform and convention operators receive a task-oriented entry point without
  losing authorized specialist inspection.
- Mid-width and split-window use becomes an explicit product contract instead
  of an accidental gap between desktop and phone CSS.
- Existing command, query, audit, and authorization services require no data
  migration or recovery change.
- Templates and embedded clients must converge on shared shell primitives;
  module-specific breakpoints or competing navigation require explicit review.
- The first slice does not by itself certify Registration, Workforce, Venues,
  Logistics, or every specialist record at every responsive state.

## Alternatives considered

### Restyle the existing directory without changing its hierarchy

Rejected. Color and spacing do not make ninety equally weighted destinations
teachable or fix missing task vocabulary.

### Replace Django administration with a new React application

Rejected. It would recreate competing shells and duplicate established command,
authorization, audit, and specialist-record boundaries.

### Hide specialist records completely

Rejected. Authorized technical inspection remains necessary. Progressive
disclosure and search reduce noise without removing capability.

### Keep the phone breakpoint as the only drawer threshold

Rejected. It ignores the space consumed by the persistent sidebar and fails
ordinary tablet, split-window, zoom, and adjusted-window use.
