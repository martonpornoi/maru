# Workforce-only progressive adoption checkpoint

Date: 2026-08-26

Status: Implemented and locally certified for pull-request review; hosted
acceptance, deployment, and external owner acceptance remain open

## Outcome

Maru now has its first executable progressive-adoption profile. A convention
can establish the minimum trustworthy Organization, Convention series, and
Event edition foundation, adopt only Workforce, appoint accountable Maru
operators, and use the existing Structure-to-Shifts journey without setting up
attendee Registration, payments, attendance, or unrelated modules.

This is an evaluation-ready product boundary, not a production-cutover claim.
The branch deliberately exposes its portability, degraded-operation,
decommissioning, retention, deployment, and owner-acceptance gaps.

## Human journey

An active platform administrator opens **Set up Workforce** and chooses one of
three paths:

1. create an Organization, Convention series, and Event edition;
2. reuse an Organization and create its series and edition; or
3. reuse an existing series and create only the edition.

The form asks only for the names that are not being reused, edition dates, and
an IANA time zone. Maru applies internal `en` and no-currency `XXX` defaults.
One atomic idempotent command creates the missing foundation, stores
`workforce_only@1`, writes minimized audit and setup-receipt evidence, and
either reuses an existing accountable representation or provisions truthful
**Maru operators**.

A newly provisioned organization then requires at least two distinct operator
invitations, each person's own acceptance, and platform activation. The
activated operators see Workforce, Setup, and Security destinations for the
edition. They do not see attendee Registration, payments, attendance summaries,
reports and badges, or unrelated planned modules. Specialist Django records
remain behind an explicit disclosure and require their own authorization.

After creating the first Department, a fresh organization may create one safe
Volunteer Position template from the Positions workspace. One accountable
controller supplies a retained reason and a different active accountable
controller approves the immutable RoleBundle. This action defines minimal
reusable Position meaning but grants nobody access and creates no Position,
person relationship, Participation, Registration, Availability, or Shift.

Exact-edition management links focus the menu and workspace selector without a
prior session selection. Public opportunities and applications use Volunteer
navigation with an explicit no-registration/no-payment boundary. Personal
Workforce pages focus on My Maru and My Workforce.

## Product and architecture decisions

- `EventEdition.adoption_profile_code` and
  `EventEdition.adoption_profile_version` are immutable in Django and
  PostgreSQL. Existing editions backfill to `full_convention@1`.
- `workforce_only@1` adopts identity, organization/series/edition,
  authorization, audit, effects, privacy operations, and Workforce. It does not
  adopt attendee Participation, Registration, finance, attendance,
  accreditation, Applications, Charity, Communications, Catalog, Venues, or
  Logistics.
- Setup creates no record in an unadopted product module. Public Registration
  configuration cannot discover a Workforce-only edition.
- A Workforce account, membership, assignment, Availability plan, or Shift
  commitment does not imply attendance, attendee Registration, or payment.
- New narrow organizations may use `maru_operators` without claiming that
  software operators form a legal Executive Board. Existing
  `executive_board` organizations and historical evidence retain their exact
  meaning.
- The accountable root keeps the existing two-person ceremony, immutable
  authority, cross-approval, audit, exact provenance, runtime containment, and
  recovery controls.
- Ordinary edition and Workforce capabilities retain an exact-edition minimum
  scope. Only the canonical reserved Maru-operator root may store them at
  organization scope, and policy applies that root only to Workforce-only
  editions. Django and PostgreSQL reject broader direct grants or generic role
  assignments.
- Adoption is evaluated before platform administration, direct grants, or role
  assignments. A platform administrator is not an invisible bypass for an
  unadopted exact-edition module.
- Profile expansion is not an edit. An ordinary Maru operator cannot create a
  full-convention edition. A later expansion requires a reviewed platform
  decision and does not mutate the existing edition's meaning.
- Position assignments retain profile-matched evidence. Full-convention
  activation continues to create and end a Participation capacity;
  Workforce-only activation and ending never create Participation.

ADR 0080 contains the durable decision and supersedes ADR 0040 only where the
older decision assumed that every organization's accountable root must be
called an Executive Board.

## Main implementation map

- `maru.events.adoption` owns the code-defined profile catalog and capability
  boundary.
- `maru.events.workforce_adoption` owns the atomic guided setup command and
  idempotent result.
- Events models, forms, services, API, and browser records persist and explain
  the immutable profile.
- Organizations own the representation catalog, neutral representation
  commands and queries, Maru-operator lifecycle, and truthful page language.
- Authorization resolves the profile with every exact-edition target, denies
  unadopted modules before broader authority, filters generic access
  management, and preserves the reserved root's purpose boundary.
- Workforce assignment services, models, commands, and database evidence use
  the edition profile to decide whether Participation capacity is required or
  forbidden.
- `maru.workforce.starter_templates` owns the independently approved, minimal
  Volunteer Position starter and its no-side-effect contract.
- The Django shell, context API, Staff Console, navigation, and public
  Registration discovery consume the same code-owned boundary.

## Schema and recovery

The branch adds these migrations:

- Events `0010_workforce_adoption_profile` adds immutable profile facts, the
  append-only setup receipt, profile validation, and a downgrade fence once a
  Workforce-only edition or receipt exists.
- Organizations `0014_purpose_bounded_representation` generalizes the
  representation type without relabelling Board history and installs matching
  Maru-operator integrity helpers.
- Authorization `0019_progressive_adoption_authority` adds the new root to
  exact provenance, closes direct and generic organization-wide Workforce
  authority, and retains the versioned runtime-role boundary.
- Workforce `0014_workforce_only_assignment_evidence` makes the assignment
  database guard require Participation capacity for full-convention editions
  and forbid it for Workforce-only editions.

Reverse migration is allowed only before durable use. Once a Workforce-only
edition, setup receipt, Maru-operator root, or profile-specific assignment
exists, the supported response is fix-forward or whole-database restore, not
partial evidence deletion. The operations runbook records migration order,
acceptance checks, failure behavior, and the current continuity limits.

## Verification

Completed for the pull-request head before this checkpoint was finalized:

- a fresh PostgreSQL database applies the complete migration graph;
- the fresh profile and original policy ceiling proof passes 14 tests;
- 64 structure, assignment, adoption, and access-management tests pass
  together;
- 99 of 100 broader edition, page, representation, navigation, and policy tests
  passed on the first run; the one scope regression was corrected and its
  original test is included in the fresh passing proof;
- 11 focused runtime-role/readiness tests pass with the new exact function and
  trigger contracts;
- a consolidated 67-test adoption, navigation, shell, assignment, and Position
  regression passes after the visible first-use corrections;
- all 29 Staff Console component/accessibility tests and strict TypeScript
  checking pass;
- Ruff formatting and lint pass across source and tests, and strict mypy passes
  across 373 source files;
- documentation policy validates 347 Markdown files and 207 requirement
  identifiers; PyDocLint and the semantic docstring validator pass; and
- warning-fatal Sphinx/AutoAPI builds the complete documentation site;
- Django reports no model migration drift; and
- `git diff --check` passes after documentation whitespace correction;
- the clean-tree `scripts/certify.ps1` gate passes the complete unit and
  eight-shard integration suite, combined branch-aware coverage, package and
  dependency checks, production settings, generated contracts, frontend
  production build, and migration recovery for one exact commit; and
- a synthetic browser rehearsal covers platform setup, two distinct operator
  invitations and activation, Department creation, independently approved safe
  Volunteer starter, Position and opportunity publication, purpose-bounded
  volunteer application, independent assignment approval, deliberately shared
  Availability, Shift creation/publication, claim, organizer confirmation, and
  locked coverage. Desktop at 1,280 CSS pixels and mobile at 390 CSS pixels
  show no inspected console warning/error or page-level horizontal overflow.
  Database inspection confirms zero Participation, Registration, attendee
  membership, and other directly edition-owned unadopted-module rows; the one
  application is a legitimate Position application and the active assignment
  has no Participation-capacity pointer.

The browser evidence uses synthetic accounts and a deliberately created
verified volunteer identity rather than real owner acceptance. Pointer
interaction verified the mobile drawer; the browser abstraction did not
provide reliable keyboard activation evidence, so automated keyboard,
Escape, and focus tests remain the executable proof. Hosted pull-request
acceptance, representative screen-reader review, and external two-human owner
acceptance remain required before production claims.

## Known limits and risks

- The current import path is the existing versioned Workforce structure
  template plus manual purpose-built editors. There is no accepted general
  partner-data import, preview, correction, or provenance format yet.
- Existing scoped APIs and browser views are not a complete continuity export.
  There is no printable rota, offline/manual operation pack, or reconciliation
  workflow.
- There is no self-service profile expansion, stop, or destructive uninstall.
  Durable evidence remains under lifecycle and retention policy.
- Exact Availability retention, legal holds, disposal execution, deployment,
  restore/PITR, runtime-role provisioning, worker supervision, load,
  safeguarding, training, and external owner acceptance remain production
  gates.
- UX-029 still requires the full width, zoom, keyboard, representative screen
  reader, reduced-motion, mutation-role, stale, failure, and read-only matrix.

## Smallest next actions

1. Deliver this exact branch through the protected pull-request gate without
   bypassing hosted acceptance.
2. Build and rehearse the Workforce continuity package: accepted import,
   preview and correction, export, printable/manual fallback, and
   reconciliation evidence.
3. Define explicit profile expansion and stop-operation procedures without
   mutating or deleting historical meaning.
4. Complete UX-029 and two-real-human owner acceptance for Assignment and
   Shift decisions.
5. Contract the next standalone profile only after the Workforce-only recipe
   has earned trust: Programme, Communications, Charity art auction, or
   Registration without payments.
