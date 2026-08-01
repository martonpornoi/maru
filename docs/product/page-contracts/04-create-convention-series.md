# Page 4 contract: Create convention series

- Status: Implemented and backend-verified for platform oversight and scoped
  Executive Board authority; browser rehearsal pending
- Branch: `codex/page-04-create-convention-series`
- Route: `/admin/platform/organizations/<organization_slug>/series/new/`
- Requirements: IDN-004, IDN-011, IDN-012, EVT-001, EVT-003, UX-012 through
  UX-014, UX-017, UX-018, UX-019, UX-024, AUD-001, AUD-002, PRI-001
- Decisions: ADR 0035, ADR 0036, ADR 0039, ADR 0040

## Purpose and primary user

Let explicit platform oversight or active Executive Board authority with
`organizations.create_series` create one recurring public convention brand
beneath the organization being inspected. This follows the accountable
organization/representation handoff and precedes any dated event edition.

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

The browser contract accepts only these five fields plus CSRF. A forged
organization, slug, profile version, actor, timestamp, or other undeclared key
fails with `unknown_input_field`; it is never silently ignored. The same
closed-input rule applies when the form is reused for Page 5, where the one
additional declared key is the expected profile version.

## Authorization, lifecycle, privacy, and audit

The M1 adapter accepted only an active platform administrator. ADR 0040 adds
exact organization-scoped `organizations.create_series` authority for an
active Board assignment; the current backend matrix verifies both. Authorization happens before
organization lookup. The service repeats it, locks the parent, and refuses a
Closed organization. Draft is allowed for platform setup before activation;
Board authority exists only after atomic activation. Active and Suspended
parents may maintain brand setup; Closed is terminal.

The series, minimized audit event,
`organizations.convention_series.created.v1` domain event, and outbox delivery
are one transaction. Audit and domain facts name the organization relationship
and created field labels, but do not copy the name, description, website, or
email into metadata. A database, audit, event-publication, or outbox failure
rolls everything back. The resulting series remains C1 setup data until an
explicit public-content publication workflow exists.

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
- crafted organization/slug values and every other undeclared field rejected;
- repeated service authorization and locked lifecycle validation;
- atomic minimized audit/domain event/outbox evidence with field names and no
  entered values;
- audit/event/outbox/database rollback and safe non-disclosing retry state;
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
