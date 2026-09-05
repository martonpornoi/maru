# ADR 0084: Serialize Programme ownership with Department retirement

- Status: Accepted
- Date: 2026-09-02
- Extends: ADRs 0001, 0003, 0005, 0041, 0045, 0081, and 0082
- Partially supersedes: ADR 0083's timeless imported-call owner equality and
  fixed Programme-import batch-version assumptions
- Requirements: HR-011, PRG-001, PRG-002, PRG-006, PRG-009 through PRG-011,
  AUD-001, AUD-003, AUD-005, PRI-001, NFR-002, NFR-003, NFR-008 through
  NFR-010, and NFR-013
- Issue: [#64](https://github.com/martonpornoi/maru/issues/64), child of
  [#48](https://github.com/martonpornoi/maru/issues/48)

## Context

Applications now owns dormant Programme calls, collaborative proposals, and a
preview-first import kernel. Workforce owns the edition Department lifecycle.
Before this decision, a Department could retire while a Draft or Active call,
or unresolved private import staging, still depended on it. The inverse race
also existed: Applications could attach new Programme work after Workforce had
completed its dependency check. A Python preflight alone cannot close either
race or protect direct SQL executed under a registered writer latch.

Normal cleanup is preferable, but old deployments or interrupted migrations
may already contain a call whose owner is retired. Recovery must be possible
without turning a continuity capability into a discovery, content-read, or
general management oracle. Existing applicants must also retain their own
proposal history even when organizer authority through the owner Department
closes.

ADR 0083 correctly made source identity, digests, applied targets, and nested
command lineage permanent. Its requirement that an imported call's current
owner equal its batch owner forever prevents legitimate Department
reorganization. It also fixed every staged batch at version one and discard at
version two, leaving no version for safe ownership reassignment.

## Decision

### Publish one non-disclosing dependency boundary

Applications owns a purpose-limited Department dependency query with only
three outcomes: `clear`, `blocked`, and `unavailable`. Its call and import
probes execute independently even when either one blocks or fails. A known
block always wins; otherwise any unavailable result is unavailable; only two
clear probes produce clear.

The call probe checks an exact organization, edition, and owner Department for
definitions in Draft or Active state. The import probe checks the same exact
scope for a staged batch with at least one staged item. Expiry is deliberately
irrelevant: unresolved expired payload is still owned until explicit disposal.
Applied or discarded evidence does not block retirement.

Workforce invokes this query only after taking its canonical exact-edition
write scope. Public HTML and API adapters continue to expose the existing
generic dependency conflict for a block and the generic service-unavailable
outcome when no known dependency blocks but Applications is unavailable. No
public, audit, readiness, or health result includes dependency categories,
counts, names, identifiers, source identities, emails, payloads, or digests.

### Use one cross-module lock order and database backstop

After a successful idempotent replay and all outer or derived retry advisory
locks, every new Applications Programme ownership writer acquires:

1. the shared structure, provenance, and retired-authority boundaries;
2. Organization, ConventionSeries, and EventEdition row locks;
3. the exact organization/edition advisory mutex;
4. source and destination Departments ordered by UUID;
5. the actor; and
6. Applications aggregates and immutable evidence.

A successful retained-receipt replay returns before acquiring the edition
mutex. Workforce retirement uses the same mutex before checking local and
Applications dependencies. Early statement barriers and row triggers on the
Programme-relevant definition, call, receipt, import-batch, import-item, and
import-receipt relations reuse the Workforce try-lock function. A racing raw
write fails with SQLSTATE `40001` instead of waiting in an inverted row-lock
order. The Workforce Department trigger independently refuses retirement when
live Programme dependencies exist.

### Make ownership changes explicit

Generic call configuration may change content but never `owner_department`.
A dedicated normal command may reassign only a Draft call. It requires exact
current source- and destination-Department
`applications.manage_programme_calls` authority, open private planning,
expected version, retry key, and reason. An Active call must use its ordinary
retirement command before the Department retires.

Each ownership mutation advances the definition aggregate and retains one
receipt action:

- `call_reassigned` for normal Draft reassignment;
- `recovery_call_reassigned` for an orphaned Draft; or
- `recovery_call_retired` for an orphaned Active call.

The receipt has nullable `PROTECT` source and destination Department references.
Both references are populated only for reassignment; recovery retirement keeps
the retired source and no destination. Audit and event payloads stay minimized
and omit Department identifiers.

### Generalize import batch versions without rewriting history

`batch_reassigned` moves an exact batch only when it is staged, unexpired,
wholly staged at item version one, payload-intact, source-unbound, unapplied,
and private planning remains open. Both exact current Departments require
`applications.import_programme`. The command advances batch version `N` to
`N+1` and changes only its owner and update timestamp. It does not change item
versions, payload bytes, source keys, source digests, expiry, or retention.

Any partial application, source binding, expired batch, closed planning, or
retired owner makes reassignment unavailable. The separately authorized
exact-Edition disposal command remains usable after expiry, planning closure,
or owner retirement and advances the current batch version once. Expiry never
performs disposal automatically.

Preview revisions record the positive current batch version. Reassignment
makes an older preview stale, and claim/adoption digests include that batch
version. Historical previews remain immutable. Item transitions independently
remain exactly version one to version two.

An imported call binding still requires call-owner equality with its batch
when the binding is created. Later valid call reassignment does not rewrite the
batch, item, source binding, applied-command evidence, or proposal history.
Instead, ordered reassignment receipts must form one contiguous owner chain
from the immutable batch anchor to the call's current owner. Configuration
commands may appear between transitions, so receipt versions need not be
numerically consecutive.

### Keep recovery exact, dormant, and two-factor

The catalog declares
`applications.recover_programme_department_ownership` with maximum Edition
scope, `delegable=False`, `requires_break_glass=True`, restricted sensitivity,
and reason/audit obligations. No current adoption profile, root role, ordinary
grant path, adapter, route, UI, task, worker, or service actor receives it.

Recovery accepts one opaque caller-supplied call ID and never lists or searches
orphans. It rechecks exact tenant and edition scope plus retired source state.
An orphaned Draft may be moved only to a current Department for which the actor
also has ordinary call-management authority. An orphaned Active call may only
be retired. A target whose owner is still current must use the ordinary path.
Import orphans have no recovery reassignment: explicit disposal is their only
continuity path.

Recovery grants no proposal content, import preview, identity match, source
metadata, or broad Programme read. It creates no account, Participation,
Registration, review, decision, Programme item, host, Shift, publication, or
schedule state. Existing lead, invitee, collaborator, and retained proposal
self/history checks continue to derive from the proposal and call relationship
without requiring the owner Department to remain current. Organizer discovery,
management, and new starts still require current authority.

### Stage the migration and preserve historical truth

The migration order is:

1. Authorization `0023` declares the dormant recovery capability.
2. Applications `0010` adds transition evidence and generalized constraints.
3. Applications `0011` installs authoritative integrity and mutex triggers.
4. Applications `0012` refuses a populated incompatible downgrade.
5. Workforce `0018` installs the 19-reference Department FK catalog and
   retirement dependency backstop.

Forward migration tolerates historical orphaned calls or batches and fabricates
no actor, reason, receipt, or ownership transition. Exact-ID recovery or
disposal fixes them forward. Reverse migration refuses only when data uses the
new transition/version forms or a live dependency would lose protection.
Runtime roles remain SELECT-only and receive no function execution grant.

## Consequences

- Programme and Workforce ownership changes now serialize within an edition,
  closing both race directions and direct-writer bypasses.
- Organizers receive safe remediation paths before retirement without learning
  hidden dependency detail through public errors.
- Immutable imported history remains truthful across later Department changes,
  at the cost of validating a receipt-backed owner chain.
- Exact orphan recovery is intentionally operational and dormant; installation
  does not make Programme Operations selectable or usable in the browser.
- Review, decisions, accepted Programme items, hosts, Scheduling, staffing,
  timetable publication, and on-site surfaces remain later issues.

## Alternatives considered

### Let Workforce import Applications models directly

Rejected because it would couple Workforce to private persistence and make
dependency failure or future schema evolution leak through the structure API.

### Check dependencies without a shared mutex

Rejected because a successful preflight can immediately become stale and raw
registered writers would still race Department retirement.

### Rewrite imported batches and bindings when a call moves

Rejected because those records are source and application history, not a
mutable current-owner projection. Rewriting them would make old evidence say
something that was not true when it was created.

### Treat expiry as disposal

Rejected because time passage has no accountable actor or reason and must not
silently erase private payload or remove a retirement dependency.

### Give platform administrators an implicit recovery root

Rejected because exact orphan repair is high-impact and rare. A dormant,
nondelegable, break-glass capability keeps activation explicit and auditable.

## Requirements affected

- **HR-011 and PRG-011:** Department retirement and Programme ownership writes
  share an exact-edition mutex, database backstop, and non-disclosing result.
- **PRG-001, PRG-002, and PRG-006:** Call ownership remains Applications-owned
  while accepted Programme, host, review, and Scheduling state remain absent.
- **PRG-009:** Existing proposal relationship/self history survives owner
  retirement without granting organizer or discovery authority.
- **PRG-010:** Batch reassignment, positive versions, stale previews, explicit
  disposal, and immutable source/application evidence complete import
  continuity.
- **AUD-001, AUD-003, and AUD-005:** Every success has reasoned immutable
  transition evidence; public and failure evidence remains minimized.
- **PRI-001:** Expiry blocks use but never performs disposal; payload clearing
  remains explicit and attributable.
- **NFR-013:** The change remains a dormant command kernel with no current
  profile or unrelated-module side effect.
