# ADR 0091: Integrate Scheduling with risk-selected acceptance

- Status: Accepted
- Date: 2026-09-08
- Requirements: NFR-001, NFR-002, NFR-003, NFR-008
- Partially supersedes: ADR 0089's whole-file acceptance selection and topology
- Extends: ADR 0090's historical membership and timing-evidence procedure
- Scope: Issue #81 / PR #82 after Issue #83 / PR #84

## Context

PR #82's earlier timing repair retained eight whole-file PostgreSQL jobs under
ADR 0089. Three subsequently timed out. The separately accepted ADR 0090
policy has now merged through PR #84 with green exhaustive hosted acceptance.
Combining the branches must not revive the old acceptance topology or silently
leave Scheduling's committed rollback tests in routine current-schema work.

## Decision

1. ADR 0090 remains the active selection and execution authority: current
   behavior on every code PR, affected history for owner schema changes, and
   exhaustive history for shared harness/global safety changes. Hosted full
   acceptance uses sixteen groups with at most eight simultaneous databases;
   local certification uses eight. Coverage, timeouts and isolation do not change.
2. Retain ADR 0089's exact-evidence calibration code and its tests as diagnostic
   whole-file tooling. Its map, median fallback and legacy targeted-budget
   helper do not control the active group runner. Do not manufacture old-format
   whole-file reports by treating partial group reports as complete files.
3. Classify Scheduling's committed empty reversal and populated two-owner
   fence functions explicitly with Scheduling and Venues ownership. They restore
   the current graph independently; all parameter variants of each function
   remain together. Real graph descendants select them for affected Programme
   prerequisites as well. Current guards, readiness, conflicts, reservations,
   continuity and field/tenant authorization stay on every code PR.
4. Extend the group cost map with complete successful retained JUnit evidence
   for the newly introduced groups. Verify receipt, complete passing reports,
   exact file/function membership and unchanged relevant source between the
   evidence revision and preserved feature head. Sum all parameterized cases,
   including their recorded setup/teardown. Preserve existing estimates and
   label the extension cross-revision cost evidence, not new-head acceptance
   or a hosted-runtime guarantee. New unmeasured groups still get the largest
   known cost. Future group-native refreshes require selection/JUnit equality
   under ADR 0090; the old whole-file baseline has no selection JSON to claim.
5. This integration changes the historical inventory and carries shared
   migration-helper changes. Its resulting exact head therefore requires
   exhaustive local certification and independent green hosted acceptance.
   Neither PR #84's success nor the older feature receipt certifies this merge.

## Consequences and alternatives

The existing Scheduling behavior, migration fences and tests remain intact.
The two timing contracts have explicit roles instead of contradictory active
instructions. Rerunning the old workflow would not incorporate the new branch
content. Dropping the new historical inventory would retain safety but conceal
avoidable routine cost; omitting current guards would weaken safety. Neither
is accepted. This decision adds no Programme surface, profile, release or
production authority. The integration checkpoint records actual provenance,
focused checks and remaining delivery evidence.
