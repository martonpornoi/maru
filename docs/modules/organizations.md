# Organizations module

Status: Implemented tenant, brand, localization, Pages 1–5, initial Page 8
Executive Board lifecycle, emergency containment, and Page 9a.0 minimized
governance-anchor query; Page 9 Department mutations remain workforce work
Last updated: 2026-08-02

## Purpose and requirements

`maru.organizations` owns tenant structure and recurring-series continuity for
IDN-002, IDN-004, IDN-005, IDN-009, IDN-011, IDN-012, EVT-001, EVT-003,
EVT-005, HR-011, UX-014 through UX-021, UX-024, and UX-025.

## Owned data and invariants

- `Organization`: the independently governed tenant/data-controller boundary,
  with UUID, slug, public and optional legal identity, lifecycle, contact,
  primary country, ordered default languages, and time-zone default. New
  records default to Draft; the synthetic demo establishes governance through
  the real representation services before the organization becomes Active.
- `ConventionSeries`: a recurring public convention brand within exactly one
  organization, with its own description, contact, website, availability, and
  monotonic profile version.
- `OrganizationMembership`: one organizer-owned account relationship with
  invited, active, suspended, or ended state.
- `OrganizationRepresentation`: the one accountable organization-level
  representation root. The first and currently fixed type is Executive Board,
  with Provisioning, Active, and reserved Suspended states plus a positive
  aggregate version and reasoned provisioning/activation provenance. It is
  never an edition Department, Position, generic group, or workforce
  assignment.
- `RepresentationAppointment`: one exact person account's versioned Controller
  invitation and accepted term in that representation, separately linked to
  the organization membership and eventual root role assignment.

A platform administrator is not an organizer relationship. Membership
validation rejects that account classification while still allowing the
administrator to be attributed as the actor of later platform provisioning.

ADR 0040 makes Draft-to-Active an explicit representation handoff. Provisioning
creates no person relationship for the platform operator. An invitation may
create an invited membership for the exact active, verified person account but
grants no authority. Initial activation requires at least two distinct accepted
controllers, no unanswered invitation, current aggregate state, and an atomic
change of appointments, memberships, scoped assignments, representation, and
organization. ADR 0043 adds one platform-only emergency containment path: it
closes a person's open Board relationships across every organization, revokes
sessions and authority, deactivates the account, and suspends any Board that
loses its two-controller quorum. Routine expiry, replacement, voluntary ending,
reactivation, and quorum recovery are not implemented.

ADR 0045 permits Page 9 to show a minimized Executive Board governance anchor
above an edition's Helper Board Department. This is presentation composition,
not a stored parent edge or cross-module write. `maru.organizations` remains the
only owner of representation state and appointments; `maru.workforce` remains
the owner of Departments, Positions, and structure-template application. The
Awoostria reference template cannot create, activate, update, or infer
representation, membership, appointment, controller identity, or root
authority.

Page 9a.0 now implements that read composition. The public organizations query
accepts one already-authorized organization identifier and returns exactly a
`governance` discriminator, the fixed **Executive Board** label, and the
truthful `absent`, `provisioning`, `active`, or `suspended` state. It never
returns a representation identifier, appointment, controller, membership,
reason, count, or authority record. Page 9 authorizes the exact edition before
calling it and repeats fresh authorization before releasing the composed
response.

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
- `update_organization_profile(...)`, the atomic exact-organization capability
  command that accepts explicit platform oversight or active Executive Board
  `organizations.change_profile`, locks the record, updates only changed
  complete-profile fields, keeps slug/lifecycle code-owned, and audits field
  names without values.
- `delete_empty_draft_organization(...)`, the atomic platform-only command that
  requires exact-name confirmation and acknowledgement and can remove only a
  Draft whose protected relationship graph is empty.
- `create_convention_series(...)`, the atomic exact-organization capability
  command for platform oversight or `organizations.create_series` that locks a
  non-Closed parent, accepts typed `ConventionSeriesCreationDetails`,
  normalizes the required name, generates a collision-safe slug within that
  organization, validates the complete series, and appends its audit event.
- `update_convention_series(...)`, the atomic
  `organizations.change_series` command used by Page 5 and its API adapter. It
  locks the exact organization-owned series, compares
  the expected profile version, writes only changed brand fields, and commits
  minimized audit plus `organizations.convention_series.updated.v1` and its
  outbox delivery together.
- `provision_executive_board(...)`, the initial platform-only Draft command
  that creates the fixed representation root without enrolling its actor.
- `invite_representation_controller(...)`, the exact-account, reasoned,
  organization-scoped invitation command that creates no authority.
- `respond_to_representation_invitation(...)`, the version-checked self command
  through which only the exact invitee accepts or declines.
- `activate_executive_board(...)`, the platform-only, aggregate-version-checked
  transaction that establishes two-or-more-controller cross-approved root
  authority and changes both representation and organization to Active.
- `emergency_remove_executive_board_controller(...)`, the platform-only,
  reasoned global containment command that locks every open Board relationship
  for one person, revokes sessions and root authority, suspends Boards that lose
  quorum, and deactivates the account atomically.
- `GET /api/v1/organizations/{organization_id}/series`, a platform-
  administrator-only paginated collection scoped before bounded, strict query
  evaluation.
- `GET /api/v1/organizations/{organization_id}/series/{series_id}`, the strict
  scoped record with no accepted query parameters.
- `PUT /api/v1/organizations/{organization_id}/series/{series_id}`, the strict
  complete profile replacement.

Generic unscoped organization APIs remain absent. Page 2 remains platform-only;
Pages 3 through 5 are exact-organization workflows whose Board-authority
browser paths have backend route and policy coverage. Existing series
APIs remain platform-administrator adapters until their separate API policy and
projection contract changes. These record operations create no membership,
governance, event edition, participation, registration, or workforce
relationships.

Page 8 has no declared public API in M2.1. Its HTML adapters call these same
module-owned commands. A future API must define strict projections,
enumeration resistance, retry semantics, authentication, approval, and OpenAPI
evidence rather than saving these models directly.

ADR 0045's public, minimized `executive_board_governance_anchor(...)` query
for Page 9 resolves the exact organization and returns only the
fixed representation label and truthful absent, Provisioning, Active, or
Suspended state. It returns no appointment, email, membership, reason,
controller count, role assignment, or authority provenance. The Page 9 adapter
composes that query with workforce's edition-owned structure projection; the
workforce module does not save organization models. The bounded read query and
focused Page 9/API verification are implemented; template application and
Department mutation remain unmounted and do not write organization state.

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

Representation state and rationale are C1 governance data. Appointment
identity, exact email lookup, response state, and membership relationship are
C2. Only an authorized representation manager may see the bounded directory
and exact account email; an invitee may see only their own open appointment.
The directory filters the exact representation before returning at most the 100
most recently invited terms, ordered by invitation time and stable UUID. Its
sensitive-read audit records only the bounded returned count, never a hidden
tenant total or personal value.
The registered `organizations.representation.changed.v1` event is deliberately
minimized to action, fixed representation code, and resulting state. It does
not carry email, display name, reason text, profile values, or capability lists.

Page 9's governance-anchor rendition is C1 and intentionally narrower than the
Page 8 directory: fixed label plus current representation state only. It does
not authorize a workforce mutation, reveal whether a particular person is a
controller, or turn Board representation into edition participation. Any
future named access explanation still uses the exact authorization and
relationship projection required by UX-020.

## Dependencies and consumers

- depends on the identity account identifier;
- events reference an owning organization and series;
- participation references the owning organization;
- the self-context projection consumes the membership query; and
- the Page 9 presentation consumes the minimized representation-
  anchor query and never writes through it.

## Bootstrap administration

The shared administration menu always exposes the global Organizations row.
Once an authorized view has selected an organization, a section named for it
links to its record, Page 8 **Representation & access**, and Convention series
section, with series creation beside that destination while lifecycle permits
it. Selecting a series adds its own
record and Convention editions destinations; new-edition availability depends
on both organization and series state. Page 9a.0 adds **Organization
structure** once beneath an exact selected edition and only when the same exact
Page 9 view decision succeeds. A user with edition-wide
`workforce.view_structure` can discover that edition even without
`events.view_basic`; inaccessible sibling record links remain hidden. This is
display context only: it
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
deletion remains disabled. Organization, convention-series, membership,
representation, and appointment specialist records are inspection-only so
model forms cannot bypass the audited commands. The purpose-built Page 3
command handles only confirmed empty Drafts.

Page 8 presents provision, exact invitation, self-response, and activation as
separate POST operations. Its forms use closed input contracts: reason is
1–240 normalized characters; invitation takes one exact email and reason;
response takes a positive expected invitation version and `accept|decline`;
activation takes a positive representation version, exact case-sensitive
organization name, and reason. Every scope, actor, state, role, lifecycle,
timestamp, and evidence identifier remains server-owned.

## Failure and retention

Tenant reparenting and cascaded deletion are not ordinary operations. The
empty-Draft command never cascades; protected relationships refuse it.
Convention-series profile versions and their database guard require compatible
writers. A migration fence refuses destructive version-column downgrade while
any series exists; populated recovery uses fix-forward or an approved backup/
PITR plan. Organization closure and data exit still need a future reasoned
workflow.

Representation migrations are additive and must never infer real people.
Existing non-Draft organizations without either a compliant Active Board or a
valid emergency-Suspended Board, and any reserved `executive-board` bundle
conflict, require preflight and explicit reconciliation. Once a representation
write exists, old writers are incompatible: fix forward or restore the whole
database to a consistent
pre-write point, and do not reverse only representation tables while
membership, authority, audit, or outbox rows refer to them. A failed activation
must roll back the entire authority/lifecycle change; pending event delivery is
recovered through the outbox rather than by repeating activation.

Organizations `0009` hardens that boundary with immutable representation,
appointment, and linked root-assignment provenance; exact monotonic versions;
deferred active-Board validation across subjects, memberships, authority,
audit, event, and outbox evidence; and a downgrade fence covering every
governance artifact. `check_representation_readiness` is the read-only
deployment preflight. It emits deterministic counts and bounded organization
slugs, never people or private values, and fails the process when blockers
exist. The complete maintenance-window and fix-forward procedure is in
[`executive-board-migration-and-recovery.md`](../operations/executive-board-migration-and-recovery.md).

The readiness pass is intentionally usable before `0009` and mirrors the
durable `0009` through `0011` assertions through ORM-only reads. Beyond quorum
and cardinality it checks the exact activation timestamp, assignment
effectivity/no-expiry/grantor/reason, immutable root-bundle version/name/
capabilities/creator/approver/reason, linked live authority, bidirectional
Board membership, activation and assignment audit correlation, original
activation event/outbox evidence, and current emergency audit/event/outbox/
identity/revocation evidence. A matching Suspended organization and
representation is governed rather than blocked only when all open Board terms,
memberships, and root authority are closed and that emergency evidence is
complete.

Organizations `0010` prevents platform accounts from receiving any convention
grant or role assignment and completes active Board membership/appointment
provenance. Organizations `0011` installs ADR 0043's emergency transition,
evidence, serialization, quorum, and downgrade guards. Organizations `0012`
then enforces IDN-011 for membership and every representation-appointment
state; participation `0004`, registration `0031`, and workforce `0003` apply
the same account-kind boundary to their owning subject tables. The migrations
lock identity rows, reject direct/bulk SQL bypass, and defer account-kind
reclassification validation to commit. See the
[IDN-011 migration runbook](../operations/idn011-convention-subject-migration-and-recovery.md).

The future ADR 0045 workforce migration must not update organization
representation rows or derive them from Department names. Existing workforce
records named Executive Board are migration-review items, not proof of a Board
and not permission to fabricate or relink governance. Organizations exposes a
read projection only; workforce structure recovery and template receipts stay
within workforce's fix-forward or whole-database recovery boundary.

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

Page 8 tests cover platform/manager/self/ordinary/inactive and cross-tenant
visibility, unknown-account equivalence, platform-subject rejection, duplicate
invitations, self-response stale/replay, activation eligibility and quorum,
non-self cross-approval, exact scope, database constraints, minimized mutation
evidence, rollback, and absence of unrelated side effects. Pages 3 through 5
also exercise active Board assignments and scoped non-staff shell entry.
Focused hardening tests cover generic reserved-role isolation, manager-only
sensitive-read audit, privileged-denial audit, raw scope/provenance/version
mutation, fabricated activation, cross-organization evidence isolation,
pre-existing platform authority, clean reverse, and artifact-fenced downgrade.
Organizations `0013` hardens the three runtime-executable Board validators and
every persistent trigger caller that reaches them. It preserves OID, owner, and
ACL, validates code-owned pre/post source hashes, fixes the function-local path
to `pg_catalog, public, pg_temp`, qualifies relations and helper calls, restores
the exact historical definitions on a pristine reverse, and refuses reversal
after durable authority activation even if the authorization `0009` recorder
row is missing.
Page projection tests also cover deterministic history ordering, the 100-row
ceiling, foreign-tenant exclusion, bounded audit count, and safe 503 behavior
when the sensitive-read audit append itself fails.
Populated local upgrade through organizations `0012` and the three other
IDN-011 module guards passes. Before the `0013`/workforce `0005`/authorization
`0009` hardening boundary, the `maru_consolidated_demo` rehearsal applied the
then-current 106 migrations, contained 80 synthetic accounts, two
organizations, and six editions, and reported readiness 16/16 with zero
blockers. Treat that as a prior baseline, not current-graph evidence; rebuild
the demo and restore drills at the new convergence leaf before release.
Fifty-eight combined representation/migration/readiness tests, five emergency-
focused tests, and a 71-test adjacent IDN-011 batch pass. The readiness/core
focus passes 10 tests, the representation/platform matrix passes 126, and the
final consolidated backend invocation passes 792 tests with 90.01 percent
coverage and no warnings. Automated accessibility, complete visual states,
representative deployment/PITR, and owner rehearsal remain release gates.

Page 9a.0 tests additionally prove absent and Provisioning anchor states, the
fixed identity-free label, separation from a same-named operational Executive
Board Department, platform non-participation, canonical navigation, and safe
foreign/dependency denial. They are included in the current 52-test Page 9/API/
catalog/template focused run and the definitive 1,239-test full-suite run at
90.35 percent branch coverage; narrow-viewport evidence for this slice remains
open.

## Limitations

Page 8's Executive Board provisioning, invitation, acceptance, initial
activation, and platform emergency containment are implemented and backend-
verified. Local migration/restore evidence is not representative production
recovery or PITR certification. Appointment expiry, withdrawal, routine
replacement/ending, planned suspension/reactivation, quorum recovery, legacy
active-tenant reconciliation, invitation notification delivery, organization
and series lifecycle transitions beyond initial activation, slug migration, publication,
processors, ownership transfer, closure/data exit, and the complete
convention-owned organizer experience remain. Page 9a.0 implements and
focused-tests the minimized governance-anchor query, exact navigation, strict
read API, and principal-specific view/manage summary. ADR 0045's structure
aggregate, Department mutation services/routes, migrations, full effective-
access header, responsive/accessibility evidence, and owner walkthrough remain
open. Platform administration remains non-participating throughout.
