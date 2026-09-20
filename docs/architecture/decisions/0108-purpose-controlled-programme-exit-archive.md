# ADR 0108: Authorize Programme exit separately from ordinary viewing

- Status: Accepted; implementation pending
- Date: 2026-09-19
- Extends: ADR 0081; preserves ADRs 0100, 0104, 0105, 0106 and 0107
- Requirements: EVT-007, INT-007, QRY-006 through QRY-008, AUD-001,
  AUD-003, PRI-001, PRI-003, NFR-003 and NFR-013
- Issue: #189 within #108/#48

## Context

The accepted Programme exit includes configuration, proposals/files, decisions,
Programme history, schedules/releases and work links through their owning
boundaries. Its first packaging and history collectors are implemented, but
neither supplies a usable complete archive. Ordinary history DTOs intentionally
omit some immutable source identifiers and lineage. An archive needs those links
to make its portable records understandable, without changing ordinary viewing
contracts or treating an opaque identifier as source-read authority.

This is restricted bulk output: a valid proposal can already retain 64 MiB of
supporting documents. The provisional 32 MiB memory-only package is not a
convention-wide capacity contract. Asynchronous execution, current authorization,
expiry and private artifact custody are required by QRY-006/007, not optional
enhancements. No generic export-job service was identified; Registration reports
have a different audience and depend on excluded attendee records.

## Decision

### One additional explicit purpose; independent source authority remains

Reserve `programme.export_archive` as an exact-edition, delegable C3 capability.
Its closed fields are `archive_requests` (the actual requester's bounded task
metadata) and `source_lineage` (explicit owner-approved archive provenance).
It is additional authority for this bulk purpose, never a substitute for any
owner's existing object, field, relationship, anonymity, retention or file checks.
Ordinary Programme summary/history DTOs and their field ceilings remain unchanged.

A minimal immutable `exit-archive@1` operational recipe supplies only this extra
capability at edition scope. Existing role recipes, representation roots and
retained approvals are unchanged. The current two-person operational approval
workflow governs issuance; selecting a recipe or being a director is not a grant.
The capability and `programme.exit-archive@1` adapter remain absent from every
current adoption profile until the complete Programme promotion gates pass.

Archive-only lineage may expose explicitly declared stable record IDs, natural
keys, exact predecessor/source relationships and immutable versions only under
this extra purpose **and** the corresponding owner's historical read authority.
A source link is not permission to follow it into another owner. Each owner must
declare the exact projection/schema before implementing it; no generic model or
dataclass dump, new DTO field discovery, invitation secret or security key is
permitted. Summary-only access does not acquire restricted lineage access.

### One understandable task, scoped to the selected Programme operation

The task names one exact edition, requester, supported archive contract and
explicit purpose. Preview describes the requested owner/field scope, restricted
classification, declared limits, private-file treatment and actual prerequisites.
It must not disclose unauthorized Department, proposal, person or history names
to explain a missing permission. Department/resource closure is resolved through
owning queries; an edition-wide label cannot hide a partial Department export.

The requester deliberately starts generation. Only that current authenticated
requester, with the still-required export and source rights, can inspect private
task metadata or download its output. No general job directory, shared bearer URL,
email delivery or administrator-impersonated download is introduced. Other-person
handoff would require a later explicit contract rather than granting access from
a guessed task ID. A prior success, role name, digest or stored permission snapshot
is never current authority.

Large exports run as purpose-specific background work. Execution and download
repeat current permission, owner-source and retention checks. Retain bounded
progress and safe failure codes, explicit cancellation/retry semantics, private
artifact expiry and minimized audited outcomes. Expiry limits access to derived
artifacts; it must not erase canonical source evidence or override holds. Choose
and verify the exact persistence/custody, resource-budget and disposal contract
before its implementation; this ADR does not provision storage or set a legal
source-retention period. No generic reporting platform or external vendor is
required by this decision.

### Complete within a declared, authorized scope

The versioned owner schemas declare required records, stable identifiers, source
versions, linkage, permitted private text and file provenance, classification,
and any purpose-authorized omitted or withheld fields. Distinguish a declared
field omission from a missing owner, denied required source, truncated page,
expired file, failed audit or changed selection. Required-source failures produce
no downloadable success artifact; a partial package cannot be labelled complete.

Owner collection must establish a coherent source boundary, including independent
placement/public-copy/authorization generations that do not advance a Programme
item cursor. Paging by itself is not a snapshot. Lock ordering and source rechecks
must be proven for the actual composed owner set and supported volume. A single
item's person locks cannot be assumed to cover every related person in a whole
edition. Later source drift and revocation require fresh retrieval admission,
not reuse of a historical authorization receipt.

Files use the actual Applications exact-answer clean-state/retention/byte reader.
Anonymous or withheld identifying content is omitted before lookup. The archive
does not expose historical private host availability, foreign personal calendars,
unrelated records, or named-person-only approval rationale through broad profile
configuration. Existing private review-history permissions may retain withdrawn
copy as C3 evidence; it is never republished or treated as current C0 sharing.

Output is a portable, restricted archive with an inspection recipe, not a current
timetable, database backup, import command or alternate operational truth.
Logical restore remains #97, accountable stop-use remains #190, and stopping the
module does not automatically waive the rights needed for a later download.

## Consequences, verification and rollout

One extra capability and scoped recipe are necessary; existing viewing authority
and immutable roles are not widened. Native capability scope and recipe definitions
must stay synchronized with their code catalogs, use fail-closed unknown-code
behavior, and fence rollback once retained authority/request/output evidence exists.
Do not manufacture readiness hashes, bypass migration guards or activate a profile
to exercise the boundary. Keep PostgreSQL cases maintained but unexecuted while
ADR 0100 is deferred; any schema-only evidence remains separate from native proof.

Maintain tests for independent export/source denial, wrong requester/tenant/edition,
field ceilings, complete pagination and lineage, source/permission changes,
file withholding, cancellation, retries, audit failure, expiry/disposal, resource
bounds and excluded effects. Actual P11/P12 and restored #102/#109, genuine-person
#92 and recovery acceptance remain required before completing #48 or a pilot.
This ADR adds no running worker, usable export screen, stored artifact or grant.

## Alternatives considered

- Widen ordinary history or summary projections to include all lineage: rejected
  because their existing field meanings and audiences are deliberately bounded.
- Treat export authority as access to all owner bodies: rejected; independent
  source permissions and retention remain mandatory.
- Treat the current memory-only codec or a synchronous attendee report as the
  full archive service: rejected because the required purposes and volumes differ.
- Add a generic reporting platform or select external storage now: deferred;
  only the purpose-specific Programme exit workflow is required by #189.
- Offer a database dump or signed timetable as the exit: rejected by ADR 0081;
  those artifacts serve different operators and recovery/disclosure purposes.
