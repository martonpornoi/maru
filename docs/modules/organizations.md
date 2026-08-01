# Organizations module

Status: Implemented tenant, brand, localization bootstrap, and mounted Pages
1–5 through convention-series record management
Last updated: 2026-08-01

## Purpose and requirements

`maru.organizations` owns tenant structure and recurring-series continuity for
IDN-002, IDN-011, IDN-012, EVT-001, EVT-003, EVT-005, UX-014, UX-015,
UX-016, UX-017, UX-018, UX-019, and UX-021.

## Owned data and invariants

- `Organization`: the independently governed tenant/data-controller boundary,
  with UUID, slug, public and optional legal identity, lifecycle, contact,
  primary country, ordered default languages, and time-zone default. New
  records default to Draft; operational demo builders request Active
  explicitly.
- `ConventionSeries`: a recurring public convention brand within exactly one
  organization, with its own description, contact, website, availability, and
  monotonic profile version.
- `OrganizationMembership`: one organizer-owned account relationship with
  invited, active, suspended, or ended state.

A platform administrator is not an organizer relationship. Membership
validation rejects that account classification while still allowing the
administrator to be attributed as the actor of later platform provisioning.

Organization slug is globally case-insensitively unique. Series slug is
case-insensitively unique within its organization. Protected relationships
prevent deletion from erasing editions or membership history.

PostgreSQL keeps a series' organization and slug stable. New series start at
profile version 1; changing any editable series fact must advance that version
by exactly one, and the version cannot advance without a profile change.

An organization may operate more than one series. For example, a legal
association may run one large annual convention and a separate small retreat.
Those brands share the accountable tenant only where policy permits; each
edition still owns its own operational configuration and history.

Country and default-language values use ISO codes. Language entry pins
`en (English)`, permits multiple defaults, and groups the remaining choices by
broad discovery region. These groups are navigation aids, not claims that a
language belongs exclusively to one continent. Time zones store an IANA
identifier and display current January/July UTC offsets so daylight-saving
behavior is visible. Server validation remains authoritative for imports and
non-browser clients.

## Public contracts

- models for owned aggregates;
- `memberships_for_account(account)`, a self-scoped query.
- `platform_organization_inventory()`, the C1 name, slug, lifecycle, series
  count, and edition-count projection used only after platform authorization.
- `create_draft_organization(...)`, the atomic platform-only command that
  accepts typed `OrganizationCreationDetails`, normalizes the required name,
  generates a collision-safe slug, validates the complete model, creates one
  Draft tenant, and appends its successful audit event.
- `update_organization_profile(...)`, the atomic platform-only command that
  locks an existing organization, updates only changed complete-profile fields,
  keeps slug/lifecycle code-owned, and audits field names without values.
- `delete_empty_draft_organization(...)`, the atomic platform-only command that
  requires exact-name confirmation and acknowledgement and can remove only a
  Draft whose protected relationship graph is empty.
- `create_convention_series(...)`, the atomic platform-only command that locks
  a non-Closed parent, accepts typed `ConventionSeriesCreationDetails`,
  normalizes the required name, generates a collision-safe slug within that
  organization, validates the complete series, and appends its audit event.
- `update_convention_series(...)`, the atomic platform-only command shared by
  Page 5 and its API. It locks the exact organization-owned series, compares
  the expected profile version, writes only changed brand fields, and commits
  minimized audit plus `organizations.convention_series.updated.v1` and its
  outbox delivery together.
- `GET /api/v1/organizations/{organization_id}/series`, a platform-
  administrator-only paginated collection scoped before bounded, strict query
  evaluation.
- `GET /api/v1/organizations/{organization_id}/series/{series_id}`, the strict
  scoped record with no accepted query parameters.
- `PUT /api/v1/organizations/{organization_id}/series/{series_id}`, the strict
  complete profile replacement.

Generic unscoped organization APIs remain absent. Pages 2 through 5 are
narrowly scoped platform workflows, not public organizer APIs. They
create no membership, governance, event edition, participation, registration,
or workforce relationships.

## Convention series creation fields

Only the recurring public brand name is required. Description, website,
contact email, and initial availability are optional; Active is the default
and means available for future editions, not published. Organization and slug
come from code-owned scope. Series slugs are stable, bounded, and
case-insensitively unique within one organization, so two organizations may
reuse the same recognizable slug while same-tenant collisions receive numeric
suffixes. Draft, Active, and Suspended parents may prepare a series; Closed
parents cannot.

Page 5 edits the same complete profile through optimistic concurrency. Its
HTML form accepts only the declared profile fields, expected profile version,
and CSRF. The API `PUT` is a strict complete replacement. Undeclared ownership,
slug, lifecycle, timestamp, or other fields are rejected rather than ignored.
An unchanged save writes and emits nothing.

## Organization profile fields

Only `name` is required at Draft creation. `slug` and `lifecycle` are
code-owned. The optional profile contains:

- public description;
- registered legal name and formatted legal address;
- printable responsible representative, without creating an appointment;
- registration authority, registration identifier, and tax identifier;
- bounded additional imprint wording for jurisdiction-specific legal text;
- website, general contact email, and E.164 public telephone number; and
- ISO primary country/languages plus IANA default time zone.

English and UTC are fallback defaults. The legal address is intentionally
formatted text because public address forms vary by jurisdiction; country and
locale remain separate structured values for operational defaults. The
additional imprint field must not contain payment data, identity-document data,
or private case information.

## Permissions and sensitivity

Basic organization identity is C0/C1 depending on publication. Membership is
C2. The current API exposes a membership only to its own authenticated account.
It does not imply cross-tenant access from a shared platform account.

The complete legal, address, representative, registration, tax, contact, and
imprint profile is C1 until an explicit publication workflow exists. Its
purpose is accountable organizer setup and future legal publication; its source
is platform administration or later active Executive Board authority. It is
retained with the organization legal record, reviewed on closure, and exported
with the organization record. Audit records name changed fields but do not copy
their values. An empty Draft may be deleted before it owns related data; once
any protected relationship exists, retention and a future closure workflow take
precedence.

## Dependencies and consumers

- depends on the identity account identifier;
- events reference an owning organization and series;
- participation references the owning organization;
- the self-context projection consumes the membership query.

## Bootstrap administration

The shared administration menu always exposes the global Organizations row.
Once an authorized view has selected an organization, a section named for it
links to its record and Convention series section, with series creation beside
that destination while lifecycle permits it. Selecting a series adds its own
record and Convention editions destinations; new-edition availability depends
on both organization and series state. This is display context only: it
does not query across tenants, infer ownership, or grant authority. The desktop
shell aligns that menu to ordinary page padding instead of centering the whole
grid.

Organization, convention-series, and membership lists use names and
relationship labels instead of UUIDs. They support scoped search, lifecycle
and relationship filters, stable ordering, related-record counts, autocomplete
selection, grouped forms, and collapsed technical identifiers.
Organization and edition forms use searchable, bounded language and time-zone
choices. The organization form also explains the tenant/organizer role; the
series form explains recurring-brand continuity. Generic administration
deletion remains disabled; the purpose-built Page 3 command handles only
confirmed empty Drafts.

## Failure and retention

Tenant reparenting and cascaded deletion are not ordinary operations. The
empty-Draft command never cascades; protected relationships refuse it.
Convention-series profile versions and their database guard require compatible
writers. A migration fence refuses destructive version-column downgrade while
any series exists; populated recovery uses fix-forward or an approved backup/
PITR plan. Organization closure and data exit still need a future reasoned
workflow.

## Tests

PostgreSQL tests cover case-insensitive scoped uniqueness, protected deletion,
two-tenant synthetic data, localization normalization/validation, readable
language/time-zone/telephone choices, and self-context non-disclosure.
Page tests additionally cover membership rejection plus empty, populated,
denied, and safe database-failure inventory states. Page 2 tests cover shared
side navigation, name-only and complete-profile creation, every optional field
validator, normalization, Unicode fallback and bounded slug generation,
collision handling, code-owned Draft/defaults, repeated service authorization
and model validation, atomic auditing and rollback, safe audit metadata,
one-time confirmation, and the absence of relationship side effects.
Page 3 tests cover linked records, compact navigation, complete profile
updates, code-owned slug/lifecycle, no-op saves, safe error states, service
authorization, audit value minimization, exact deletion confirmation,
Draft/relationship guards, and atomic update/delete rollback.
Page 4 tests cover empty and populated organization-scoped series projections,
contextual navigation, denied-before-lookup authorization, unknown and Closed
parents, name-only and complete optional creation, crafted-scope resistance,
per-tenant slug collision/fallback/bounds, repeated service validation,
value-minimized atomic audit/domain-event/outbox evidence, publication and
database rollback with safe 503 disclosure, and the absence of edition or
people-relationship side effects.
Page 5 and API tests cover exact tenant scope, strict input, complete profile
replacement, no-op and stale saves, stable ownership/slug database guards,
profile-version monotonicity, safe activity, audit/event/outbox rollback,
pagination, error shapes, fail-closed populated downgrade, and the absence of
convention relationships.

## Limitations

Executive Board provisioning/backfill, organization and series lifecycle
transitions, slug migration, publication, processors, invitations, ownership
transfer, closure/data exit, and a convention-owned organizer console are not
implemented. Per IDN-012, the
later governance workflow must establish an Executive Board before activation
and extend Page 3 property editing to active Executive Board authority;
platform administration remains non-participating.
