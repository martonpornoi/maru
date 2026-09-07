# Programme host confirmation and purpose-bounded availability

Date: 2026-09-06
Issue: [#79](https://github.com/martonpornoi/maru/issues/79), child of
[#48](https://github.com/martonpornoi/maru/issues/48).
Status: implementation candidate; full certification and protected delivery pending.

## Outcome and contract

[ADR 0087](../architecture/decisions/0087-programme-host-confirmation-and-availability.md)
extends PRG-008 with an explicit host/co-host relationship for accepted and
organizer-created items. Invitations carry deliberately host-visible copy;
only the invited person confirms or declines. Withdrawal, reasoned organizer
removal and fresh reinvitation retain independent history and optimistic versions.
Proposal collaboration is not hosting consent.

Confirmed people can draft, share or withdraw bounded per-item availability.
Private drafts are not disclosed to organizers. Missing periods are not free
time, and deliberately shared empty periods mean unavailable. Ending hosting
clears current windows; retained evidence does not preserve exact old windows.
Two reserved ending revisions and a narrow own-withdrawal path after planning
closes prevent ordinary editing limits from trapping shared availability.

Independent self, roster, history and dependency projections retain their own
field ceilings. Ended self history does not expose later approved item copy.
Current-person and edition-bound checks prevent stale host evidence from being
presented as current scheduling readiness. Host changes invalidate only their
declared readiness dependencies; no concern becomes satisfied automatically.

See the [owner contract](../modules/programme-hosts.md) for commands, projections,
limits, disclosure rules and future Scheduling consumers.

## Safety and installation

Four additive Programme relations and an additive Authorization vocabulary
migration retain scope, closed transitions, immutable history, canonical
edition/person locking and complete deferred command evidence. State, receipt,
minimized audit, event and outbox commit together. Exact schema/function/trigger
fingerprints and SELECT-only runtime inventory include the new boundary.

Empty host installation reverses and reapplies. Retained host history refuses
downgrade before protection removal; retained grants fence vocabulary reversal.
The [recovery runbook](../operations/programme-host-migration-and-recovery.md)
requires fix-forward or a mutually consistent restore, never erasing history
to force a rollback.

Both existing literal adoption profiles remain unchanged and closed to these
commands. No route, UI, API, worker, message delivery, public host directory,
Scheduling placement, Workforce Shift, Registration, Participation, payment or
attendance state is introduced. This is a dormant owner boundary, not a usable
Programme department workspace or production approval.

## Verification at this checkpoint

- Complete database-free unit suite: 2,915 passed in 10.81 seconds.
- Final host PostgreSQL group: 32 passed in 60.92 seconds; an additional
  approved-copy/ended-self isolation case passed in 2.44 seconds.
- Host and accepted-conversion group: 51 passed in 124.27 seconds before the
  final canonical roster-read lock refinement, subsequently covered above.
- Programme authorization, integrity and historical migrations: 33 passed in
  555.44 seconds. Earlier host/query feedback also passed. These groups overlap
  and must not be summed as independent full-suite evidence.
- Cases include tenant/object/field denials, current identity, response/removal
  and availability races, retry collisions, stale versions, late-effect
  rollback, raw-DML refusal, current readiness, empty reversal/reinstall and
  populated downgrade refusal. Accepted conversion continues into explicit
  invitation and person confirmation without fabricating Applications evidence.
- Strict mypy passed 436 source files; Ruff lint and formatting, source
  docstrings, semantic docstring checks and documentation validation passed.
  Django reported no migration changes. Its unconfigured invitation-encryption
  warning is expected in this synthetic environment; no sender is enabled.
- The new integration timing entry retains measured durations from all 33
  distinct host cases, without changing existing file weights or coverage gates.

All database evidence used isolated synthetic PostgreSQL 17 test data. No real
browser journey applies because this child exposes no UI. Full clean-commit
local certification and independent exact-head hosted acceptance are pending;
these focused results do not authorize merge by themselves.

## Continuation

The user authorized sequential completion of all remaining #48 children through
protected merges, single-agent. Finish #79 delivery, reconcile its issue and
the umbrella, synchronize main, then implement Scheduling's days, occurrences,
candidate placement, conflict and Venue contracts. Preserve dormancy until the
later complete Programme-only journey and activation acceptance exist.
