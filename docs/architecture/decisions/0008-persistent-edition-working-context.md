# ADR 0008: Persistent edition working context

- Status: Partially superseded by ADR 0023
- Date: 2026-07-27
- Requirements: IDN-002, IDN-004, EVT-002, EVT-003, UX-003, UX-006, UX-008,
  UX-009, REG-001

## Context

Maru serves several organizers and annual editions through one account and one
administrative surface. Showing records from MaruCon 2026, MaruCon 2027, and an
unrelated organizer together makes routine work error-prone even when every row
is technically authorized. A convention operator normally works on one edition
at a time.

Some workflows must still refer outside that edition. Registration setup may
copy a reviewed prior edition or an eligible reusable template. Platform
identity and bootstrap structure also contain records that do not belong to one
edition.

## Decision

Maintain one explicit selected-edition working context in the authenticated
session.

- Staff Console selection and bootstrap administration use the same edition
  identity when moving between those surfaces.
- Event-owned administration querysets, object lookup, counts, and ordinary
  foreign-key choices are scoped to the selected edition before rendering.
- Organization-wide authority that applies to the edition remains visible
  alongside edition-specific authority.
- Platform-only records remain available but are visibly identified as
  platform-wide; the edition context does not falsely reclassify them.
- The selector includes an explicit `All foundation data` state so a bootstrap
  administrator can create the first organization, series, or edition.
- Cross-edition registration sources are an explicit exception. They are
  limited to eligible templates or editions in the selected edition's
  organization, and copying still creates an independent reviewed draft under
  ADR 0007.
- A selected edition is a navigation and query-minimization context, never
  proof of authority. APIs and commands continue to authorize trusted
  organization and edition scope independently.
- An active Django staff account with no convention participation originally
  routed from `/staff/` to bootstrap administration. ADR 0023 supersedes that
  visible-surface behavior: every authenticated account now remains in the
  Management Console's safe empty-workspace state, where Django staff may
  follow an explicit Advanced records link.

## Consequences

Routine administration stays focused and direct links to records from another
edition resolve as unavailable while a context is selected. Switching context
is explicit and persistent. New module admin pages must declare how their
records relate to an edition rather than inheriting an unscoped default.

Bootstrap Django staff access remains a temporary broad operational mechanism;
the context filter improves safety and usability but does not replace the
capability system required for product workflows.

## Alternatives considered

- Independent filters on every changelist: rejected because they are easy to
  forget, do not scope details or choices, and lose context during navigation.
- Treat selected edition as authorization: rejected because client or session
  state cannot grant organizer access.
- Hide all cross-edition records without exception: rejected because reviewed
  configuration inheritance is a required workflow.
- Automatically select the newest edition for bootstrap administrators:
  rejected because it could silently place an administrator in the wrong
  tenant or year; the first selection remains explicit.
