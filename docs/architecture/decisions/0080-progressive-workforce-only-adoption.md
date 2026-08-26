# ADR 0080: Make Workforce-only adoption explicit and purpose-bounded

- Status: Accepted
- Date: 2026-08-26
- Supersedes: ADR 0040 only where it requires every organization
  representation to be an Executive Board
- Extends: ADRs 0003, 0031, 0039, 0041, 0044, 0049, 0055, and 0075–0079
- Requirements: IDN-011, IDN-012, IDN-014, EVT-006, UX-019, UX-023 through
  UX-025, UX-027 through UX-030, NFR-003, and NFR-013

## Context

Maru's implemented convention journey assumed that an organizer would adopt
the platform broadly. That assumption made a safe first trial unnecessarily
risky for conventions that already have Registration, payment, attendance, or
other operational systems. It also made the Executive Board bootstrap ceremony
appear mandatory even when the people taking responsibility for a narrow Maru
deployment did not hold that real constitutional office.

The first bounded use case is volunteer management. A convention should be able
to use Structure, Positions, assignments, Availability, and Shifts while every
attendee-facing and financial workflow remains in its incumbent systems. The
edition still needs tenant, recurring-convention, dates, time-zone, identity,
authorization, audit, recovery, and accountable-human foundations. Removing
those foundations would make the apparently simpler workflow unsafe.

A navigation-only toggle cannot enforce that boundary. Platform oversight,
ordinary role assignments, generic access management, APIs, public
Registration configuration, and background behavior must all agree on what the
edition adopted. Existing Executive Board organizations and historical
authority evidence must not be relabelled or rewritten.

## Decision

### Store one immutable edition adoption profile

Every edition stores a code-owned adoption-profile code and version. Existing
editions migrate to `full_convention@1`; no existing behavior is silently
removed. New editions deliberately choose a supported profile. The first
bounded profile is `workforce_only@1`.

The profile is immutable for that edition at the model and PostgreSQL layers.
This avoids turning adoption into a casual checkbox that can silently change
authority, retention, integrations, or user expectations. A future profile
version or expansion uses an explicit reviewed workflow. A Maru-operator
organization cannot create a full-convention edition through ordinary operator
authority; that broader setup requires an active platform administrator.

`workforce_only@1` declares:

- required foundations: identity, organization, convention series, edition,
  authorization, audit, effects, and privacy operations;
- enabled product destination: Workforce, including Structure, Positions,
  assignments, Availability, and Shifts;
- excluded purposes: attendee Participation, Registration, payments,
  attendance, accreditation, catalog, charity, programme applications,
  Communications, Venues, and Logistics;
- internal locale defaults: `en` and `XXX`, where `XXX` means no currency is
  involved and is not presented as a payment choice;
- coexistence: incumbent systems remain authoritative for every excluded
  purpose and exchange no data unless a later reviewed adapter contract says
  otherwise;
- import: the existing versioned, copy-on-write Workforce structure template
  and manual purpose-built editors are available; no general partner bulk
  importer is claimed by this profile version;
- export, print, and degraded operation: existing scoped APIs and browser views
  remain available, but a complete continuity export, printable rota, and
  offline/manual reconciliation package are still production gates and must
  not be implied by activation;
- removal: there is no destructive self-service uninstall. An organization may
  stop operating the profile and retain its scoped evidence under lifecycle and
  retention policy. Migrations refuse profile-contract downgrade once durable
  Workforce-only evidence exists; recovery is fix-forward or whole-database
  restore; and
- expansion: adopt another accepted profile through an explicit platform
  decision without mutating the meaning of the existing edition.

These declared limitations make the profile suitable for incremental product
use and honest evaluation, not an assertion of production cutover readiness.

### Provide one minimum guided setup

`Set up Workforce` is a platform-administrator workflow. It asks how much of
the foundation already exists, then reuses the highest available level:

1. create Organization → Convention series → Event edition;
2. reuse an Organization and create its series and edition; or
3. reuse an existing series and create only the edition.

The only new human facts are organization name when needed, convention name
when needed, edition name, start and end dates, and IANA time zone. One atomic,
idempotent command creates or reuses the foundation, stores the Workforce-only
profile, records an append-only request receipt and minimized audit evidence,
and establishes accountable representation when absent. Disabled fields do not
affect the request digest. A changed retry conflicts. Existing active
organizations without a representation fail before partial child creation.

Setup creates no Participation, attendee Registration, payment, attendance,
application, accreditation, catalog, charity, Communications, Venue, or
Logistics record. A successful setup continues to accountable access when
human activation is needed and otherwise to Organization structure.

### Provide one safe first Position meaning

A fresh organization cannot create its first Position until an immutable,
published Position template and independently approved RoleBundle define what
that Position would mean. Requiring a convention to leave the guided journey
and invent that authority model would make the minimum profile incomplete.

After at least one active Department exists, an active accountable controller
may therefore create one code-owned **Workforce volunteer** starter when the
organization has no compatible published template. A different active
accountable controller must approve it and the initiating controller must give
a retained reason. The starter contains only `events.view_basic` and
`workforce.view_structure`, carries the semantic `volunteer` capacity label,
and is reusable by later Positions in that organization.

This action creates only the immutable RoleBundle, its independent issuance,
the Position template, and minimized audit evidence. It grants nobody
authority and creates no Position, opportunity, application, assignment,
membership, Participation, Registration, payment, Availability, or Shift
record. A reserved-code collision is a reconciliation conflict rather than an
overwrite. Published templates containing any capability outside the edition
profile are excluded from Position creation.

### Use truthful Maru-operator stewardship

`OrganizationRepresentation` supports two immutable code-owned types:

- `executive_board` for people who really are the organization's Executive
  Board; and
- `maru_operators` for people accountable only for operating Maru and the
  adopted Workforce capability.

Maru operators are not described as legal officers, do not replace an existing
Board, and do not become attendees. They use the same exact-person invitation,
self-acceptance, two-distinct-human activation, cross-approved immutable root
role, reason, audit, provenance, containment, and database-integrity controls
as the Executive Board ceremony. Their root role contains organization and
edition setup plus implemented Workforce capabilities, but no Registration,
payment, attendance, or unrelated module capabilities. Existing Board wrappers,
records, role versions, and historical evidence remain compatible.

The canonical root assignment is stored at organization scope so the same
accountable pair can govern successive Workforce-only editions. That is a
narrow reserved-role exception, not a broader capability ceiling. Edition
profile and Workforce capabilities still require exact edition scope for every
direct grant and ordinary role. PostgreSQL rejects an organization-wide direct
grant or generic role containing those capabilities, and policy applies the
reserved root only to `workforce_only` editions. A later full-convention edition
therefore grants its operators no implicit access.

### Enforce adoption before authority and disclosure

Exact-edition policy resolution rejects a capability whose top-level module is
not adopted before considering platform-administrator policy, direct grants,
or role assignments. Generic access management lists only groups and
assignments whose complete capability set fits the profile and rejects an
attempt to assign an incompatible group at edition, Department, or resource
scope. Public Registration configuration cannot discover Workforce-only
editions.

The context API exposes the profile, adopted modules, and code-owned available
destinations without manufacturing Participation. The Django shell, Staff
Console, setup guide, Today summary, forms, and specialist-record gateway use
that projection. Workforce-only users do not see attendee Registration,
payments, People attendance summaries, Reports and badges, or unrelated
planned-capability pressure. Low-frequency authorized technical records remain
reachable only through an explicit specialist-record disclosure.

An exact edition in the requested route is the navigation and workspace-selector
context even when the browser session has no saved edition. Public volunteer
pages use a Volunteer-only shell that does not imply attendee Registration or
payment. Personal Workforce routes focus their menu on My Maru and My
Workforce instead of advertising unrelated registration, order, application,
schedule, or equipment workflows. These are disclosure boundaries, not new
authorization mechanisms.

UI filtering is explanatory defense in depth. Services, policy, tenant scope,
database constraints, and audit remain authoritative.

## Consequences

- A convention can build trust with one complete volunteer-management journey
  while leaving incumbent Registration and finance systems untouched.
- Organization, series, and edition remain necessary because they provide the
  tenant, recurring identity, date/time, authority, history, and recovery scope
  that makes Workforce trustworthy.
- A narrow deployment no longer asks volunteers to pretend to be an Executive
  Board, while still requiring two accountable humans.
- A new organization can reach its first real Position without designing a
  custom role model, while the starter itself grants nobody access and cannot
  import an unadopted capability.
- Existing full-convention and Executive Board deployments preserve their
  exact meaning and behavior.
- Platform administrators are also denied unadopted exact-edition operations;
  oversight is not a hidden modularity bypass.
- Profile immutability makes expansion deliberate but means the product needs a
  later reviewed expansion workflow rather than an edit field.
- Bulk partner import, complete continuity export, printable/offline packs,
  profile decommissioning, deployment, retention execution, and representative
  recovery remain explicit production gates.

## Alternatives considered

- **Require every convention to adopt all of Maru:** rejected because it makes
  initial use operationally risky and blocks trust-building with one team.
- **Hide unrelated menu entries without a durable profile:** rejected because
  APIs, platform policy, stored grants, and background behavior could still
  cross the promised boundary.
- **Call Maru operators an Executive Board:** rejected because software
  responsibility does not establish a real legal or constitutional office.
- **Remove accountable representation for narrow adoption:** rejected because
  tenant configuration and access delegation still need recoverable human
  accountability and independent control.
- **Infer attendance from a volunteer account or assignment:** rejected because
  it creates unrelated personal data and collapses distinct purposes.
- **Make adoption mutable on the edition record:** rejected until Maru has an
  accepted impact preview, migration, integration, retention, rollback, and
  human-confirmation contract for expansion and removal.

## Requirements affected

- **IDN-012 and IDN-014:** Representation is truthful and purpose-specific;
  account access does not imply participation.
- **EVT-006:** The edition owns an immutable, versioned adoption boundary.
- **UX-019, UX-023 through UX-025, and UX-027 through UX-030:** Setup,
  representation, structure, context, and navigation consistently expose only
  adopted work.
- **NFR-003:** Append-only setup evidence and current documentation preserve a
  resumable handoff.
- **NFR-013:** Workforce-only is the first executable progressive-adoption
  profile, with coexistence and current portability/removal limits declared.
