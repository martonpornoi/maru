# ADR 0087: Keep Programme hosting explicit, person-confirmed and purpose-bounded

- Status: Accepted
- Date: 2026-09-06
- Extends: ADRs 0081 and 0086
- Requirements: PRG-005, PRG-006, PRG-008, IDN-014, SCH-001, SCH-002,
  SCH-009, AUD-001, AUD-003, AUD-005, NFR-001 through NFR-003,
  NFR-008 through NFR-010, and NFR-013
- Issue: [#79](https://github.com/martonpornoi/maru/issues/79), child of
  [#48](https://github.com/martonpornoi/maru/issues/48)

## Context

An accepted proposal becomes independent Programme work. Its contributors may
not be its eventual hosts, and an organizer-created ceremony may have no
proposal at all. Scheduling needs proof of who agreed to deliver each item and
when that person deliberately made themselves available. Neither proposal
authorship nor a Workforce relationship supplies that proof.

## Decision

### Retain one explicit item/person relationship

Programme owns one retained relationship per exact item and existing active,
verified person. An independently authorized host manager issues a reasoned
invitation as `host` or `co_host`. Both accepted and organizer-created active
items support this command; no Applications evidence is fabricated or copied.
The organizer explicitly supplies the bounded invitation title and host
briefing. They are host-visible operational fields, not an implicit copy of
private working or review text. The first version admits at most 100 retained
relationships per item and 1,000 ordinary revisions per relationship. Two
additional revisions are reserved for withdrawing availability and then ending
hosting; exhausting editing history must not trap a person in shared availability.
An organizer removal may use this ending reserve but still requires open planning.

Only the invited person may confirm or decline the current invitation. A
confirmed person may withdraw without disclosing a personal explanation. An
authorized organizer may remove an invited or confirmed relationship with a
retained reason. Declined, withdrawn and removed states retain history but
grant no current hosting authority. Reinvitation keeps the same relationship
identity, advances its version, records new explicit invitation fields, and
requires a fresh person-owned response. No role change silently preserves a
previous confirmation. Organizers cannot confirm on someone's behalf.

### Scope availability to the actual hosting purpose

Each confirmed relationship owns its own availability. The person may save a
private draft or deliberately share a complete bounded set of available or
preferred intervals for that item. This permits a host to express different
delivery constraints for different items without opening a general personal
calendar. A later surface may offer explicit person-owned copying or a batch
command; it must never silently reuse Workforce or another item's periods.

Unknown, private draft, shared and withdrawn are distinct. A shared empty set
means explicitly unavailable; unknown or withheld periods do not mean free.
Periods are offset-aware, whole-minute, positive half-open intervals inside
the edition's local-date envelope. They are normalized to UTC, ordered,
non-overlapping and capped at 128 per relationship. Adjacent intervals are
allowed. Browser adapters must separately resolve edition-local minutes and
reject nonexistent or ambiguous input before calling this same command.

Withdrawal, declining, removal or reinvitation clears current exact periods.
Immutable command/history evidence retains only state, version, period count
and normalized-intent digest, not a historical copy of private time windows.
An organizer sees only deliberately shared current periods for a currently
confirmed, active-person relationship; a private draft and unknown state are
both reported as not shared. The subject can clear their own current periods
even after planning closes; that privacy action does not reopen planning.

### Keep authority and disclosure independent

New exact-edition host-management and host-read capabilities are independent
of item editing, review, readiness attestation and public-copy approval.
Relationship-derived self capabilities are non-persistable and require both
the exact person and the exact item relationship. Every path checks the exact
profile before private lookup; a test policy substitute retains the existing
two-factor isolated-database guard.

The subject's invitation/history projection contains only their own role,
response, deliberately host-visible invitation fields, availability and
approved item copy. It contains no other host, organizer rationale, contact,
proposal answers, review, discussion, technical/accessibility layer or private
working information. Current confirmed hosts gain only those host-purpose
fields, not general Programme read or edit authority. Retained self history
survives relationship ending, but does not expose later item changes.

Organizer roster and availability reads require their own field ceilings and
audited, version-fenced, bounded complete snapshots. Authorization and current
identity are rechecked before disclosure. Neither a caller-supplied UUID nor
an invitation expands account discovery into directory search.

### Preserve one command and dependency history

Host changes join the Programme item transaction, advancing its optimistic
version exactly once. Relationship versions and exact invitation sequence
prevent stale person responses. Commands share Programme's actor/edition
retry namespace: same normalized intent returns only retained result IDs and
versions after current identity/adoption proof; collisions fail closed.
Routine person actions use code-owned action reasons, not requested private
explanations. Organizer rationale remains separately restricted.

Acquire the edition ownership locks before person and Programme object locks,
and lock multiple persons in deterministic identifier order. Persist current
state, immutable revisions, the Programme receipt, minimized audit, event and
outbox together. Failure changes none of the success state. Database guards
independently enforce scope, person ownership, allowed transitions, interval
shape, complete evidence and contiguous versions.

Roster changes invalidate host-confirmation and schedule-availability
readiness dependencies; availability changes invalidate only the latter.
No change rewrites approved public copy or fabricates satisfied readiness.
The Programme-owned dependency query returns exact source versions and
explicit confirmation/availability consequences for later Scheduling. It
never returns a private draft, contact, reason, review field or another
module's relationship. No confirmed host is not proof that hosting is
unnecessary: readiness must explicitly declare a concern not applicable.

### Retain dormancy until the full workflow exists

The new owner records, capabilities and event actions remain excluded from
both existing literal adoption manifests. Runtime tables stay SELECT-only;
there is no new URL, API, UI, worker, external invitation delivery or active
Programme profile in this child. Later surfaces and pinned purpose-delivery
adapters consume these commands rather than introducing alternate writers.

Additive migrations preserve existing items, conversion receipts and readiness.
Unused host tables can reverse exactly. Durable host history fences downgrade
before any protection is removed. Recovery fixes forward or restores Programme,
Identity, Events, Organizations, Authorization, Audit, Effects and migration
history from one mutually consistent point. It never creates attendees,
Registrations, payments, memberships, volunteers, Shifts or schedule releases.

## Consequences and alternatives

An organizer invitation is not consent; the person's response is independent
evidence. Per-item availability avoids unrelated calendar disclosure but may
need deliberate copy/batch affordances in the later host workspace. Reusing
proposal collaborators, auto-confirming hosts, importing Workforce availability,
or treating missing periods as free would cross purpose boundaries. Automatic
public host profiles and direct model writers are not accepted shortcuts.

## Verification boundary

Acceptance includes cross-tenant and field denials, service-account rejection,
stale invitations, retry namespace collisions, both orders of response/removal
and availability races, partial-failure rollback, exact interval withdrawal,
raw-DML guards, current-person dependency changes, schema/readiness/runtime-role
proof and empty/populated recovery. Full local certification and independent
exact-head protected acceptance remain required. This child alone does not
establish a usable Programme Operations workflow or production readiness.
