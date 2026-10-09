# Announcements module

Status: Standalone manual publishing implemented; protected delivery pending
Last updated: 2026-10-09

## Purpose and ownership

`maru.announcements` owns canonical announcement copy, immutable versions,
channel/language variants, independent review, manual publication reports,
corrections, record-keeping settings and portable outputs. It implements the bounded
manual subset of ANN-001, ANN-003 through ANN-005 and ANN-007 through ANN-009 under
[ADR 0117](../architecture/decisions/0117-standalone-manual-announcements.md).
The [page contract](../product/page-contracts/announcements.md) owns the human journey.

The exact `announcements_only@1` adoption profile contains required foundations
plus Announcements. It creates no attendee, Registration, payment, attendance,
Workforce, Programme or recipient-notification records. Communications retains its
service inbox responsibility. External websites and social/chat channels remain
authoritative for their posts; Maru records approved copy and attributable reports.

## Command and query contract

The native browser adapter uses the same owning application boundary as any later
adapter. Commands establish settings, save immutable drafts, request review, decide
an exact review, record or correct a manual publication report, cancel remaining
work and stop/resume new use. Current authorization, exact profile and trusted
organization/edition scope precede every mutation, including idempotent replay.
Optimistic announcement and settings versions distinguish competing work; changed
retry payloads conflict. A draft save binds the settings the writer saw. Exact
authorized retries remain recoverable when later settings remove a destination.
Receipt, minimized audit and domain facts commit atomically with the owned state.

Queries provide a bounded workspace, announcement detail, exact approved-copy
rendition and independently authorized private handover export. Public copy excludes
private review comments, people history, policy notes and internal identifiers that
serve no publishing purpose. Private downloads recheck authority and scope before
releasing any bytes. No query creates a report, sends a message or changes a draft.

Every editor in the current draft round is an author for independent review.
Saves and requested changes retain that author set; a new correction round
starts only from an independently approved version. Approval applies to
one immutable version and all of its exact renditions. Changes require fresh review;
a pending correction leaves the last approved rendition and reports available.
After approval, only differing channel copy requires an update. Reports are claims
with report actor/time, claimed publication time and optional safe external link.
Corrections append evidence rather than changing the original claim. Cancellation
and stopping work cannot delete external posts or rewrite published history.

## Authority and foundations

Capabilities separate `announcements.view`, `announcements.compose`,
`announcements.review`, `announcements.record_publication`,
`announcements.manage_settings` and `announcements.export_evidence` at exact edition
scope. Self-review is prohibited independently of broad platform or root access.
The new purpose-specific Announcements operators use the existing truthful,
two-person accountable representation controls; existing Workforce operators and
exact profile versions retain their previous meaning. Guided setup creates or
reuses only Organization, Convention series and Event edition foundations.

## Data, retention and external effects

Drafts and review comments are private operational content; author/reviewer/reporting
actor identities and timestamps are personal accountability evidence. Exact approved
copy is a distinct publication rendition, not a reclassification of its private
source. Free text must not contain restricted case narratives or credentials.

An authorized organizer must confirm the real record-keeping rules, owner and review
date before new content collection. The bound settings version retains what was
confirmed and by whom. This is an accountable organizational statement, not legal
certification or automated disposal. Actual retention periods, holds, disposal,
backups and exported-copy custody remain governed by the deploying organization's
rules. No generic retention period or legal basis is invented by this module.

Domain events contain minimized identifiers/state facts, never announcement text,
review notes or contact data. This profile has no external sending route. It adds
no tracking pixels, recipient directory, audience analytics or notification side
effects. Provider outages therefore do not prevent preparing or recovering copy.

## Portability, stopped use and recovery

Manual text entry provides a preview-first import from existing tools. Approved
text can be selected, downloaded and printed without JavaScript. A separately
protected handover export retains version lineage, settings references, review and
manual report evidence with format/integrity metadata. Downloads do not claim
publication and are not bearer authorization to read Maru later.

Stopping or cancelling prevents new writing and review while retaining authorized
historical reads and exports. Operators may still record earlier publication of
approved copy and correct retained reports, including older reports whose channels
are no longer configured. Correcting an older report does not make it the latest
publication. There is no self-service destructive uninstall or automatic external
deletion. Owning migrations
must preserve scope, append-only facts and the command-evidence graph. Reverse only
an unused installation where the explicit migration fence permits it; used stores
fix forward or restore a complete mutually consistent database. Runtime relation,
function and readiness contracts are part of the same change, never bypassed by an
owner connection. Operational errors expose a safe retry/reconciliation path without
logging private copy or policy details.

## Scope and verification limits

Scheduled or automatic sending, emergency authority, private recipient targeting,
images, provider credentials and recipient acknowledgement are later increments.
They are not completed by a manual publication report. Independent-person usability,
specialist accessibility, operational ownership and production recovery remain
separate from automated and assistant-operated synthetic verification.

Implementation evidence, exact tests and remaining work are maintained in
[CURRENT](../project/CURRENT.md) and the
[implementation checkpoint](../checkpoints/2026-10-09-standalone-announcements.md).

## Public interfaces and migration ownership

`announcements.contracts` defines immutable `AnnouncementReadRequest` and
`AnnouncementCommandRequest`, settings/draft/variant inputs, identifier-only command
results, and bounded page/detail/copy/download projections. A command request carries
the actual actor, exact organization and edition, correlation and retry identifiers;
none of those values grants authority.

| Public boundary | Operations |
| --- | --- |
| `announcements.services` | `update_announcement_settings`, `create_announcement`, `revise_announcement`, `request_announcement_review`, `review_announcement`, `record_announcement_publication`, `correct_announcement_publication`, `cancel_announcement`, `set_announcements_stopped` |
| `announcements.queries` | `load_announcement_settings`, `list_announcements`, `load_announcement`, `load_approved_announcement_copy`, `load_approved_announcement_preview`, `export_announcement_evidence` |
| `events.announcements_adoption` | `set_up_announcements_adoption`, using the closed input in `events.announcements_setup_inputs` |
| `events.announcements_scope` | Current exact-profile scope resolution without authority expansion |

The internal `announcements.changed.v1` domain event contains the operation and
standard scoped aggregate metadata, never public copy or private comments. This
profile has no adopted external delivery route.

Announcements owns `0001_initial`, `0002_integrity` and `0003_downgrade_fence`.
The additive foundation changes belong to Organizations `0015`, Authorization
`0042`, and Events `0019` through `0021`. Events `0020` is the SQL-only setup guard
source and `0021` fences removal of used setup evidence. Readiness checks the native
source and installed guards for both setup and the Announcements store.

The current runtime helper closure is v5: it preserves frozen v4 and adds only
`maru_assert_active_announcements_operators(uuid)` and its `_v0009` implementation.
Runtime writes are limited to insert/update of the control and announcement
aggregates and insert-only immutable settings, copy, variant, review, publication
report and command receipt rows. Delete, truncate and schema ownership are not
runtime permissions. The isolated Programme test overlay retains all three current
profile manifests unchanged and appends its separately fenced test candidate.
