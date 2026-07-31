# ADR 0032: Minimal draft organization creation

- Status: Accepted
- Date: 2026-07-31
- Requirements: IDN-002, IDN-011, IDN-012, UX-013, UX-014, UX-015,
  AUD-001, AUD-002

## Context

Page 1 deliberately lists organizations without offering a mutation. Page 2
must make the first useful platform action available without turning initial
tenant provisioning into a long legal, locale, governance, or convention form.
At creation time, the only fact the operator necessarily knows is the
organization's recognizable name.

An organization will ultimately require an Executive Board representation
root, and organization properties will be editable only by that authority or
platform administration. The board workflow and Organization record do not yet
exist in the controlled rebuild. Pretending to provision usable human authority
before those pages and their approval rules are designed would recreate the
confusion that the page-by-page rebuild is intended to prevent.

## Decision

Add `/admin/organizations/new/` as Page 2. Only an authenticated, active
`platform_administrator` may load or submit it. The form asks for one required
value: organization name.

Maru creates the organization with:

- a normalized non-empty name;
- a lowercase ASCII slug generated from that name, using a bounded numeric
  suffix when the preferred slug already exists;
- `draft` lifecycle;
- existing code-owned defaults of English and UTC; and
- blank optional legal, contact, country, and descriptive properties.

The command, organization row, and successful audit event share one database
transaction. Failure rolls back both state and success evidence. The audit
identifies the platform administrator as actor, while creation produces no
membership, capability grant, role assignment, participation, workforce
structure, series, or edition.

Successful submission redirects to the platform organization inventory, which
shows the new Draft record and a one-time confirmation. Page 3 will make that
record navigable and will own its full legal, imprint, contact, localization,
activation, and property-editing workflow.

IDN-012 records the future governance invariant, but Page 2 does not create a
placeholder Executive Board. When the governance workflow is introduced, it
must atomically provision or backfill the board for existing draft
organizations and enforce that only active Executive Board authority and
platform administration can modify organization properties. The platform
administrator remains a non-member attributed actor.

## Consequences

The first organization can be created with one understandable decision and no
false claim of legal or governance completeness. Draft status prevents the
record from being treated as an operational organizer before later review.
Stable generated slugs remove technical data entry from the form while keeping
URLs and audit references readable.

The temporary interval between Page 2 and the governance page permits draft
organizations without an Executive Board. They cannot be activated through the
controlled browser experience. Later work must close that interval and cover
existing drafts rather than assuming that only new records need governance.

## Alternatives considered

- Require the complete legal profile and imprint at creation: rejected because
  those details are conditional by jurisdiction and can be completed safely on
  the later Organization record.
- Ask the operator for a slug: rejected because it is a technical identifier
  Maru can derive and disambiguate safely.
- Create the Executive Board immediately: deferred because the representation,
  appointment, approval, and property-authorization contract has not yet been
  reviewed page by page.
- Create organizations as active: rejected because a name-only record is not
  ready to own live convention operations.
