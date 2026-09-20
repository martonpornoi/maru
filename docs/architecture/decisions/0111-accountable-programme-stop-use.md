# ADR 0111: Stop Programme through a profile-specific archived boundary

- Status: Proposed; owner integration and native acceptance pending
- Date: 2026-09-20
- Extends: ADRs 0081, 0106, 0108 and 0109
- Requirements: EVT-007, ARC-003, ARC-005, AUD-001, INT-007 and NFR-013
- Issue: [#190](https://github.com/martonpornoi/maru/issues/190), within #108/#48/P11

## Context

The accepted profile needs an explicit predictable exit, not cancellation of the
convention, a changed adoption profile, stopped shared server or deleted records.
Events owns edition lifecycle. Its existing terminal archived state already
represents read-only retained evidence, but the generic archive path invokes
full-convention closure gates and Participation snapshots. It cannot serve as an
unmodified Programme-only stop command.

Operational roles have separately approved provenance and differing scopes.
Edition-scoped work must stop without implying that Organization-scoped Venue
authority or constitutional representation disappeared. Immutable assignments,
confirmed work and prior disclosures also cannot be rewritten to claim completion.

## Proposed decision

### Reuse the terminal state, not the full-convention transition workflow

Events will own a dedicated Programme stop preview and command for the exact
`programme_operations@1` pair. It will move this adoption into `archived` through
its own auditable receipt-backed boundary. The UI calls this **Stop Programme**,
not **Cancel convention** or **Complete all work**. The profile remains immutable;
Full Convention and Workforce-only transition rules and closure paths stay intact.

The dedicated command may stop an otherwise eligible active Programme adoption
before event completion. It must not manufacture intermediate live/closing states,
readiness approvals, Participation snapshots, completed Shifts or attendance.
The generic transition endpoint must not become an alternate way around the stop
preview, exact source/version binding or cleanup/accounting contract.

One immutable Events-owned receipt will bind actual controller, organization,
edition, prior lifecycle/version, original retry identity, canonical intent digest,
accountable reason, current impact identity, terminal transition and Audit evidence.
It will retain minimized references to exact authority/output outcomes, not private
proposal/review contents. Exact authorized replay returns the original result;
changed intent or a changed preview requires a fresh deliberate confirmation.
No successful result exists before the complete transaction commits.

### Accountable preview and actual owner authority

Require a current ordinary accountable controller and existing exact
`events.transition` authority, not platform-administrator fallback. Minimized
owner-controlled status queries will report affected work, active outputs,
pending processing/files/exports, retained commitments and exact operational
assignments. Stop-purpose visibility is explicit; it does not grant bulk private
source access or reuse export permission as a general controller role.

Every owner mutation retains its existing public command and actual authority.
If withdrawing an active release or revoking a particular assignment requires
additional current permission, preview must show that prerequisite and refusal
must leave the adoption unchanged. Do not impersonate another approver, borrow
old consent, self-grant missing rights, or invent a full-convention approval.

For ADR 0106 outputs, distinguish exact edition/Department/resource assignments
from deliberately shared Organization-scoped Venue assignments. Retain complete
accounting of which authorized assignments were revoked, already inactive or
deliberately retained as shared. Never bulk-revoke by role name or destroy roots,
immutable role definitions, other editions' rights or independently adopted work.
Volunteer assignment/commitment history is not automatic completion or removal.

### Close ordinary operation while retaining a bounded history purpose

Canonical shared parents, edition and affected person/source locks must serialize
stop against in-flight commands and independently approved grants. Existing owner
guards and additional narrowly required checks must refuse ordinary writes after
stop, including old retry keys and queued work. Public, personal and operator
current-output boundaries must stop presenting the edition as operational.
Withdrawal of one release is part of output handling, not the stop-use operation.

Authorized historical reads, retention/privacy operations, restricted exit archive
and explicitly governed correction/recovery remain available at their existing
field ceilings. Forms and navigation must identify historical/read-only context;
they must not merely expose ordinary controls that fail later. The native stop
receipt/transition boundary must prevent direct lifecycle changes from bypassing
the complete operation, and retained stop evidence must fence unsafe downgrade.

Existing downloaded files and disconnected read-only continuity packs cannot be
remotely erased. Explain their bounded lifetime and historical nature. Online
verification and a known stop state must suppress operational use; old local
bytes, a signature, cached HTML or an old session never restore server authority.
Source-bound archive downloads continue checking current rights and source state.
Pending/history exports and derived artifact expiry/disposal are accounted for
explicitly, without pretending an export is a database backup.

### Recovery and non-goals

Stop is terminal in the ordinary UI; no retry, profile toggle or generic lifecycle
command reopens it. Retain immutable history and supported correction paths.
Fix forward or restore one mutually consistent supported database/artifact state
through #97, retaining the corresponding stop evidence and rechecking access.
This decision grants no production activation, destructive uninstall, broad
retention override, server shutdown or external message/provider action.

## Alternatives and acceptance

- A second independent active/stopped flag duplicates Events' terminal lifecycle
  and risks contradictory admission. Prefer the existing archived state if the
  complete owner/entry-point inventory proves that it can represent this outcome.
- Calling generic full-convention archive would introduce unrelated dependencies
  and effects. Changing global transition rules would widen current profiles.
- Application-only hidden navigation, one withdrawn timetable or role-name-based
  revocation does not establish a complete stop boundary.

Before acceptance, map every adopted command/read/output/effect and required
history/correction exception, then run real scope/field denial, stale/retry/race,
rollback, native recovery and excluded-effects cases. Verify the stop preview and
confirmation UI, original work/evidence preservation, shared-grant accounting,
P11 composition and #97 restore. If the existing terminal state cannot support
these semantics without changing other profiles, revise this proposed decision
before implementation; do not silently weaken the outcome. #92 human and #109
integrated evidence remain separate requirements before closing #48.
