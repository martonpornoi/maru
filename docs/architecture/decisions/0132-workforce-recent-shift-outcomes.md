# ADR 0132: Receipt-backed recent Shift outcomes on Home

- Status: Accepted contract; implementation pending
- Date: 2026-11-01
- Extends: ADRs 0078, 0126 and 0128 without changing their existing projections
- Requirements: UX-033, UX-029, UX-031, AUD-003–005, NFR-001–003 and NFR-013
- Parent: #35; bounded contract issue #233

## Context

Home already offers bounded Workforce next steps. Django administration log
entries are deliberately absent: they miss service/API commands and do not
establish current disclosure. Existing Shift commands retain immutable demand
receipts for locking, completion and cancellation. An organizer should be able
to find a few recent retained outcomes without interpreting a click log.

The maintainer authorized successive bounded work, including documented contracts
with separately retained manual validation. This increment accepts the next
contract; it adds no running panel, permission, data collection or profile effect.

## Decision

Workforce owns a new read-only recent-outcome projection for exact
`workforce_only@1` scope. The shell calls a documented public owner query and
never reads Workforce, Django administration-log or Audit tables itself. Other
profiles and unadopted modules contribute nothing. Existing primary/attention
guidance keeps its four-area limit and ordering.

Admit the complete existing organizer Shift-read capability and field ceiling
before reading candidate metadata. Management, staff/platform status or selected
context alone grant nothing. Bind every candidate to its current exact-edition
parent, repeat current authorization and owner lifecycle, and reauthorize the
ordinary detail destination independently. Do not add a broader history grant.

Show at most five distinct Shifts whose latest matching demand receipt records
`locked`, `completed` or `cancelled` in the preceding seven elapsed UTC days.
The receipt's resulting version and status must match the current demand.
An old lock followed by reopen/update is excluded. Receipt time is when Maru
recorded the governed command, not evidence of attendance, actual work or handover.
The page contract fixes complete-cohort bounds, ordering, integrity and time rules.

Release only the currently readable Shift label, closed outcome wording, recorded
time and exact existing detail link. Select no actor/holder identity, rationale,
contact, document, Availability interval, retry key or security-audit payload.
The current Shift label is an explicit operational disclosure under its existing
field ceiling, not permission to display other source text. Escape it normally;
do not copy historical labels into a new retained store.

Use short read-only coherent snapshots and complete bounded source signatures.
Repeat current policy/profile/lifecycle before and after required minimized
read audit and after all home providers finish. Check the deadline and next
lookback expiry after the final source probe. Retry the whole component once
on source movement; persistent movement, corruption, overflow, audit/dependency
failure or clock rollback releases no rows and only generic unavailability.
Other admitted guidance and direct tools remain usable.

The proposed `workforce.shift_outcomes.read` operation must be registered with
the existing Workforce operational-read purpose and `workforce-personal` retention
class before implementation releases facts. Retain only existing principal,
scope, policy, route/method and correlation metadata. No outcome contents,
analytics purpose, new duration or per-person productivity record is added.
Mandatory audit failure withholds the entire component. This contract does not
itself register an operation or claim its runtime availability.

## Consequences and acceptance

The [page contract](../../product/page-contracts/workforce-recent-outcomes.md)
defines the role/disclosure matrix, five-item and 128-candidate bounds,
seven-day horizon, current-source fencing, empty/unavailable behavior and recovery.
The bound can make this optional panel unavailable in a busy edition; existing
Shift workflows remain the fallback. It is not a complete history/export service.

Implementation must supply unit, native PostgreSQL, restricted-runtime,
rendered/browser, fictional demo and measured resource evidence. Human,
specialist accessibility, owner, recovery, operational and production acceptance
remain separate. Contract delivery closes only #233; #35 stays open.

No migration, runtime ACL, account/grant, domain write, task/activity database,
notification, polling, activity tracking, profile expansion or deployment is
included. Future source rollback removes the optional projection/presentation;
domain receipts and their existing retention remain unchanged.
