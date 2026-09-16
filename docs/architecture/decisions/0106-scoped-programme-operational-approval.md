# ADR 0106: Separate Programme responsibility from independently approved access

- Status: Accepted; implementation and native acceptance pending
- Date: 2026-09-17
- Clarifies: ADRs 0003, 0041, 0044, 0080 and 0081
- Requirements: IDN-002, IDN-004, IDN-005, IDN-012, IDN-014, EVT-006,
  EVT-007, UX-020, UX-030, AUD-001 and NFR-013
- Issue: [#108](https://github.com/martonpornoi/maru/issues/108), within #48

## Context

Atomic Programme setup now retains a new edition and first Department without
granting operational access. Existing representation preserves truthful Executive
Board or Maru-operator responsibility and two distinct people's own acceptances.
Neither acceptance nor its fixed root role implies every later Programme power.

The capability catalog has materially different ceilings: Applications call and
review tasks require Department scope; Programme and timetable planning require
Edition scope; reusable Venue facts require Organization scope; physical room
approval requires an exact typed-resource scope. A single organization-wide
Programme role would violate the ordinary-role storage boundary. A new constitutional
root would misrepresent the responsibility already accepted by these people.

Existing public Authorization commands provide independently attributed immutable
role versions, assignments, exact controller provenance, horizons, audit and
effects. Supplying another account as the approver does not itself prove that
person reviewed this particular intent in their own session. Programme continuation
must retain that deliberate decision rather than borrowing an earlier invitation.

## Decision

### Preserve the root; add optional exact operational recipes

Keep Executive Board and `maru-operators@1` unchanged. Initial representation
activation still does exactly its existing ceremony and grants no supplemental
Programme authority. Ordinary active controllers, not generic platform policy,
subsequently propose and approve access through existing persistent authority.

Authorization owns code-reviewed immutable operational recipes: recognizable task
labels, exact capability tuples, version and correct target scope. They are optional
starting definitions, not hard-coded Department titles or a second policy system.
Each future exact Programme profile pins the recipes it supports. Unknown recipes,
versions, unsupported profiles or changed contents fail closed. Current profiles
gain no recipe, capability, destination or assignment.

Separate intake, review management, reviewer, moderator and decision purposes;
ordinary Programme content/hosting/staffing; timetable planning, independent release
approval and publication; Venue catalog, edition selection and exact-room work;
notice preparation/review/handoff; and bounded on-site reading. Reuse existing
Workforce authority where independently sufficient. A recipe does not replace named
review assignment, personal conflict clearance, host/volunteer relationships,
field policies, physical approval or any owner's separation-of-duty checks.

No recipe contains relationship-derived/self capabilities, break-glass recovery,
authority-management powers, or excluded product modules. Some ordinary Venue
capabilities deliberately deny platform fallback; do not remove that flag to make
setup convenient. Exact ordinary role authority remains subject to existing policy.

Organization-scoped Venue-fact management is explicitly broader than one edition
because those facts are shared. Present that consequence separately; never silently
include it in an edition role. Exact-space powers can only be proposed once the
owning selected space and canonical binding exist. Ordinary template composition
never upgrades or rewrites an existing role version.

### One immutable intent and one actual terminal decision

Authorization owns the request and terminal decision, not Events or a browser
adapter writing authorization tables. A request binds its Programme context,
actual target scope, exact recipe, author, named independent approver, eligible
recipient, intended validity, rationale, original retry key/digest and audit.
It grants nothing. Recipient may equal author, but approver differs from both.
No platform account can be the ordinary organizer controller or recipient.

An actual authenticated approver reviews that immutable intent and personally
approves or declines. The author may cancel a still-pending request. A request has
one append-only terminal decision; serialization and uniqueness arbitrate competing
approval, decline and cancellation. Unknown, foreign and unauthorized requests are
non-disclosing, not a directory. Pending views expose only independently authorized
exact people, target labels, capability consequences, interval and rationale.

Approval requests expire after seven days. Expiry grants nothing and does not need
an automatic mutation. A new request is required after expiry or changed intent.
Assignments never start before actual approval: use the later of requested start
and the locked decision instant, retaining that effective result. The requested
end remains unchanged and must still be usable. Existing controller-horizon rules
govern bounded or unbounded requested assignments; this workflow adds no horizon
exception and never creates backdated authority.

Inside one transaction, the approving command joins existing shared authority
fences, resolves and locks canonical owner scope and request, locks all involved
people in UUID order, and rechecks exact profile, recipe, eligible people and both
current controller sources. It reuses an exact historically proven immutable role
or creates the reviewed version through the public owner command, then calls the
public assignment command. The target assignment, its provenance/effects, decision
and audit commit together. A familiar role name, old matching assignment, current
source fingerprint or accepted invitation is not a new approval or replay receipt.

Exact terminal retries reauthorize the actual requesting principal and recover
only the original result. Changed outcome, reason or original intent conflicts.
Source revocation, insufficient horizon, stale scope, retired Department/resource,
unsupported manifest and dependency failure preserve the original pending or
terminal evidence without partial authority. Existing generic role commands and
their provenance meaning are not replaced or broadened.

### Continuation, retention and recovery

Reuse existing genuine-person representation screens. Pending setup explains the
remaining own acceptances, activation and operational approvals honestly. A form
containing someone else's email cannot claim their approval. The independent
approval workspace follows the shared shell, strict input, CSRF, error and pending-
intent recovery contracts. Links and previews grant no access.

Retain minimized request/decision identities, scope, immutable intent and reason
under the existing security-extended authority-evidence purpose. Do not copy private
proposal/review content, credentials or recipient contact directories. Audit
privileged writes and sensitive named reads; failed writes never retain success
evidence. No general message, Participation, Registration, attendance or membership
is created by operational approval.

Native schema must enforce exact scope/evidence, immutable intent/decision,
single terminal outcome, retained foreign outputs and anti-truncate protection.
Unused contraction is serialized; durable requests or decisions require fix-forward
or mutually consistent recovery, never deletion to permit downgrade. Runtime stays
SELECT-only during dormant development. Schema metadata observation is separately
approved and cannot replace native race, rollback, lineage or runtime acceptance.

Stop-use must account for the exact output assignments retained by these requests,
including any deliberately broader shared Venue-fact assignment; an edition change
alone must not be claimed to revoke an organization-scoped grant. Revoke through
existing public commands with current authority and retained evidence, never raw
deletion or inferred replacement.

## Alternatives considered

- Widen `maru-operators@1`: rejected; it changes settled authority silently.
- Invent a third representation: rejected; operational tasks are not a new
  constitutional or accountability root.
- One broad Programme bundle: rejected; owner scope ceilings and separation of
  purposes differ, and optional private layers must remain explicit.
- Treat an approver email or prior acceptance as present approval: rejected; it
  cannot prove this person's deliberate decision on the exact new authority.
- Signed links alone: not the chosen durable boundary; pending cancellation,
  competing decisions, retained output identity and exact retry require accountable
  persisted evidence. A link may locate a request but is never approval or a grant.
- Redesign every existing generic access screen now: outside this increment. Reuse
  the owner commands and add the required Programme continuation without silently
  changing unrelated workflows.

## Consequences and acceptance

Programme setup gains explainable delegated work while existing roots and profiles
retain their meaning. More than one scope may require an explicit request, and
room-specific access follows real room selection rather than being invented up
front. Tests must cover no-grant proposal, actual own approval, two-person control,
scope/field isolation, horizon and revocation, exact retry, races, atomic rollback,
runtime enforcement, recovery and excluded effects. Human comprehension belongs
on #92; full native, logical recovery and integrated evidence remain #102/#97/#109.
This decision is not implementation, profile promotion or production approval.
