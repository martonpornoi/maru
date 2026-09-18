# ADR 0107: Retain each person's own approval of the Programme Volunteer starter

- Status: Accepted; implementation and native acceptance pending
- Date: 2026-09-18
- Extends: ADRs 0080, 0081 and 0106 without changing their existing workflows
- Requirements: HR-012, IDN-012, IDN-014, AUD-001 and NFR-013
- Issue: [#175](https://github.com/martonpornoi/maru/issues/175), child of #108/#48

## Context

A blank Programme organization needs an immutable compatible Position template
before it can create a volunteer Position and genuinely staff the timetable.
The candidate already pins the minimal `workforce-volunteer@1` template, but the
existing starter command admits only Workforce-only and accepts a selected
approver email. That input cannot demonstrate the second person's own Programme
decision. A fixture must not invent a template or impersonate that decision.

## Decision

Workforce owns a separate Programme starter request and one immutable terminal
decision. They retain exact organization/series/Programme-edition context, fixed
versioned definition/digest, author, distinct named approver, bounded reasons,
seven-day deadline, original retry identities and audits. These two records are
necessary for pending recovery, cancellation, concurrent terminal arbitration and
exact output attribution; a signed browser payload alone is not durable approval.
Do not reuse Authorization's recipient-access requests to approve a template.

Only current ordinary verified accountable controllers with Organization role
management and Edition structure authority may act. The named approver personally
approves or declines in their authenticated session; the author can cancel pending
intent. Approval requires both original people's current source authority and
unexpired intent. Other terminal actions still require the actual actor's current
authority. Expiry is derived, not an automatic write. Exact authorized retries
recover original results; changed intent/outcome/reason conflicts.

The one definition is the existing Workforce volunteer starter: limited
`events.view_basic` and `workforce.view_structure`, semantic `volunteer` capacity,
default headcount one and the existing immutable name/description. No configurable
capability picker or new role recipe is introduced. Approval atomically creates
the RoleBundle through public Authorization commands and the PositionTemplate
through Workforce, or explicitly reuses an exact compatible historically proven
existing definition. Conflicting reserved meaning fails closed.

The template is Organization-owned and may be reused outside the originating
edition when another exact profile allows its meaning. Explain this broader
definition scope before both people's actions. It grants nobody authority and
creates no Position, opportunity, application, assignment, Availability, Shift,
Participation, Registration, payment, attendance or unrelated communication.
Those later decisions remain independently authorized owner commands.

New intent and approval belong to the same Draft/Preparing private-planning
phase as Position creation. A later phase cannot publish a new starter through
this setup task; authorized review and pending cancellation/decline retain their
own existing-evidence purpose without implying a new planning write.

Canonical authority/scope/person locks precede publication. Native guards retain
immutable intent, exact scope/people/definition/audit/output, one terminal outcome
and anti-truncate protection. Unused contraction is serialized; retained evidence
requires fix-forward or mutually consistent recovery. Both new relations remain
runtime SELECT-only in production during dormant development; candidate writes
are separately explicit. Current profiles and the legacy Workforce-only command
are not broadened or redesigned.

Only the author and named approver may review a request after current admission.
Sensitive named reads are audited; bounded inventories fail rather than truncate,
and final rendered disclosure is revalidated. Preview binds the originally
selected person, never a subsequently re-resolved email. The task sits beside
Position creation in the existing shell; no competing navigation system or
platform-admin operational override is introduced.

Retain the minimal request/decision under the security-extended authority-evidence
purpose. Cancellation/decline/expiry grant nothing and never delete history.
Stopping an edition preserves this shared definition and its approvals; it does
not imply revocation of an assignment, and this workflow creates none.

## Alternatives and acceptance

- Direct fixture writes or a substituted profile would hide the missing workflow.
- Immediate approval from an email would misattribute another person's action.
- Recipient role requests describe a different output and must not become generic
  approval storage.
- A generic template/role approval platform and redesign of legacy Workforce-only
  setup are unnecessary for this bounded Programme requirement.

Cover ordinary source admission, own-person decisions, scope/field isolation,
expiry, exact retries, incompatible existing meaning, concurrent terminal actions,
rollback, native drift/permissions and recovery. Connect genuine blank setup and
P06 staffing. Schema-only fingerprints are not native acceptance. PostgreSQL debt
remains #102 and representative human comprehension remains #92; #97/#109 and
supported-profile promotion are still separate gates before closing #108/#48.
