# ADR 0102: Governed Programme change communication

- Status: Accepted
- Date: 2026-09-13
- Issue: [#104](https://github.com/martonpornoi/maru/issues/104), under #48's
  existing change-impact/delivery/acknowledgement checklist item

## Context

ADR 0101 supplies exact-purpose read comparisons, not authority to select other
people or send a notice. Ordinary operator output is not a recipient directory.
The Programme department needs to prepare and review a change, deliberately hand
it off and distinguish that claim from the exact person's acknowledgement.
General Communications remains excluded by ADR 0081.

## Decision

Sender-side operator selection requires the separate exact-edition capability
`scheduling.view_change_recipients`, ceilinged to `operator_recipients`. Resolve
one deliberately selected verified person and exact room/Department/edition,
not a general directory, inferred audience or supplied contact address.

The actual sender is authorized before identity disclosure. Ordinary subject
policy independently checks the selected person's Scheduling released geometry,
Venue scope links and, for a Department with adopted Programme staffing,
Workforce scope links. These are eligibility decisions only: never invoke an
operator or personal output query as the recipient and never attribute the
sender's sensitive read to that recipient. Canonical scope and complete sorted
sender/recipient locks precede actor-only final checks. Repeat current subject
eligibility/adoption before final sender authority and mandatory sender audit.

Return only the selected current account/operational label, exact purpose,
staffing-adoption consequence and policy contract version. This is not a grant
version, affected-occurrence proof, copy permission or portable sending token.
Missing, foreign, inactive and ineligible subjects share an unavailable result.
No release or private instructions are read by recipient selection.

The additive native capability migration preserves existing scope ceilings and
rejects downgrade after retained grant/role use. Its expected function definition
is derived from reviewed source, not claimed as observed PostgreSQL evidence.
No current profile pins this capability and no grant or route is created.

The subsequent persisted workflow must keep these facts independent:

1. preparation selects one exact release transition, affected occurrence and
   independently eligible recipient purpose;
2. a different authorized reviewer approves that exact version-bound package;
3. a deliberate manual handoff records only the operator's handoff claim; and
4. only the exact currently eligible recipient acknowledges the exact change.

Export is not handoff, handoff is not delivery-provider evidence, and none is
recipient acknowledgement. An approved notice seen in Maru can be acknowledged
without inventing a previous external handoff. New material changes need new
acknowledgement. No step alters attendance, accepted work or release approval.
Effects delivery requires an explicitly pinned adopted route; otherwise provide
the reviewed manual package without creating general Communications records.

Review may instead reject the package; that immutable rejection prevents handoff
and acknowledgement. Corrections require a new prepared package and independent
review. One notice retains at most one review, one manual handoff claim and one
exact-recipient acknowledgement. Handoff and acknowledgement may occur in either
order after approval, with an optimistic evidence version for each new fact.
Duplicate facts are lifecycle conflicts, not proof of an idempotent retry.
Host/work input selects an owner relationship; callers cannot supply a substitute
recipient account. Operator selection requires its explicit person and scope.

Persisted notice state belongs to Scheduling's governed owner boundary, with
immutable exact source/purpose references, atomic command/audit/event evidence,
fresh authorization even on replay and database-enforced scope/lifecycle rules.
Historical notice existence cannot restore withdrawn/invalidated content or a
revoked purpose. Regeneration must recheck current disclosure authority. Native
schema, runtime permissions, recovery and exact readiness remain mandatory;
do not fabricate observed fingerprints or bypass deferred PostgreSQL execution.

## Current implementation boundary and consequences

The local implementation includes sender-authorized operator recipient selection,
its dormant capability, closed notice inputs and pure evidence lifecycle rules.
Persisted preparation/review/handoff, acknowledgement and user surfaces remain
#104 work; neither selection nor pure rules deliver the persisted workflow.
This ADR does not create another delivery item or displace #48's decomposition.

PostgreSQL tests and migration/recovery cases remain maintained but unexecuted
under ADR 0100. #102 restores their evidence before integrated acceptance or
activation. A green development PR is not database or departmental acceptance.
The maintainer subsequently authorized a bounded disposable schema-only migration
and metadata check for this new schema while retaining the PostgreSQL test-suite
deferral. It collects exact readiness fingerprints only; it does not certify
workflow behavior, native negative/race cases, populated recovery or #102.

## Requirements affected

OPS-009, SCH-010/012, AUD-001, NFR-001/013 and PRI-001/008. ADRs 0081,
0096, 0097, 0099, 0100 and 0101 otherwise remain accepted.
