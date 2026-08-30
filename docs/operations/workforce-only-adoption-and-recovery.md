# Workforce-only adoption and recovery

**Audience:** Platform administrators, deployment operators, and maintainers
rehearsing the first bounded Maru adoption profile  
**Outcome:** Establish or recover a Workforce-only foundation without enabling
Registration, payments, attendance, or unrelated modules  
**Requirements:** IDN-012, IDN-014, EVT-006, HR-013, UX-030, NFR-003, and
NFR-013\
**Decisions:** ADR 0076 as partially superseded by ADR 0080

This runbook describes repository-owned behavior and synthetic rehearsal. It is
not production approval, a retention policy, or authority to import personal
data. Complete restore/PITR, deployment, representative owner, assistive-
technology, and partner cutover evidence remain required before production use.

## Profile boundary

`workforce_only@1` uses identity, Organization → Convention series → Event
edition, authorization, audit, effects, privacy operations, and Workforce. It
does not adopt attendee Participation, Registration, payments, attendance,
accreditation, catalog, charity, programme applications, Communications,
Venues, or Logistics.

The required organization/series/edition spine is operational scope, not an
all-platform commitment:

- Organization is the tenant, data-controller, and accountable-access scope;
- Convention series is the recurring event identity; and
- Event edition supplies the exact dates, time zone, lifecycle, operational
  isolation, and history for Workforce decisions.

## Pre-deployment review

1. Back up the database under the deployment's accepted recovery procedure.
2. Confirm the release contains all four migrations:

   - `events.0010_workforce_adoption_profile`;
   - `authorization.0019_progressive_adoption_authority`;
   - `organizations.0014_purpose_bounded_representation`; and
   - `workforce.0014_workforce_only_assignment_evidence`.

3. Run migration-plan and drift checks. The dependency graph applies Events
   first; Workforce and Authorization follow once their dependencies permit,
   and Organizations follows Authorization. Django may display other
   independent application migrations between those steps.
4. Confirm existing editions are expected to become
   `full_convention@1`. The additive migration must not relabel an existing
   representation or create a Maru-operator record.
5. Confirm the configured runtime PostgreSQL role can receive the updated
   catalog. Runtime execution closure V3 adds only
   `maru_assert_active_maru_operators(uuid)` and
   `maru_assert_active_maru_operators_v0009(uuid)` to V2. The setup-receipt
   relation is runtime-readable and insertable, never normally updateable or
   deletable.
6. Use only synthetic people and reserved example domains for rehearsal.

## Apply and verify migrations

Use the repository's normal locked environment and migration command. Then
verify:

- `manage.py migrate --plan` has no pending migration;
- `manage.py makemigrations --check --dry-run` reports no drift;
- every EventEdition has a supported profile code and version;
- every pre-existing edition is `full_convention@1`;
- no pre-existing `OrganizationRepresentation.code` changed;
- the runtime-role and authority-provenance readiness checks pass with exact
  function fingerprints and grants; and
- the application health/readiness projection remains value-minimized.

Do not hand-edit the migration recorder or compensate for a failed data check
with an inferred person, Board, operator, role, Participation, or Registration
record. Keep the release stopped, diagnose the exact incompatible state, and
fix forward or restore the database.

## Establish a Workforce-only workspace

1. Sign in with an active platform-administrator account.
2. Open **Platform administration → Set up Workforce**.
3. Choose the highest foundation already present:

   - start a new organization and convention;
   - reuse an organization; or
   - reuse a convention series.

4. Enter only the fields shown for that choice and the edition name, dates,
   and IANA time zone.
5. Review the explicit **Only Workforce is adopted** boundary and submit once.
6. If redirected to **Representation & access**, invite two distinct active,
   verified person accounts as Maru operators. Each person signs in and accepts
   their own invitation. A platform administrator then confirms the exact
   organization and activates the representation.
7. Open **Organization structure** and create or apply the required Department
   structure.
8. Open **Positions**. If no compatible published Position template exists,
   one accountable controller uses **Create the safe Volunteer starter**,
   enters a different active accountable controller's exact email, and records
   why the starter is needed.
9. Create and publish the required Positions. Propose one relationship-bounded
   synthetic volunteer, then have the other accountable controller approve the
   exact assignment in a separately authenticated session.
10. Confirm that approval activated the scoped RoleAssignment while the
    assignment's `participation_capacity_id` remained null and exact-edition
    `Participation` and `ParticipationCapacity` counts for that person remained
    zero.
11. While the assignment remains active, complete the bounded Availability and
    Shift journey. Then end the assignment through a freshly authenticated
    revoker. Confirm that the RoleAssignment is revoked, the retained assignment
    is ended, its Participation-capacity pointer remains null, and both
    Participation counts remain zero.

Do not give one human two accounts to simulate independent control. Do not call
Maru operators an Executive Board unless they genuinely hold that role. If an
existing organization already has an Executive Board representation, retain
and use it rather than provisioning another root.

## Acceptance checks after setup

For the exact edition, verify all of the following:

- adoption profile displays **Workforce only** and cannot be edited;
- `en` is present and currency is explained as not involved rather than shown
  as a payment setting;
- Today presents workspace and scheduling context, not attendee/payment counts;
- navigation contains Workforce, purpose-matched Setup, and Security but not
  People attendance, Registration, payments, or Reports and badges;
- a direct exact-edition link selects that edition and keeps the same focused
  menu even in a session that has no previously selected workspace;
- if the safe Volunteer starter was needed, its immutable role contains only
  `events.view_basic` and `workforce.view_structure`, the initiating and
  approving controllers differ, and creating or replaying it produced no
  Position, assignment, person relationship, Participation, Registration,
  payment, Availability, or Shift;
- generic access management does not list a group containing an unadopted
  module capability and refuses a crafted assignment attempt;
- an operator can use the complete Workforce journey but receives
  `module_not_adopted` for Registration and Participation staff-summary
  capabilities;
- platform administration receives the same modular denial at exact edition
  scope;
- public Registration discovery does not return the edition;
- public volunteer pages expose only Volunteer navigation and explain that the
  account is not attendee Registration, attendance, or payment; personal
  Workforce routes focus on My Maru and My Workforce;
- no Participation or unadopted application row was created by setup, login,
  context selection, invitation, acceptance, or representation activation;
- Position-assignment proposal creates no authority or Participation evidence;
- independent assignment approval creates the scoped RoleAssignment but leaves
  `participation_capacity_id` null and creates no `Participation` or
  `ParticipationCapacity` for the exact person and edition;
- retained ending revokes the RoleAssignment while the assignment pointer stays
  null and both exact-person, exact-edition Participation counts stay zero; and
- the specialist record index stays collapsed unless the person explicitly
  asks to browse it.

Use the focused integration test and browser-rehearsal instructions referenced
by `CURRENT.md` for reproducible local evidence. Absence of rows should be
checked by exact app/model ownership, not inferred from an empty page.

## Coexistence and data movement

The convention's incumbent attendee, finance, programme, communications,
venue, and logistics systems remain authoritative. Workforce-only setup sends
them nothing and receives nothing from them. Do not connect systems through
ad-hoc database writes or CSV loads.

Current supported setup paths are the versioned copy-on-write Workforce
structure template and the purpose-built manual editors. A partner-specific
bulk importer requires its own schema, provenance, preview, correction,
authorization, minimization, replay, error, retention, and removal contract.

A complete continuity export, printable rota, offline/manual reconciliation
pack, and automatic decommissioning are not implemented. Existing authorized
views and APIs are not a substitute for those operational guarantees. Record
that limitation in partner acceptance and keep a separately approved incumbent
fallback until those gates pass.

## Failure and recovery

### Setup validation or dependency failure

The command is atomic. Correct the input or dependency and retry with the same
idempotency key only when the intended normalized request is unchanged. A
changed request must use a new key. Do not delete the retained receipt to force
a replay.

### Partial state appears after an interrupted request

Treat this as an integrity incident: the contract requires all-or-nothing
commit. Stop further setup for the affected scope, preserve logs and audit
evidence, and verify Organization, series, edition, representation, receipt,
audit, domain event, and outbox correlation. Fix forward or restore the whole
transactional database; do not manually remove a subset.

### Authority or runtime readiness fails

Keep web and worker cutover stopped. Compare the exact migration recorder,
function source fingerprints, search paths, trigger attachments, owners,
PUBLIC grants, runtime grants, role attributes, and relation ACLs against the
current code-owned catalog. Never make a readiness probe pass by granting broad
function or table privileges.

### Assignment evidence does not match the edition profile

A null `participation_capacity_id` is required for a governed active or ended
`workforce_only@1` assignment. Do not manufacture attendee Participation to
"repair" it. In `full_convention@1`, where Participation is adopted, the same
null pointer is an integrity conflict; a non-null pointer in Workforce-only is
also an integrity conflict. Stop assignment writes for the exact scope,
preserve receipts, audit, events, RoleAssignment, Participation, and capacity
evidence, and diagnose the immutable edition profile and complete transaction.
Fix forward or restore the mutually consistent database. Never clear valid
full-convention evidence or create forbidden Workforce-only evidence merely to
make one row pass validation.

### Stop using Workforce

Stop new operational writes through an approved edition lifecycle and access-
revocation plan. Preserve required audit, authority, assignment, Availability,
and Shift evidence under an organization-approved retention policy. There is
no safe destructive profile uninstall or in-place conversion. Database
downgrade fences intentionally refuse removal after durable profile,
representation, authority, or setup-receipt evidence exists.

### Expand beyond Workforce

Do not mutate the existing edition profile or grant an incompatible group. A
platform administrator must use an accepted expansion/profile workflow. Until
that workflow defines impact preview, data creation, integrations, retention,
rollback, and human confirmation, create no implied Registration or attendance
state.

## Evidence to retain

- exact release commit and migration plan;
- backup/restore reference appropriate to the deployment;
- minimized migration and readiness results;
- setup mode, receipt identifier, edition identifier, profile code/version,
  and audit correlation;
- representation type and activation outcome, without copying unnecessary
  controller contact data;
- assignment state, RoleAssignment activation or revocation state, nullable
  Participation-capacity pointer shape, and exact-person, exact-edition
  Participation and ParticipationCapacity counts;
- automated test and browser-rehearsal results; and
- explicit open production gates, fallback owner, and cutover decision.
