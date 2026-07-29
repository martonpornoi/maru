# Participation module

Status: Implemented V01 kernel and initial staff projection  
Last updated: 2026-07-27

## Purpose and requirements

`maru.participation` owns a person's relationship with an edition and durable
capacity labels for IDN-003 and ARC-001 through ARC-004.

## Owned data and invariants

- one participation per account and edition;
- explicit organization and edition scope;
- interested, pending, confirmed, active, completed, or cancelled state;
- edition and series name snapshots;
- multiple stable capacity codes and historical labels;
- proposed, active, completed, or withdrawn capacity state;
- contribution summary and opt-in public-history flags.

PostgreSQL triggers reject organization/edition mismatches and any ordinary
participation or capacity mutation after edition archive. Uniqueness exists at
the database boundary.

## Public queries and API

- `participations_for_account(account)`
- `archived_participations_for_account(account)`
- `snapshot_participations_for_archive(edition_id)`
- `GET /api/v1/me/context`
- `GET /api/v1/me/participation-history`
- `GET /api/v1/organizations/{organization_id}/editions/{edition_id}/participations`
- `GET /api/v1/organizations/{organization_id}/editions/{edition_id}/participations/{account_id}`

Both endpoints use only `request.user`; no client-supplied account or tenant
scope can broaden them. The context endpoint combines only that account's
memberships, participations, and capacity projections.

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
non-disclosure.

## Limitations

Capacity definitions, status transitions, completion evidence, certificates,
capacity administration outside bootstrap, archive correction, retention
execution, and staff mutations are not implemented. The new edition
registration profile is purpose-specific and does not yet replace the broader
opt-in public participation history planned here.
