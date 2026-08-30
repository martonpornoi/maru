# Assignment authority-interval recovery

- Date: 2026-08-30
- Issue: [#39](https://github.com/martonpornoi/maru/issues/39)
- Parent evaluation: [#29](https://github.com/martonpornoi/maru/issues/29)
- Requirements: IDN-005, HR-004, HR-013, UX-029, NFR-001, NFR-004, NFR-009
- Decisions: ADRs 0044, 0076, and 0080; no new ADR

## Outcome

Position assignment intent can no longer be created or approved beyond the
complete interval of the exact current controlling-authority sources that make
it possible. A new proposal validates the proposer before persistence;
approval validates the original proposer and the current independent approver
again inside the activation transaction.

The recovery contract is deliberately narrow. A proposal is immutable. When
current authority no longer covers its interval, an organizer reloads, rejects
it, and creates a new proposal within current authority. Maru does not edit,
backfill, silently rebind, or replace the retained proposal.

## Decisions

- After required current route authorization, exact idempotent replay resolution
  precedes the new proposal-time horizon assertion. An identical successful
  retry after source-interval replacement returns its original receipt while
  those route capabilities remain current; their loss remains a denial.
- One exact current control source must cover the complete requested interval.
  Equal start and expiry boundaries are valid; a bounded source cannot cover an
  unbounded assignment.
- Proposal-time start or ending failures are field-local validation and happen
  before proposal persistence or headcount reservation.
- Approval-time failure is a dedicated conflict with stable machine-readable
  recovery and an action-local browser message.
- No response identifies the failing controller or exposes an issuance, grant,
  source timestamp, or raw provenance.
- Existing IDN-005 and HR-013 behavior plus ADRs 0044, 0076, and 0080 are
  sufficient; no new architecture decision is required.

## Changed areas

- Authorization classifies uncovered starts separately from uncovered endings
  and exposes a locked, non-disclosing persistent-horizon assertion to
  compatible domain writers.
- Workforce validates proposer authority after exact replay lookup, maps the
  approval-time dual-control failure to its own conflict, and keeps HTML and
  API recovery aligned.
- Assignment requirements, page contract, module documentation, and changelog
  now describe the interval and recovery boundary.

## Atomicity and disclosure

Proposal-time rejection creates no proposal, reservation, RoleAssignment,
Participation, receipt, audit, domain event, outbox message, or access. An
approval-time rejection leaves the immutable proposal at the same version and
continues its truthful headcount reservation. The enclosing transaction retains
no RoleAssignment, access, Participation, success receipt, success audit,
success domain event, outbox message, or other successful mutation effect.

Revoked, expired, unavailable, and insufficient authority remain fail-closed
without disclosing which controller or source caused the result. The browser
places recovery beside the attempted approval; the API returns the same bounded
meaning as a typed `409` without names or provenance.

## Verification scope

The bounded acceptance suite covers start and expiry failures, exact boundary
success, bounded-source versus unbounded-assignment failure, revoked and
expired authority, unchanged proposal/version/reservation after failure,
idempotent replay ordering, fresh step-up ordering, daylight-saving input
validation, strict API status and code, browser action-local recovery, and the
absence of authority, Participation, and successful mutation evidence. The
protected pull-request gate remains authoritative for the exact delivered
commit.

The complete focused PostgreSQL files passed 38 Authorization command tests
and 20 Workforce assignment command tests. The latter includes the assignment
form's Europe/Budapest daylight-saving gap and fold boundaries. A real
synthetic stepped-up approver journey then exercised the typed conflict and
retained rejection at 1,280 by 900 and 390 by 844 CSS pixels. The alert received
focus; one H1 and one `main`, unique IDs, and no horizontal overflow were
retained; approval was disabled while reload and fresh rejection remained
available; rejection preserved version 2 and both history entries; and the
browser recorded no console warning or error. This bounded rehearsal is not
the complete UX-029 matrix or two-human owner acceptance.

## Data, migration, and deployment notes

No model, schema, migration, runtime role, or deployment boundary changed.
Existing proposals are neither edited nor backfilled. If one cannot pass the
approval-time interval recheck, its supported recovery is rejection followed
by a new proposal inside current authority. Rolling back this repository change
removes the additional command and adapter validation only; it does not rewrite
retained data.

## Known risks and incomplete work

This change does not add assignment editing, replacement, bulk operations, or
production approval. Complete rendered accessibility, provider recovery,
deployment, and two-human owner acceptance remain broader release gates.

## Smallest next action

Resolve the next bounded finding from issue #29 as its own focused pull request
after this exact change passes the protected gate.
