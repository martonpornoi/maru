# ADR 0033: Complete organization creation and platform navigation

- Status: Accepted
- Date: 2026-07-31
- Supersedes: ADR 0032 only where Page 2 displayed one field and deferred the
  organization profile to Page 3
- Requirements: IDN-002, IDN-011, IDN-012, EVT-005, UX-013, UX-014,
  UX-015, UX-016, AUD-001, PRI-001

## Context

The first Page 2 implementation proved the authorization, draft, slug, audit,
and non-participation boundary with a name-only form. Product-owner inspection
showed two usability gaps. The creation route was presented as an action inside
the inventory panel rather than as a stable administration destination, and
the form did not let an administrator complete the organization information
normally available at the time of setup.

Public organizer imprints commonly combine a recognizable name, registered
legal name, address, responsible representative, contact address, and
registration identifier. Jurisdictions vary, so Maru
needs common structured properties plus a bounded additional-imprint field
instead of assuming one country's exact legal vocabulary.

## Decision

Page 1 and Page 2 share a persistent, responsive **Platform administration**
side navigation. It contains **Organizations** and **+ Add**, identifies the
current page with `aria-current`, and remains usable as compact navigation at
narrow widths. The inventory no longer needs a second competing create button.

Page 2 keeps organization name as the only required operator-supplied value,
but accepts the complete initial profile in four sections:

- public identity: recognizable name and description;
- legal and imprint: registered name, formatted legal address, responsible
  representative, registration authority and identifier, tax identifier, and
  bounded additional imprint wording;
- public contact: website, email, and optional international telephone number;
  and
- operating defaults: primary country, ordered ISO language codes, and an IANA
  time zone.

The generated slug remains code-owned. Lifecycle is displayed as Draft and is
not selectable: IDN-012 prevents activation before the later Executive Board
workflow exists. English and UTC remain safe defaults when locale values are
omitted. All other optional properties default to blank.

The platform-only service repeats authorization and validates the complete
model. Organization creation and its successful audit event remain atomic.
Audit records list property names but never copy legal, address, representative,
contact, tax, or imprint values into audit metadata. Entering legal or imprint
information does not publish it.

Page 2 still creates no membership, Executive Board, convention authority,
series, edition, participation, registration, or workforce record. The
platform administrator remains an attributed non-member actor.

## Consequences

A new organization can be described completely without turning the first step
into a mandatory legal questionnaire. Operators may submit only a name, while
those who already have official details can capture them once at creation.
The additional imprint field preserves jurisdiction-specific wording without
forcing every legal system into nullable columns.

Organization records created by the earlier Page 2 remain valid Drafts. The
schema migration adds blank optional values and does not rewrite MaruCon or any
preserved database record. Editing an existing organization remains Page 3;
this decision makes Page 2 complete for future creation rather than silently
turning the creation route into an edit route.

## Alternatives considered

- Keep the single inventory action and name-only form: rejected after owner
  inspection because creation was not discoverable as navigation and required
  immediate follow-up for already-known details.
- Require every legal and locale field: rejected because jurisdiction and
  organizer maturity differ; a recognizable name is enough to create a Draft.
- Store only one unstructured imprint blob: rejected because contact, locale,
  address, and common registration facts have distinct operational uses.
- Allow Active during creation: rejected until Executive Board representation
  and its authorization invariant are implemented.
