# ADR 0093: Bind Programme staffing explicitly and preserve accepted work

- Status: Accepted
- Date: 2026-09-09
- Extends: ADRs 0078, 0081, 0087, 0088 and 0092
- Requirements: HR-009, HR-014, HR-015, SCH-001, SCH-003, SCH-005, SCH-007,
  SCH-009, SCH-010, SCH-012, AUD-001 and NFR-013
- Issue: [#88](https://github.com/martonpornoi/maru/issues/88), child of #48

## Context

Private timetable alternatives exist, but they do not request Workforce work.
A volunteer accepts one explicit work expectation, not whatever time a planner
later selects. Staffing needs must have a durable owner without creating a
second claim/confirmation lifecycle or exposing personnel data to every planner.

## Decision

Programme owns each occurrence's versioned staffing requirement and retained
revisions. A requirement identifies an exact Position, explicit work briefing,
reporting place, work interval, headcount, planned break and minimum rest. It
is separate from general Programme readiness attestations and from a volunteer
commitment. The work interval may include preparation or teardown and need not
equal the audience-facing occurrence interval.

An explicit binding joins one requirement revision, one Scheduling occurrence
and candidate/placement revision, and one Workforce demand. Candidate copies
or movements never create demand, select a staffing source or rebind it. A
source mismatch makes coverage stale; it never edits an accepted expectation.
Stable requirement and occurrence identities survive source revisions.

Workforce retains its existing demand and commitment commands. Draft
reconciliation requires no retained commitments, both owners' current authority,
an exact impact preview, optimistic versions, reason and retry identity. Open,
locked, cancelled or completed demand cannot be rewritten by the adapter.
Recovery explicitly preserves the predecessor, cancels through Workforce when
appropriate and creates a separate draft successor. It never transfers claims,
reconfirms a person, accepts underfill or relocks coverage automatically.

Planning consumes a complete, bounded, independently authorized and audited
Workforce projection containing demand state/version, aggregate counts and
current suitability consequences. It does not receive names, private reasons,
contact data or complete availability. Unavailable or withheld sources are not
empty demand; stale evidence cannot count as current coverage. Claimed places
are not confirmed coverage. Locked underfill remains explicitly underfilled,
even when the Workforce owner has accepted its reason.

Binding lineage and its retained rationale are separate read purposes. Current
binding views omit actor and rationale columns; history requires both Programme
`staffing_history` and independent Workforce work-field authority, uses a fixed
inclusive revision ceiling and bounded consecutive pages, and audits before
releasing restricted decisions. Opaque owner references grant no directory or
private-candidate access. Current coverage compares exact source and work-term
fingerprints, not demand version equality: opening or locking unchanged work is
not a source change. Private rationale never enters the coverage projection.

Cross-owner writes acquire the canonical Workforce edition scope first:
retired-authority boundary, Organization, series, edition, structure mutex,
then affected owner aggregates in deterministic order. Fresh source facts and
authority are checked under this scope; all state, receipts, audits, events and
outbox work commit or roll back together. Each module owns its tables and
guards; adapters use public commands and minimized typed queries.

The personal reader uses only the caller's own retained Shift relationship.
Private Programme alternatives are not disclosed through that relationship.
Combined published host/volunteer timetables remain the later SCH-012 atomic-
release child's responsibility. No Participation or unrelated module is used.

This decision does not activate a profile or route. Additive migrations must
preserve dormant runtime containment, raw-DML integrity and populated recovery
fences. #87 and the complete setup-to-on-site acceptance remain activation gates.

## Consequences

Planners can distinguish needed, requested, claimed, confirmed, stale and
locked-but-underfilled work. Movement may require deliberate recovery instead
of automatic rescheduling. More exact-source evidence is retained, but original
volunteer decisions remain truthful and independently inspectable.

## Alternatives considered

- Infer staffing from a readiness note: rejected because it lacks typed demand,
  exact source versions and actionable coverage.
- Reuse the organizer Shift overview directly: rejected because it contains
  personnel labels and rationale beyond the planning purpose.
- Follow whichever candidate was edited last: rejected because alternatives
  have no implicit publication or staffing authority.
- Rewrite accepted shifts or copy claims to a successor: rejected because
  neither a planner nor a prior claim accepts new work on the person's behalf.
