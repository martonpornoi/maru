# Participation module

Status: Implemented V01 kernel, initial staff projection, and purpose-bounded
edition-context projection that does not manufacture Participation
Last updated: 2026-08-26

## Purpose and requirements

`maru.participation` owns a person's explicit relationship with an edition and
durable capacity labels for IDN-003, IDN-011, IDN-014, EVT-006, NFR-013, and
ARC-001 through ARC-004. It does not own account existence or generic edition
authority.

## Owned data and invariants

- one participation per account and edition;
- explicit organization and edition scope;
- interested, pending, confirmed, active, completed, or cancelled state;
- edition and series name snapshots;
- multiple stable capacity codes and historical labels;
- proposed, active, completed, or withdrawn capacity state;
- contribution summary and opt-in public-history flags.

Platform administrators are operational actors rather than convention people;
model validation and PostgreSQL reject that account classification as a
participation subject. The database guard locks the identity row during writes,
and a deferred identity trigger rejects reclassification while any edition
participation remains.

PostgreSQL triggers reject organization/edition mismatches and any ordinary
participation or capacity mutation after edition archive. Uniqueness exists at
the database boundary. Participation `0004` installs its IDN-011 write and
reclassification guards before a final count-only existing-data preflight; see
[`idn011-convention-subject-migration-and-recovery.md`](../operations/idn011-convention-subject-migration-and-recovery.md).

## Public queries and API

- `participations_for_account(account)`
- `archived_participations_for_account(account)`
- `snapshot_participations_for_archive(edition_id)`
- `GET /api/v1/me/context`
- `GET /api/v1/me/participation-history`
- `GET /api/v1/organizations/{organization_id}/editions/{edition_id}/participations`
- `GET /api/v1/organizations/{organization_id}/editions/{edition_id}/participations/{account_id}`

Both endpoints use only `request.user`; no client-supplied account or tenant
scope can broaden them. The context endpoint combines that account's explicit
relationships and currently authorized edition targets. Authority may expose a
purpose-bounded Workforce-only workspace with `not_participating` status,
immutable adoption profile, adopted modules, and available destinations without
creating a Participation or capacity row. Platform administrators remain
separately classified and receive the same profile boundary.

The staff list and detail require `participation.view_staff_summary`, establish
organization and edition from trusted route scope, constrain the queryset
before target lookup, and return exactly account ID, display name,
participation status, and active/proposed capacity labels. Search never includes
email. List and detail reads append allow, denial, or unavailable audit
evidence. Filters cover display name, capacity label/code, status, and bounded
pagination.

The public registration application service creates a pending participation
when an attendee has no relationship with the selected edition. It reuses an
existing same-account, same-edition participation and cannot assign capacities.
The attendee registration profile renders active and proposed capacities as
authoritative convention roles, such as a volunteer department, rather than
letting the attendee self-assert them.

Workforce-only setup, Maru-operator activation, account sign-in, edition-
context selection, Position assignment, Availability, and Shift operations do
not create Participation. Full-convention Position assignment retains its
historical capacity-projection behavior. Volunteer responsibility in a bounded
profile therefore remains distinct from attendee registration and attendance.

## Permission and sensitivity

Participation and non-public capacities are C2. Public-history flags default
false. Self endpoints remain self-only. The first staff projection enforces the
code-owned field ceiling and sensitive-read audit obligation. Contact,
credential, membership, contribution, and internal identifiers are not exposed.

## Bootstrap administration

Participation lists identify the person and edition directly, summarize the
first three capacity labels with the complete list available on hover, and
provide person, edition, capacity, status, visibility, and tenant search or
filters. Capacity lists use person, edition, historical label, status, and a
compact term summary; codes, visibility, contribution detail, and exact dates
remain available in filters or record detail.

Capacities are editable inline for non-archived participation. Archived
participation and capacity records are view-only, and ordinary deletion is
disabled. Technical UUIDs remain in collapsed detail sections.

## Archive and correction

At closing-to-archived transition, names are finalized from the current edition
and series. Later renaming does not rewrite history. Archived changes require a
future audited correction command.

Operational history intentionally excludes application reviews, legal identity,
hotel room, cases, and other unnecessary detail.

## Tests

PostgreSQL tests cover cross-scope model and raw-update rejection, duplicate
participation/capacity, archive immutability, snapshot timing, self-only API
projection, staff field minimization, staff list/detail audit, filters,
anonymous denial, unknown-target hiding, and two-tenant/two-edition
non-disclosure. IDN-011 tests also cover bulk insertion, raw reassignment,
account-kind reclassification, legacy-row migration refusal, and concurrent
subject writes versus reclassification.

## Limitations

Capacity definitions, status transitions, completion evidence, certificates,
capacity administration outside bootstrap, archive correction, retention
execution, and staff mutations are not implemented. The new edition
registration profile is purpose-specific and does not yet replace the broader
opt-in public participation history planned here.
The context API currently carries adopted-destination projection for the shared
shell; it is not a general profile-management command and must continue to
resolve policy server-side on every request.
