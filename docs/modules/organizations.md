# Organizations module

Status: Implemented tenant, brand, and localization bootstrap  
Last updated: 2026-07-29

## Purpose and requirements

`maru.organizations` owns tenant structure and recurring-series continuity for
IDN-002, EVT-001, and EVT-003.

## Owned data and invariants

- `Organization`: the independently governed tenant/data-controller boundary,
  with UUID, slug, public and optional legal identity, lifecycle, contact,
  primary country, ordered default languages, and time-zone default.
- `ConventionSeries`: a recurring public convention brand within exactly one
  organization, with its own description, contact, and website.
- `OrganizationMembership`: one organizer-owned account relationship with
  invited, active, suspended, or ended state.

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

Generic unscoped organization API and mutation commands are intentionally
absent until V02 policy enforcement.

## Permissions and sensitivity

Basic organization identity is C0/C1 depending on publication. Membership is
C2. The current API exposes a membership only to its own authenticated account.
It does not imply cross-tenant access from a shared platform account.

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

## Limitations

Organization lifecycle transitions, processors, invitations, ownership
transfer, and a purpose-built organizer setup console are not implemented.
