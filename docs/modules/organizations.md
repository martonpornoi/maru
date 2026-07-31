# Organizations module

Status: Implemented tenant, brand, localization bootstrap, Page 1 inventory,
and complete Page 2 Draft creation
Last updated: 2026-07-31

## Purpose and requirements

`maru.organizations` owns tenant structure and recurring-series continuity for
IDN-002, IDN-011, IDN-012, EVT-001, EVT-003, EVT-005, UX-014, UX-015,
and UX-016.

## Owned data and invariants

- `Organization`: the independently governed tenant/data-controller boundary,
  with UUID, slug, public and optional legal identity, lifecycle, contact,
  primary country, ordered default languages, and time-zone default. New
  records default to Draft; operational demo builders request Active
  explicitly.
- `ConventionSeries`: a recurring public convention brand within exactly one
  organization, with its own description, contact, and website.
- `OrganizationMembership`: one organizer-owned account relationship with
  invited, active, suspended, or ended state.

A platform administrator is not an organizer relationship. Membership
validation rejects that account classification while still allowing the
administrator to be attributed as the actor of later platform provisioning.

Organization slug is globally case-insensitively unique. Series slug is
case-insensitively unique within its organization. Protected relationships
prevent deletion from erasing editions or membership history.

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

Generic unscoped organization APIs remain absent. Page 2 is a narrowly scoped
server-rendered platform command, not a public or organizer API. It creates no
membership, governance, convention, participation, registration, or workforce
relationships.

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
retained with the organization legal record, reviewed on closure, exported with
the organization record, and not subject to ordinary deletion. Audit records
name changed fields but do not copy their values.

## Dependencies and consumers

- depends on the identity account identifier;
- events reference an owning organization and series;
- participation references the owning organization;
- the self-context projection consumes the membership query.

## Bootstrap administration

Organization, convention-series, and membership lists use names and
relationship labels instead of UUIDs. They support scoped search, lifecycle
and relationship filters, stable ordering, related-record counts, autocomplete
selection, grouped forms, and collapsed technical identifiers. Ordinary
deletion is disabled to preserve protected tenant and history relationships.
Organization and edition forms use searchable, bounded language and time-zone
choices. The organization form also explains the tenant/organizer role; the
series form explains recurring-brand continuity.

## Failure and retention

Tenant reparenting and cascaded deletion are not ordinary operations.
Organization closure and data exit need a future reasoned workflow.

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

## Limitations

Organization property editing for an existing record, Executive Board
provisioning/backfill, lifecycle transitions, publication, processors,
invitations, ownership transfer, and a purpose-built organizer setup console
are not implemented. Per IDN-012, the later governance workflow must establish
an Executive Board before activation; only active Executive Board authority and
platform administration may then modify organization properties.
