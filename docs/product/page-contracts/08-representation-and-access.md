# Representation & access contract

- Status: Truthful Executive Board and Maru-operator initial lifecycles
  implemented, hardened, and locally verified; final suite, representative
  accessibility, complete visual-state, and owner rehearsal pending
- Route: `/admin/platform/organizations/<organization-slug>/representation/`
- Mutations: POST-only child routes `provision/`, `invite/`,
  `appointments/<appointment-id>/respond/`, and `activate/`
- API: none declared in this slice
- Requirements: IDN-002, IDN-004, IDN-005, IDN-007, IDN-009, IDN-011,
  IDN-012, IDN-014, UX-012, UX-013, UX-017, UX-019, UX-020, UX-024,
  UX-029, UX-030, AUD-001, AUD-005, NFR-001 through NFR-004, NFR-008,
  NFR-009, and NFR-013
- Decisions: ADRs 0003, 0031, 0038 through 0044, 0055, and 0080

## Purpose and primary users

Establish one organization's truthful accountable representation through a
visible, human-controlled handoff:

```text
platform provision -> exact invitations -> each person answers
  -> two-or-more-person activation -> organization Active
```

The platform administrator oversees the initial boundary and is recorded as an
actor. They never become a representation controller, organization member,
role-assignment principal, edition participant, registrant, volunteer, or
workforce assignee.

The page serves three deliberately different audiences:

- an active platform administrator may provision and activate initial
  governance and may manage invitations under explicit platform policy;
- an organization-scoped representation manager may see and manage the
  appointment directory allowed by policy; and
- an exact active, verified invitee may see and answer only their own open
  invitation.

This is not a department editor, staff roster, Django Group page, public
controller directory, legal-office inference, or complete page-level access-
control list.

## Placement and navigation

After an organization is selected, the shared sidebar shows
**Representation & access** beside **Organization record** and the scoped
convention-series row. The page uses the same Maru logo, shell, title, purpose,
access summary, modules, form language, tables, focus behavior, and narrow
stacking as the platform setup record journey. It never renders a second global menu, workspace
selector, or Quick Start strip.

The first task-oriented people-to-governance journey reaches this page from
**User accounts**. An authorized platform operator may first find an existing
person or use the contextual **Invite account** action. The invitation outcome
states that the result is an identity only, then directs the operator to choose
an organization and open its exact **Representation & access** route. The
handoff does not create a membership or representation appointment and does not bypass
this page's exact-account eligibility and disclosure rules.

The page presents its existing commands as one visible three-step progress
sequence: **Choose accountable access**, **Invite at least two controllers**,
and **Activate governance**. The current persisted state says
which step is complete, current, waiting, or unavailable and gives the next
authorized action. A shortcut back to **User accounts** may help prepare
another identity, but it never implies that the account has been appointed.

The organization slug is trusted route scope. Selected-edition session state
is irrelevant and never grants authority. A manager reaches the page from the
organization record/sidebar. An invitee reaches their own open appointment
through `/admin/invitations/`; canonical inbox/email delivery remains a later
discoverability improvement.

GET and every POST must authorize before disclosing whether another tenant,
appointment, or account exists. An unknown scoped record may return 404 only
after the caller has authority to know the parent organization. A wrong-subject
appointment response is indistinguishable from an unknown appointment.

## Record and lifecycle

The page presents the persisted code-owned representation name and purpose,
organization name and lifecycle, representation state and aggregate version,
minimum controller count, and at most the 100 most recently invited
appointments.
Appointment history is filtered to the exact representation before slicing and
is ordered by descending invitation time with appointment UUID as a stable
tie-breaker. A truncated result says that it is the latest bounded window.

Representation lifecycle for this slice:

```text
absent -> Provisioning -> Active
```

Appointment lifecycle for this slice:

```text
Invited -> Accepted -> Active
        \-> Declined
```

`Suspended` representation and `Ended` appointment states are durable model
vocabulary for later reasoned suspension, removal, replacement, and recovery
commands. No form on Representation & access may set them directly. Until those commands and
their quorum/revocation tests exist, the full ongoing representation lifecycle
is incomplete.

## Step 1: provision the representation root

Only an active platform administrator may provision. The exact organization
must be Draft and must not already have a representation. Provisioning creates
one code-owned `executive_board` or `maru_operators` representation in
`Provisioning` at aggregate version 1. Executive Board is valid only when the
people really hold that constitutional office; Maru operators identify
software responsibility without making that claim. The choice is immutable.
Provisioning creates no person appointment, membership, authority, series,
edition, Participation, Registration, Department, Position, or Workforce
record.

| Field | Type and format | Bounds; null/blank | Normalization | Classification and writer | Lifecycle and retention |
| --- | --- | --- | --- | --- | --- |
| `representation_code` | Closed code-owned choice | Exactly `executive_board` or `maru_operators`; null/blank forbidden | No alias or inferred default at the browser boundary | C1 accountability classification; active platform administrator | Immutable after provisioning; existing Board history is never relabelled |
| `reason` | Unicode text | 1–240 characters; null/blank forbidden | Trim ends and collapse whitespace | C1 governance rationale; active platform administrator | Required while organization is Draft and representation absent; retained in governance record and audit purpose, not domain-event payload |

Organization, representation code/name/state/version, actor, timestamps, and
scope are server-owned. The form accepts only `reason` and CSRF. A repeated or
concurrent provision fails with `representation_exists` or the equivalent
safe conflict; it never creates a second root or duplicate success evidence.

## Step 2: invite exact controllers

Invitation is available only while both the organization is Draft and the
representation is Provisioning. The actor must be an active platform
administrator under the initial bootstrap rule or hold
`organizations.manage_representation` at this exact organization.

| Field | Type and format | Bounds; null/blank | Normalization | Classification and writer | Lifecycle and retention |
| --- | --- | --- | --- | --- | --- |
| `account_email` | RFC-compatible email address used for an existing Maru account | Required; null/blank forbidden; bounded by the account email model | Trim and lowercase for exact case-insensitive lookup | C2 account contact; representation manager only; never shown to an ordinary viewer | Accepted only in Draft/Provisioning; used to resolve the account, not copied into the appointment or domain event |
| `reason` | Unicode text | 1–240 characters; null/blank forbidden | Trim ends and collapse whitespace | C1 governance rationale; representation manager | Retained with the appointment and minimized audit purpose; not exposed to unrelated viewers or event payload |

The resolved subject must be an existing active `person` account with verified
email. A platform administrator is always ineligible. No fuzzy matching,
candidate list, account creation, or existence disclosure is allowed. Missing,
inactive, unverified, and platform accounts receive the same bounded
`representation_account_ineligible` presentation. One account may have only
one open Invited, Accepted, or Active appointment for this representation.

A successful invitation atomically creates the Invited appointment and, when
no compatible organization relationship exists, an Invited membership labelled
the selected definition's exact `Executive Board controller` or `Maru
operator` label, then advances the representation aggregate version. An
eligible existing active membership may be reused without weakening its state.
Invitation grants no capability. A suspended membership blocks invitation; a
conflicting ended relationship requires human review instead of silent reuse.

## Invitee response

Only the exact authenticated appointment subject may respond. They must remain
active, verified, and non-platform, and the parent must remain
Draft/Provisioning.

| Field | Type and format | Bounds; null/blank | Normalization | Classification and writer | Lifecycle and retention |
| --- | --- | --- | --- | --- | --- |
| `expected_version` | Positive integer hidden concurrency token | Integer ≥1; null/blank forbidden | Strict integer parsing | C1 control metadata; exact invitee | Compared under row lock; not rendered as content and advances once on a successful answer |
| `decision` | Closed enum | Exactly `accept` or `decline`; null/blank forbidden | No aliases | C1 relationship decision; exact invitee only | Accepted only from Invited; retained as appointment state and evidence |

Accept moves Invited to Accepted and grants no authority yet. Decline moves the
appointment to Declined, records response/end time, and ends only the matching
Invited purpose-matched representation membership. A stale version returns
`stale_representation_invitation`; a replay returns
`representation_invitation_answered`. Neither mutates state or produces a
second success event. Wrong-subject and unknown appointment responses use the
same non-disclosing 404 behavior.

## Step 3: activate governance

Only an active platform administrator may perform initial activation. The
action is offered only for a Draft organization with a Provisioning
representation. It locks and rechecks the organization, representation, every
accepted appointment, and relevant memberships.

| Field | Type and format | Bounds; null/blank | Normalization | Classification and writer | Lifecycle and retention |
| --- | --- | --- | --- | --- | --- |
| `expected_version` | Positive integer hidden aggregate token | Integer ≥1; null/blank forbidden | Strict integer parsing | C1 control metadata; active platform administrator | Compared under lock; stale value fails without mutation |
| `confirmation_name` | Unicode text | Exact current organization name; maximum 160; null/blank forbidden | No case folding or whitespace rewriting | C1 high-impact confirmation; active platform administrator | Used only for this activation attempt; not stored as a second organization fact |
| `reason` | Unicode text | 1–240 characters; null/blank forbidden | Trim ends and collapse whitespace | C1 governance rationale; active platform administrator | Retained with activation/authority provenance; excluded from the minimized domain event |

Activation refuses unless at least two distinct controllers have Accepted, no
controller invitation remains unanswered, and every accepted account is still
active, verified, non-platform, and without a suspended membership. A
pre-existing reserved bundle for the selected representation type is a
conflict for human reconciliation; Representation & access never overwrites it
or uses one type's bundle for the other.

One transaction:

1. creates the selected immutable organization-scoped `executive-board@1` or
   `maru-operators@1` role bundle with its code-reviewed purpose-matched root
   capability set;
2. creates one organization-scoped authority assignment per accepted
   controller, granted by the platform operator and approved by a different
   accepted controller in a deterministic cycle;
3. activates each matching membership and appointment and links the
   appointment to its durable assignment;
4. changes the representation from Provisioning to Active and advances its
   aggregate version once; and
5. changes the organization from Draft to Active.

No controller self-approves. The platform administrator is actor only and does
not receive or approve convention authority. A concurrent or replayed
activation loses on the aggregate version/state check and cannot duplicate
roles, assignments, membership, or evidence.

## Effective access and disclosure

The header must derive its wording from the current principal and persisted
state:

- platform administrators may oversee the initial handoff but are not Board
  members, Maru operators, or convention participants;
- active controllers hold the selected fixed organization root bundle while
  their assignment remains effective and unrevoked; and
- an exact invitee may view and answer only their own invitation.

Managers may see each visible controller's safe display label, exact email,
role, appointment state, and whether root authority is active. An invitee sees
only their own row and no other email. A viewer with basic organization access
but without representation-management authority sees no appointment directory
or hidden principal count. Foreign-organization appointments are excluded
before ordering and applying the 100-row ceiling.

This is a bounded UX-020 slice. It does not yet calculate department, edition,
resource, field, lifecycle-exception, or restricted-case access and must not
offer a generic **Manage access** shortcut that bypasses the underlying
commands.

## Audit, event, and failure contract

Provision, invitation, accept/decline, each root assignment, and activation
produce correlated, value-minimized security audit. Successful representation
changes publish `organizations.representation.changed.v1` and its outbox row in
the same transaction. The payload contains only action, code-owned representation
code, and resulting state. Email, display name, reason text, organization
profile values, password/session facts, and full capability lists are absent.

Sensitive appointment-directory reads and privileged denials retain actor,
action, exact organization scope, target class, time, source, and outcome
without copying personal values. A successful directory-read audit records only
the bounded number of rows returned as `target_count`; it does not calculate or
reveal a hidden total. Focused AUD-001 tests cover a manager read, bounded count,
basic-view redaction, platform-only mutation denial, foreign-organization
isolation/denial, and fail-closed audit-append failure.

Database, read/mutation-audit, or outbox failure returns a generic 503, exposes
no appointment directory or dependency detail, and keeps no partial governance
change. A committed change whose outbox delivery is pending is
recovered through the effects worker/replay procedure; the operator must not
repeat a non-idempotent governance action merely to force delivery.

## Page states

- **Unprovisioned:** purpose and Step 1 shown to platform administrators;
  other authorized viewers receive a truthful waiting explanation.
- **Provisioning:** state/version, bounded visible appointments, invitation,
  exact invitee response, activation readiness, and the three-step progress
  state shown according to policy.
- **Active:** durable representation and assignment outcome shown read-only;
  all three setup steps show complete and initial provision/response/activation
  controls are absent.
- **Validation:** field-local messages and safe input retained; no partial
  relationship or evidence.
- **Stale/conflict:** 409-equivalent explanation with reload guidance; winning
  state remains unchanged.
- **Denied/not found:** no cross-tenant or wrong-principal disclosure.
- **Dependency failure:** generic 503/retry guidance with atomic rollback.
- **Loading:** ordinary server rendering; no invented partial appointment.

## Migration and recovery implications

The schema migrations must be additive and must not infer a representation
type or controllers from staff flags, Django Groups, old role assignments,
account age, email, or demo rosters. Existing Board records retain their type
and existing Draft organizations remain Draft. Every existing Active,
Suspended, or Closed organization without a compliant active representation
must appear in a preflight report and receive an approved reconciliation path
before M2 is called enforced.

Organizations `0009` adds immutable identity/provenance and monotonic-version
guards, deferred exact active-Board validation across organization, account,
membership, bundle, assignment, appointment, audit, domain-event, and outbox
evidence, a populated-data platform-principal preflight, and a governance-
artifact downgrade fence. The read-only
`check_representation_readiness` command reports bounded blocker counts and at
most twenty organization slugs without people or private values.

Organizations `0010` and `0011` harden subject eligibility and emergency
containment. Relationship writers serialize before identity changes; a
platform-only command closes the selected person's open Board relationships
globally, suspends every Board that loses quorum, and emits one correlated
evidence chain per affected representation before the account is deactivated.
Old application connections must be drained before upgrade. Emergency evidence
fences reverse migration; recovery is fix-forward or a whole-database restore
to a consistent pre-emergency point.

Organizations `0014` adds the immutable Maru-operator type, purpose-matched
membership/appointment/root-role validation, two pinned operator helpers, and
a downgrade fence. Authorization `0019` validates representation-control type
and broadens the code-owned organization minimum scope needed by the operator
root. Neither migration creates, relabels, or activates a representation or
person relationship. The bounded-profile procedure is in
[`workforce-only-adoption-and-recovery.md`](../../operations/workforce-only-adoption-and-recovery.md).

Organizations `0012`, participation `0004`, registration `0031`, and workforce
`0003` enforce IDN-011 at the database boundary for every covered convention-
subject relationship. Subject writes lock the identity row; a deferred check
rejects later person-to-platform reclassification while any relationship
remains. Platform accounts remain valid in actor/provenance fields. The
separate [IDN-011 runbook](../../operations/idn011-convention-subject-migration-and-recovery.md)
defines its maintenance-window, count-only preflight, and fix-forward boundary.

After the first representation write, old code is write-incompatible. Roll
forward with compatible code or restore the whole database to a consistent
pre-write point; never reverse only representation tables after memberships,
assignments, audit, or outbox evidence exists. Migration drift, fresh and
populated upgrades, constraint bypass, and rollback/fix-forward rehearsal are
required before release acceptance. The additive schema, drift, populated
local upgrade, empty-database migration, populated restore drill, raw-write
matrix, clean reverse, and populated downgrade-fence evidence pass. The full
procedure is in
[`executive-board-migration-and-recovery.md`](../../operations/executive-board-migration-and-recovery.md).

## Acceptance checks

- Representation & access link appears once at selected-organization scope with correct current
  navigation and no second shell;
- User accounts, invitation outcome, and Representation & access form a
  truthful identity-to-governance handoff with no relationship side effect;
- the three-step accountable-representation progress sequence and next action
  reflect persisted type, state, and current authorization;
- anonymous redirect plus inactive, ordinary, Django staff, platform,
  basic-view, representation-manager, own-invite, wrong-subject, and
  cross-tenant matrices;
- platform administrator remains absent as every convention-subject type;
- exact active verified account lookup with uniform unknown/ineligible result;
- duplicate root and duplicate open-appointment race protection;
- own accept/decline, stale/replay behavior, membership outcome, and no
  pre-activation authority;
- at least two distinct accepted controllers, all-invitations-answered rule,
  eligibility recheck, exact-name confirmation, and reserved-bundle conflict;
- deterministic non-self cross-approval, purpose-matched immutable role
  version, exact organization scope, and atomic Draft-to-Active activation;
- closed input rejection for every forged scope, actor, state, role, version,
  timestamp, lifecycle, or evidence field;
- value-minimized allow/deny/read audit, event registry/schema, transactional
  outbox, failure rollback, and outbox recovery;
- exact-tenant appointment filtering, deterministic newest-first ordering,
  100-row history ceiling, bounded audited result count, and direct audit-append
  failure without directory or dependency disclosure;
- database constraints plus fresh/populated migration and old-writer recovery
  review;
- no department, participation, registration, application, series, edition,
  shift, venue, document, or workforce side effects; and
- keyboard order, focus/error association, screen-reader table/form labels,
  the 320/390/768/958/1,024/1,280/1,920-pixel and 200-percent-zoom matrix,
  every state above, and owner tutorial rehearsal.

## Current verification evidence

The current backend covers provisioning, exact invitation, self accept/decline,
two-controller activation, platform-subject exclusion, scoped non-staff shell
entry, wrong-tenant/wrong-subject non-disclosure, stale and replayed input,
reserved-role conflict, PostgreSQL constraints, transaction rollback, minimized
mutation events, and absence of unrelated domain side effects. Django system
check, migration drift, Ruff, and mypy pass for the consolidated tree. Generic
authority commands and the access workspace cannot list, create a version of,
share, replace, project, or revoke the reserved Executive Board or Maru-
operator role.
The backend also covers atomic global emergency containment from pending or
active relationships, multi-organization authority revocation, quorum-loss
suspension, session/account deactivation, historical approval provenance, and
concurrent relationship/identity serialization. This is an audited service
boundary; a routine lifecycle editor and quorum-recovery UI are not implied.

Focused HTML integration coverage verifies the User accounts handoff links and
the state-aware three-step accountable-representation presentation without
changing the underlying
commands or authorization matrix. The shared responsive drawer and navigation
have source-contract coverage. Authenticated rendered inspection across the
complete ADR 0055 width/zoom matrix is still open.

The last pre-hardening isolated backend run passed 710 tests at 90.03 percent
coverage. On the current hardening tree, 58 combined representation/migration/
readiness tests, five emergency-focused tests, and a 71-test adjacent IDN-011
batch pass. Populated local upgrade through organizations `0012` and the other
IDN-011 module guards, fresh migration tests, the local populated restore drill
through `0009`, sensitive-read/denial audit, generic reserved-role isolation,
and desktop/390-pixel browser smoke pass. Readiness-parity and concurrent
multi-active hardening are still underway. A new clean consolidated full suite/
coverage run, representative deployment/PITR rehearsal, keyboard/automated
accessibility, complete visual-state review, and owner rehearsal remain open.

## Explicit non-goals

- Department/subdepartment hierarchy, leads, deputies, or volunteers.
- Routine appointment expiry, withdrawal, replacement, voluntary ending,
  planned suspension, quorum recovery, or reactivation commands. ADR 0043's
  platform emergency containment is the only implemented ending/suspension
  path.
- General role sharing, ADR 0041 department/resource scope, or a complete
  effective-access editor.
- Edition participation, Chair/position creation, registration, or any
  convention application.
- Public Board publication or reuse of imprint representative text as an
  appointment.
- A new API endpoint before its strict external contract is accepted.
