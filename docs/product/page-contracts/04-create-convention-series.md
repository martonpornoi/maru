# Page 4 contract: Create convention series

- Status: Implemented and verified; owner inspection pending
- Branch: `codex/page-04-create-convention-series`
- Route: `/admin/organizations/<organization_slug>/series/new/`
- Requirements: IDN-011, EVT-001, EVT-003, UX-013, UX-014, UX-017,
  UX-018, UX-019, AUD-001, AUD-002, PRI-001
- Decisions: ADR 0035, ADR 0036

## Purpose and primary user

Let an active Maru platform administrator create one recurring public
convention brand beneath the organization being inspected. This is the second
identity step in setup, after the accountable organization and before any dated
event edition.

The administrator is an attributed platform operator. Creating the series does
not make that account an organizer member, Executive Board holder, convention
authority, participant, registrant, volunteer, or workforce assignee.

## Placement and navigation

Page 3 adds a **Convention series** section before its complete profile. The
section lists only series owned by that organization and provides a contextual
**+ Add series** action. Empty text explains that editions come later.

Page 4 is nested under that organization and links back to its Page 3 record.
The shared sidebar retains the global **Organizations** row and adds a section
named for the selected organization. That section links to **Organization
record** and **Convention series**; the latter keeps its compact adjacent
**+ Add** action current on Page 4. This is contextual navigation, not a
global or cross-tenant Series collection. The desktop sidebar starts at normal
page padding and the bounded content remains beside it; narrow layouts stack.

## Information and creation action

The heading names the parent organization and explains that a series is the
public identity continued across editions, not a separate tenant. The form has:

- **Convention series name** — required, normalized, at most 160 characters;
- **Public description** — optional, at most 2,000 characters;
- **Website** — optional validated URL, assuming HTTPS when omitted;
- **Public contact email** — optional validated email; and
- **Availability** — optional selection defaulting to Active.

Active means available as the parent for future editions. It does not publish
anything and does not create an edition. Organization and slug are never posted
fields. Maru generates a bounded slug, unique case-insensitively within the
organization; duplicate names receive a numeric suffix and other organizations
may use the same slug.

## Authorization, lifecycle, privacy, and audit

Only an authenticated active `platform_administrator` may load or submit Page
4 during the controlled rebuild. Authorization happens before organization
lookup. The service repeats it, locks the parent, and refuses a Closed
organization. Draft is explicitly allowed so Page 2 organizations can progress
before the later Executive Board/activation workflow. Active and Suspended are
also allowed to maintain brand setup; Closed is terminal.

Creation and its audit event are one transaction. Audit names the organization
relationship and created series fields, but does not copy the name,
description, website, or email into metadata. A database or audit failure rolls
back the series. The resulting series remains C1 setup data until an explicit
publication workflow exists.

## Page states

- **Initial:** parent identity is visible, name is focused, availability is
  Active, optional fields are blank, and boundaries are explained.
- **Validation:** field-local errors keep safe submitted values and create
  nothing.
- **Success:** redirect to Page 3 with a one-time confirmation and the new
  series row.
- **Closed parent:** `409` explanation with no creation form or mutation.
- **Denied:** `403` before lookup and with no organization disclosure.
- **Not found:** an authorized administrator receives `404`.
- **Failure:** generic `503` retry guidance with no internal error or partial
  series.
- **Loading:** ordinary server rendering; no invented partial series.

## Responsive and accessibility evidence

The page uses one `h1`, visible parent context, labelled sections, field-local
errors, text labels for status, visible focus, and an ordinary cancel link.
Page 3's series table reflows to labelled records at narrow widths. Desktop and
390-pixel layouts must have no horizontal overflow.

## Acceptance checks

- Page 3 empty and populated organization-scoped series states;
- contextual record and series destinations, current add route, global
  organization row, and viewport-edge desktop alignment;
- anonymous redirect, denied-before-lookup, authorized 404, and Closed `409`;
- name-only active creation and complete optional inactive creation;
- normalized names, bounded collision-safe per-organization slugs, and
  cross-organization reuse;
- crafted organization/slug values ignored;
- repeated service authorization and locked lifecycle validation;
- atomic audit with field names and no entered values;
- audit/database rollback and safe retry state;
- no edition, membership, authority, participation, registration, or workforce
  side effects;
- desktop and 390-pixel browser inspection without creating a live MaruCon
  series; and
- focused and complete quality gates plus handoff documentation.

## Explicit non-goals

- Editing, moving, deleting, deactivating, or publishing an existing series.
- Creating or inheriting an event edition.
- Organization lifecycle changes or Executive Board provisioning.
- Convention access, participation, registration, staffing, or hierarchy.
