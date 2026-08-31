# Profile-aware Position-assignment evidence contracts

- Date: 2026-08-30
- Issue: [#41](https://github.com/martonpornoi/maru/issues/41)
- Parent evaluation: [#29](https://github.com/martonpornoi/maru/issues/29)
- Requirements: HR-013, NFR-002, NFR-003, NFR-013
- Decisions: ADR 0076 as partially superseded by ADR 0080; no new ADR

## Outcome

Current Position-assignment documentation now matches the already-implemented
immutable adoption-profile boundary. Proposal creates no Participation,
RoleAssignment, capability, or schedule commitment in either profile. Approval
and ending share the governed Assignment and authorization lifecycle while
their Participation evidence differs deliberately.

| Edition profile | Approval evidence | Ending evidence | Required pointer |
| --- | --- | --- | --- |
| `full_convention@1` | Activate the scoped RoleAssignment and configured Participation capacities. | Revoke the RoleAssignment and complete only capacities no other active assignment needs. | `participation_capacity_id` is non-null. |
| `workforce_only@1` | Activate the scoped RoleAssignment; create no `Participation` or `ParticipationCapacity`. | Revoke the RoleAssignment; create or touch no Participation evidence. | `participation_capacity_id` remains null. |

The opposite pointer shape is an integrity conflict in either profile. A null
full-convention pointer must not be normalized by discarding other evidence; a
non-null Workforce-only pointer must not be normalized by treating attendee
Participation as adopted.

## Decision relationship

ADR 0076 remains the historical record for relationship-bounded proposals,
independent stepped-up decisions, immutable intervals, headcount, onboarding,
scoped RoleAssignment activation and revocation, retained ending, direct
manager evidence, audit, events, receipts, and recovery. Its original
unconditional Participation activation and completion is now marked partially
superseded.

ADR 0080 owns the later profile boundary. Its metadata and a dated relationship
clarification now state that only ADR 0076's unconditional Participation side
effect changes. No accepted ADR 0076 decision prose or historical checkpoint
was rewritten.

## Corrected current guidance

- HR-013 and the roadmap state both profile outcomes and mismatch handling.
- The Assignment page contract states profile-aware purpose, approval, ending,
  database evidence, downgrade, recovery, and acceptance boundaries.
- The Workforce module, domain map, experience summary, and key workflow no
  longer imply that every assignment joins or creates Participation.
- The Workforce-only runbook now rehearses proposal, independent approval, and
  retained ending while checking RoleAssignment state, the null pointer, and
  zero exact-person, exact-edition Participation and capacity rows.
- Both ADR catalogs expose ADR 0076 as partially superseded and preserve its
  still-accepted boundaries.

## Executable evidence

The existing full-convention lifecycle test proves approval creates an active
Participation capacity and ending completes it. It now also attempts to clear
the ended assignment's pointer directly and proves the PostgreSQL stopped-
writer guard rejects that invalid governed ending.

The existing Workforce-only lifecycle test proves there is no Participation
before proposal, approval activates a RoleAssignment while the pointer stays
null, ending retains the null pointer, and Participation remains absent. The
focused cross-document policy test prevents the owning current contracts and
ADR relationship from drifting back to unconditional wording.

## Verification

- all 18 documentation-policy unit tests pass;
- both focused PostgreSQL assignment lifecycle tests pass through proposal,
  approval, and ending, including the new raw-database conflict; and
- the protected pull-request gate remains authoritative for the final exact
  delivered commit.

## Data, migration, and recovery notes

No runtime implementation, model, schema, migration, API, permission, or
browser behavior changed. Existing records are not backfilled or rewritten.
Migration `0014_workforce_only_assignment_evidence`, model validation, and the
PostgreSQL guard already enforce the documented split.

On mismatch, stop assignment writes in the exact scope and preserve edition,
assignment, RoleAssignment, Participation, capacity, receipt, audit, event, and
outbox evidence. Fix forward or restore the complete mutually consistent
database. Do not manufacture Participation for Workforce-only, clear required
full-convention evidence, mutate the immutable edition profile, or reverse the
guard independently.

## Known limits and next action

This correction is not profile expansion, lifecycle redesign, a continuity
package, production approval, or the missing operator tutorial. Issue
[#42](https://github.com/martonpornoi/maru/issues/42) remains the next bounded
release-candidate finding.
