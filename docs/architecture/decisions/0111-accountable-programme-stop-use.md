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

The database-free confirmation contract is now `events.programme_stop_inputs`.
It binds the original actual actor, organization, edition and non-nil retry UUID,
both displayed Events versions, the complete owner-preview fingerprint and a
required NFC-normalized rationale of at most 240 characters. Boolean, coerced,
negative or overflowing versions, partial/noncanonical fingerprints and control
characters are rejected. The digest is purpose/version separated and is not an
authorization token. Transport channels and fresh correlation IDs do not change
the original intent; the eventual receipt retains its original attribution.
This preparation enables no command, route, profile, transition or native writer.

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

### Inspected owner boundaries and unresolved changes

This is an implementation map, not proof that the archived state already meets
the stop contract. The following findings were checked against the local code:

| Owner | Existing boundary | Required stop integration |
| --- | --- | --- |
| Events | `services.transition_edition` invokes full closure/Participation; migration 0004 permits only existing lifecycle edges; migration 0011 requires native release-change audit/witness. | Separate exact-profile command/receipt and native edge; preserve existing transition evidence and invalidation, block generic/bulk bypass and fence used downgrade. |
| Authorization | Programme grant decisions retain exact output assignment IDs. `_lock_scope` rejects archived/cancelled context for both commands and the own-request reader. | Complete owner-controlled assignment accounting and current authorized revocation; an explicit bounded historical detail path without approval controls. Pending intent cannot become a new grant after stop. |
| Applications | Proposal writes share mutable-scope checks; file intake has its own preflight, source/version and retry boundary. | Verify every call/proposal/review/decision/import/file path and in-flight processing under the same stop lock; preserve legitimate sealed history, withdrawal/privacy/disposal purposes. |
| Programme | Private writes consume Events' private-planning flag; public-copy withdrawal and some operational/correction paths deliberately have separate rules. Archive custody separately rechecks source/export permission. | Inventory the exceptions individually; ordinary operation stops, required history/correction and authorized archive custody remain explicit rather than accidentally disabled. |
| Scheduling | `_execute` gates fresh ordinary writes through Events; immutable retry receipts precede that gate. Current outputs use the checked release pointer/dependency journal. | Withdraw before the terminal transition under current withdrawal authority, keep historical receipts non-operational, and verify personal/operator/continuity known-state suppression as well as public output. |
| Workforce | Assignment and Shift commands have lifecycle checks; retained commitments and shared person-owned Availability are distinct. | Test all starter/structure/assignment/demand/claim/confirmation/recovery paths. Stop does not complete or erase accepted work, or prevent a person updating Availability for another adoption. |
| Venues | Shared property facts are Organization-owned. `select_venue_for_edition` resolves/locks the edition but does not itself check its lifecycle. | Explicitly guard edition selection, availability, physical reservation/approval and their native writers for stopped Programme. Preserve shared facts and other editions; archiving alone is insufficient. |
| Effects/Identity/Audit | Existing invitation/worker and immutable event/audit boundaries are separately owned. | Inventory pending work and safe completion/disposal; an account remains usable elsewhere. No excluded-owner event or delivery, invented login authority or audit deletion. |

The archive requires current independent owner rights even after generation.
Blindly revoking every source grant would also remove later authorized history
and archive retrieval; archived context must not manufacture replacement rights.
Before accepting this ADR, settle the explicit disposition of each exact grant
(revoked, already inactive, or deliberately retained for an admitted historical
or shared purpose), including what remains accessible to the original requester.
No retained grant may reopen ordinary Programme operations. A withdrawn pointer
alone also does not prove suppression of independently retained personal work.

### Grant disposition selected for implementation

Stopping operation and revoking read authority are separate decisions. Use the
following closed dispositions in the complete owner-produced preview and receipt;
never silently infer a revocation from the archived lifecycle:

- **Retained historical:** exact edition, Department or room assignments remain
  immutable authority evidence and may still satisfy the existing independently
  authorized historical/archive field ceiling. Their write capabilities cannot
  override the terminal owner guards. No new grant, renewal or pending approval
  may restore operation. Stop does not extend the assignment's validity interval.
- **Retained shared:** exact Organization-scoped Venue assignments and accountable
  representation continue serving their independently adopted purposes. Show that
  they remain; do not revoke them merely because this edition stopped.
- **Already inactive:** retain the exact expired/revoked output and original
  request/decision. Do not rewrite it as a consequence performed by stop.
- **Separately revoked:** a deliberately selected revocation must already have
  succeeded through the current authorized Authorization command, and the stop
  preview must be refreshed to bind that actual outcome. Stop neither grants
  itself revocation authority nor requires destructive blanket revocation.

Pending requests remain original unapproved intent, not fabricated declines or
consent. A stopped-context exact historical detail may display them as unable to
be approved, with no operational controls; the live pending-work inventory must
not invite a new decision. Exact historical reads still require the actual
author/approver and current controller proof. Recipient status alone is not a
history-directory permission. Generic direct grants, delegation and role assignment
must also be fenced for the stopped edition, not only the guided request adapter.

### Literal adopted entry-point review

The isolated candidate's capabilities, adapters, internal events and table ACLs
are the bounded inventory source, not every module installed in Django. The
following concrete command families were enumerated for the remaining owner work:

| Boundary | Ordinary operation to refuse after stop | Retained purpose requiring a separately tested exception |
| --- | --- | --- |
| Events `services` and Programme setup | Edition editing, ordinary transition/reopen and profile replacement; no generic archive shortcut | Exact stop receipt and original setup/configuration history; no new edition state manufactured by a read |
| Authorization `programme_role_commands` and `commands` | Request/approve operational access, direct capability grant, delegation and role assignment into the stopped edition | Exact own-request detail, current-authority revocation and shared Organization scope; immutable role definitions are not deleted |
| Applications `programme_commands`, `programme_call_editor`, `programme_conversion_commands` | Create/configure/activate/succeed calls, selection/answer/profile edits, collaboration acceptance/invitation, seal/reopen/submit, accepted-item conversion | Existing immutable proposal/contributor evidence, explicitly governed withdrawal and orphaned ownership recovery; each exception is still independently admitted |
| Applications `programme_review_commands` | All new review policy, case, score, moderation, decision and acknowledgement actions, including the current acknowledgement exception to private-planning admission | Existing decision/review history at its recipient/reviewer ceiling; stopping is not a new review decision |
| Applications `programme_import_commands` | Staging, reassignment for new operation, previews leading to apply, call commit and proposal claim | Separately authorized staging disposal and retained permanent source lineage |
| Applications `programme_file_commands` | New intake/persistence, including a scan begun before stop whose final write loses the parent-lock race | Existing authorized original-file retrieval and required retention/disposal; a scan result is not permission to persist |
| Programme `commands`, `host_commands`, staffing and placement commands | New/revised accepted or core content, readiness, discussion/delivery/public approval, hosting/invitations/availability, staffing and placement decisions | Current-authority public-copy withdrawal, immutable source/host/work history and requester-bound archive custody; no fake host removal or work completion |
| Scheduling day/occurrence/candidate/placement/evaluation/reservation/release commands | New or revised planning, warning acknowledgements, approvals and publication | Independently authorized release withdrawal before terminal stop; exact historical receipts/artifacts do not reinstate a current pointer |
| Scheduling `change_notice_commands` and continuity/current-output queries | Preparation, review, handoff and acknowledgement; public/personal/operator/online-continuity operational output | Historical exact-recipient evidence and bounded already-downloaded bytes; known stopped state suppresses operational use |
| Workforce structure/assignment/starter/shift commands and `services` | New structure, positions/opportunities, onboarding, assignment activation, demands, claims, confirmation, reopening and ordinary completion | Immutable proposal/assignment/commitment history and explicit governed correction; person-owned Availability and another edition remain usable |
| Venues `services` and Scheduling reservation adapter | Edition venue/space selection, availability, booking/rescheduling/approval/publication and new occupancy/binding | Organization catalog and other editions; separately governed withdrawal/cancellation of retained physical obligations must not be mistaken for convention cancellation |
| Effects, Identity and Audit | No queued operational request or replay may bypass current owner admission | Retained internal transactional evidence, account/restriction security, required expiry/disposal and independently admitted shared invitation workers |

The candidate declares only `internal` effect routes. Stop must not create a
Communications delivery, disable a global Identity worker or cancel a person's
platform account. Its pending-work preview must nevertheless account for archive
tasks, staged imports/files, outstanding collaborator/host intent and existing
internal effect evidence. Existing archives retain original source identity;
source movement caused by stop can make an older package unavailable. Generate a
fresh authorized historical package or finish retrieval before stop rather than
weakening freshness checks.

The next implementation step is to map these families to exact native root and
derived-table guards, purpose exceptions and actual race/denial cases. This table
does not claim that every family is already fenced. Native guards must consider
both old and new scope on updates, so moving a row cannot escape a stopped edition.

The map remains incomplete until the exact adopted command/read/effect inventory,
field ceilings, native exceptions and corresponding negative cases are enumerated.
No schema or stop command is authorized by treating this proposed map as already
accepted or tested.

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
