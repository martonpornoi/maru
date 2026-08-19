# ADR 0051: Typed applications and policy-governed profile extensions

- Status: Accepted
- Date: 2026-08-09
- Clarifies: ADRs 0007, 0029, and 0047
- Requirements: REG-002, REG-012, REG-015, REG-022 through REG-024, KNO-004,
  KNO-005, KNO-009, PRI-001, and PRI-003

## Context

Organizers need a useful convention-registration base, fields added after
registration, and many application forms such as DJ, dance competition, Maid
Cafe, adult performance, volunteer, helper, merchandise, feedback, idea, and
damage report. A single generic response table would mix admission, sensitive
profile data, review authority, and downstream operational records. Arbitrary
field ACLs would also create a second authorization system.

## Decision

Maru ships immutable, code-owned starter definitions with stable version and
content digest. Starting setup always copies one selected starter into an
edition-owned draft with source actor, time, version, and digest. The copy is
independent and must be reviewed and activated through the governed
registration commands; later catalog changes never mutate organizer data.

Post-submission profile extensions use one closed reader audience: self,
exact registration staff, one exact active Department, confirmed attendees,
or public. Writer policy is separate. Existing compatibility visibility is a
derived database-guarded value, not an additional audience. Values remain
append-only. Confirmed-attendee and public reads additionally require current
directory consent and confirmed/check-in state; withdrawal removes the
projection immediately. Platform-administrator identity alone grants no
profile-value access.

All non-registration forms live in a typed `applications` bounded context.
Definitions are versioned drafts with sections, closed typed questions,
eligibility, cardinality, windows, owner Departments, exact immutable role
versions, and optional named reviewers. Activation validates the complete
graph; active definitions are immutable and later edits use a traceable
copy-on-write successor. Answers and reviews retain append-only provenance.
Acceptance may create only a closed typed target receipt; a downstream domain
must consume that receipt through an explicit adapter. Application state never
creates a ticket, payment, role, or second registration.

Sensitive, adult, and case-like starters require explicit code-owned policy
before activation. Applicant, reviewer, and staff projections filter answers
by their declared audience, and sensitive reads are separately audited.

## Consequences

- Most editions receive a safe starting point without sharing mutable
  configuration.
- New profile fields and form starters can be added through a closed catalog
  and command vocabulary rather than schema forks.
- Reviewer assignment can use exact users or immutable roles without Django
  Groups or page ACLs.
- General form construction is reusable while submissions advance into typed
  domain work instead of becoming permanent unstructured spreadsheets.
- Richer visual editing and additional downstream adapters may evolve without
  weakening the stored lifecycle and evidence boundary.

## Alternatives considered

### One universal registration record for every form

Rejected. It would create duplicate registrations and incorrectly couple
applications, safety reports, volunteering, and feedback to admission.

### Live-link every edition to a universal template

Rejected. A platform update could silently change an active convention form.

### Per-field lists of arbitrary users and groups

Rejected. Closed audiences plus exact scoped capabilities are explainable,
testable, and consistent with Maru's authorization lattice.
