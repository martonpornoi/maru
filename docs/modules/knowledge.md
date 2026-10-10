# Knowledge module: Guides and FAQs

Status: Implementation in progress; verification pending
Last updated: 2026-10-09

## Purpose and ownership

`maru.knowledge` owns internal plain-text guides, settings, immutable revisions,
independent review, current availability, withdrawal and portable outputs.
KNO-010 through KNO-013 and [ADR 0118](../architecture/decisions/0118-reviewed-internal-guidance.md)
define the first bounded journey. The interface calls it **Guides**.
The [page contract](../product/page-contracts/guidance.md) describes its screens;
the [walkthrough](../operations/guidance-maintainer-walkthrough.md) gives the
synthetic maintainer journey and its verification limits.

A guide has one language, title, text, review date and approved task placements.
Its responsible owner is the actual accepted Guides team for the event. Its
fixed audience is people with current guide-reading access to that event.
An unfinished draft may omit the review date; asking for review requires it.
Another authorized person approves the complete version. Everyone who edited
that draft round remains an author through requested changes and cannot approve it.
Approval makes that version available immediately in Maru. A correction draft
leaves the last approved copy current until the correction receives fresh review.
An overdue review date is a visible warning, not automatic removal or renewal.

## Public boundaries

The browser and other modules use the same owning commands and separately
admitted queries. Request values identify the actual actor, organization, event,
correlation and retry; possession of identifiers grants nothing.

Command `source_channel` is canonical, nonempty plain text of at most 40 Unicode
characters, matching the existing Audit record field. Overlong attribution is
rejected before the owning transaction or retry lookup. Noncanonical text keeps
its existing idempotency-conflict error; no normalization or error reclassification
is introduced. Accepted attribution remains part of the exact retry intent
without truncation.
The browser supplies the fixed `knowledge-html` value. The historical receipt
column still allows 80 characters, and conservative storage/reserve accounting
keeps that bound; it is not the new-command admission ceiling.

| Public boundary | Operations |
| --- | --- |
| `knowledge.contracts` | Immutable request/input/result and reader, working-copy, resume-preview and download projections |
| `knowledge.services` | `update_guidance_settings`, `create_guidance`, `revise_guidance`, `request_guidance_review`, `review_guidance`, `withdraw_guidance`, `stop_guidance`, `resume_guidance` |
| `knowledge.queries` | `load_guidance_options`, `load_guidance_settings`, `list_current_guidance`, `load_current_guidance`, `load_context_guidance`, `list_working_guidance`, `load_working_guidance`, `load_guidance_resume_preview`, `download_current_guidance`, `export_guidance_evidence` |
| `knowledge.authorization` | `authorize_guidance_scope` for current, exact-purpose page admission |
| `events.knowledge_scope` | Exact adopted-edition resolution without content authority |
| `authorization.guidance_authority_queries` | Current accepted-team reference and purpose-qualified access evidence |

Reader queries select only approved copy and metadata. They do not load draft
text, private feedback, reviewer identities or private settings and then redact
them. Search and continuation are bounded. A summary-only field grant searches titles;
matching the approved body requires current-copy field admission and its final recheck. The only contextual placements are
`knowledge.compose` and, in the combined profile, `announcements.compose`.
The receiving page independently asks Knowledge for current content; its own
permission cannot substitute for guide-reading access. Before releasing a page,
adapters recheck the snapshot so withdrawal, replacement or access loss cannot
release a previously rendered private title. Unavailable contextual guidance
leaves the receiving writing task usable without hidden titles or counts.

## Adoption and access

[ADR 0119](../architecture/decisions/0119-guidance-adoption-and-purpose-authority.md)
owns fresh `guidance_only@1` setup and the explicit, reviewed transition from
`announcements_only@1` to `announcements_guidance@1`. Existing profile meanings,
event identities and Announcements records remain unchanged. Setup creates only
necessary foundations; it creates no Registration, Participation, attendance,
payment, Workforce or Programme records.

Seven capabilities separate `knowledge.view_current`, `knowledge.view_working`,
`knowledge.compose`, `knowledge.review`, `knowledge.withdraw`,
`knowledge.manage_settings` and `knowledge.export_evidence`. Exact-event access
management is a separate Authorization responsibility. A platform administrator
or an existing Announcements administrator does not gain guide content authority.
Actual separate acceptances establish the initial team. Later canonical access
requests need the named approver's authenticated decision; a recipient cannot
approve their own assignment. Current pinned source authority remains mandatory.

Each append-only setup or access request, actual decision and activation or
revocation receipt emits its own version-one domain event using that row's
canonical type and ID. Parent request IDs remain relationships, not reused event
aggregate slots. Exact actor, scope, correlation, source audit and internal outbox
stay bound atomically; an exact replay emits no additional event.

## Retained evidence, availability and recovery

Settings record the organization's actual readable record-keeping rules, owner,
review date and confirmation covering text, feedback, attribution and exports.
Overdue rules block new collection and review until refreshed, while authorized
history, withdrawal and private export remain available. This does not invent
retention periods, a lawful basis or automatic disposal. The
[retention inventory](../security/data-classification-and-retention.md) governs
classification and separate custody of backups and exported copies.

Withdrawal requires a reason and the current item version. It removes ordinary
reading, search, contextual links, printing and current downloads while preserving
separately authorized history. **Stop using Guides** also hides current copies
and blocks writing and review, leaving Announcements unchanged. Resume requires
a confirmation bound to the complete retained-current inventory and control
sequence. Every intervening command invalidates that preview; withdrawn guides
stay withdrawn.

Each guide's retained evidence is limited to 8 MiB. Every non-withdrawn
item keeps 8 KiB inside that total for one withdrawal receipt, including
the maximum permitted reason and source text. Further writing fails
without replacing the current copy when it would spend this allowance.
Withdrawal may consume it; subsequent writing must reserve it again.
Native deferred checks use the actual final item receipt, so an ordinary
write followed by withdrawal in the same transaction needs one allowance.
The 256-revision and 4,096-item-command limits remain unchanged. The
current state machine permits at most four item commands per revision,
so its byte reserve does not require a separate command-count allowance.

This admission rule cannot retroactively fund an already full immutable
history. An existing installation needs a locked retained-state review
before stronger guards are deployed; deficient history needs an explicit
fix-forward decision. Editing a recorded migration does not install a
new guard. Neither history deletion nor a larger cap is an implied repair.

Current text and print outputs identify their event, language, copy number,
review date and generation time, and warn that saved copies may become outdated.
They are internal copies, not public publication or later permission tokens.
Private evidence export has its own capability and canonical integrity digest.
For one guide it includes all of that guide's versions, reviews and commands,
the current edition control snapshot, and all edition settings and stop/resume
evidence. It excludes unrelated guide content and item commands. The export
identifies that scope and explains resulting shared command-sequence gaps.
Complete control history is bounded to 4,096 commands and the envelope to 16 MiB;
overflow fails explicitly rather than silently truncating history. These bounds
do not delete records or define their retention.
Pasted text starts a new draft and cannot import trusted approval.

Commands lock scope, recheck current authority before retry, reject changed retry
payloads and use optimistic item/settings versions. State, immutable receipts,
audit evidence, minimized internal events and outbox rows commit together.
`knowledge.changed.v1` carries closed operation and scoped identifiers, never
text, private notes or contact data. No external delivery route or reading
analytics is added.

Knowledge owns six tables and migrations `0001_initial` through
`0003_downgrade_fence`. Native guards check both receipt-to-state and
state-to-receipt correspondence. Runtime may insert/update control and item rows,
and only insert immutable settings, revisions, review and command receipts.
Used Guidance, adoption or joined predecessor evidence refuses downgrade before
successor guards or migration records are removed. Reverse only a verified unused
installation; otherwise fix forward or restore a mutually consistent database.
Runtime helper generation v6 preserves v5 and adds the two workspace foundation
assertions and five purpose-qualified Guidance helpers. The ten new foundation
decision/qualification relations are insert-only; edition locks serialize their
commands without granting those evidence rows update privileges. Source pins and
installed guard readiness accompany the behavioral checks.

Files, rich text, acknowledgements, private case requests, public audiences,
notifications and external indexing remain later work. Automated and synthetic
browser results do not establish independent-person comprehension, specialist
accessibility or production acceptance. Current evidence belongs in
[CURRENT](../project/CURRENT.md), not this interface contract.
