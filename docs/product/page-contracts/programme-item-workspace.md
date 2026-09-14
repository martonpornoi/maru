# Programme item workspace

- Status: First increment delivered through PR #112; #108 remains open. Dormant
  routes only, not profile activation.
- Requirements: PRG-005, PRG-006, PRG-008, UX-013, UX-029, NFR-013.
- Decisions: ADRs 0081, 0086, 0087, 0096 and 0100.
- Owner: Programme; shared Administration shell, no specialist-record dependency.
- Reserved route: `/admin/programme/items/<organization>/<edition>/`.

## Outcome and sequence

An authorized organizer selects a labelled private item or creates a ceremony,
break, announcement or other organizer core item. Item pages separate working
copy, delivery instructions, readiness and reviewed public copy. Creation does
not fabricate a proposal, host, review, readiness evidence or publication.
Accepted proposals continue to use the reciprocal Applications conversion.

This is the first reviewable #108 increment. Calls/proposals, review, conversion,
host self-service, notice task choices, connected navigation and guided setup
remain #108 work, followed by #109 integrated acceptance. Neither this page nor
one supporting PR closes #108. Current manifests, runtime writers and production
URL configuration stay unchanged. #102, #97 and #92 precede final promotion.

## Scope and disclosure

The authenticated principal and organization/edition path are trusted inputs to
owner authorization, never authority themselves. The inventory requires
`programme.view_private` and its item/working field ceiling. It is complete up
to the existing item ceiling, or unavailable, never silently truncated. It
contains current working labels, item kind/lifecycle/version and the creation
control version, not summaries, people, readiness or delivery fields.

An item page requires private working read permission for its title and source.
Delivery, readiness and current approved public copy additionally require their
independent read capabilities and fields. Private public-copy review history
uses `programme.view_private` with `public_copy_review_history`, independently
from the base working fields. A layer is loaded only when explicitly selected;
navigation may not disclose inaccessible layers. Mutation permission does not
imply permission to read an item, its labels, reasons or adjacent layers.
The working source identity is a hidden exact command reference, not a text-entry
task or permission token. Owner queries authorize before lookup, recheck before
disclosure and audit first. Scope locks keep item version and working source
coherent. Reason/history reads retain their existing independent field ceilings.

## Writes and failure

Use only existing Programme commands: core creation, working revision, delivery
revision, readiness configuration and public rendition approval. Submitted text
is explicit; private copy is never automatically copied into public fields.
Readiness configuration is not evidence of satisfaction. Public-copy approval
is not timetable publication; Ready/Live approval retains the existing independent
reviewer rule. Historical withdrawals must not expose an older rendition as current.
The next #108 increment adds three independently selected decisions. Department
discussion requires `programme.view_discussion`/`discussion_entries`, lists the
latest 200 retained entries and appends through `programme.manage_items`; it is
not general chat. Evidence requires readiness read/write authority and an explicit
concern, state, note and source choice. Operator attestation has no object source;
working, delivery and available public-rendition references are offered only after
their independent source-layer read authorization. Choices name exact sequences,
not raw UUID-entry tasks. Sources are never silently advanced on a refused POST;
an expired choice remains a rejected original intent, not a newly bound command.
Existing dependency/version validation and actual host facts remain authoritative.

Public-copy withdrawal uses separately authorized private review-history labels
and an exact retained rendition, never an implicit latest selection. It requires
`programme.approve_public_copy`, a current genuine person and retained reason.
Explain that disclosure of the selected rendition, including retained releases,
is withdrawn without replacing the timetable or falling back to older copy.
This privacy exit remains available for retained/retired items and Closing/Archived
editions; ordinary planning lifecycle checks must not hide or block it. The owner
still fences exact item version, scope, idempotency and existing withdrawal state.
Do not offer already withdrawn renditions as new withdrawal targets.

Organizer hosting and genuine-person hosting/availability use the separate
[hosting page contract](programme-host-workspace.md) in the same #108 increment, not private-item permission
as a substitute for person-owned authority. These decisions are not yet delivered
by PR #112; their implementation and evidence must be recorded separately.

CSRF-protected POST carries one closed form, the originally displayed version,
one retry key and a retained reason. Reject unknown/duplicate fields, files and
unsupported selections. Commands reauthorize and enforce lifecycle, scope,
independence, version and retry semantics transactionally. Never substitute a
fresh version after conflict. Successful writes redirect to a fresh owner read;
failed writes retain bounded input only while the caller still has its read and
write authority. Denied responses disclose neither values nor existence.
Dependency/audit failure gives unavailable output, not partial content or a false
empty inventory. Read-only pages omit mutation controls. Empty and missing
evidence states explain the next task without reporting a readiness percentage.

## Interface and acceptance

One H1, one host main landmark, computed Access disclosure, ordinary labelled
forms and links, visible focus and bounded wrapping cards. Error summaries focus
and associate field errors. A stale form explicitly asks the operator to review
the latest source before making a new attempt; reloading discards entered input.
Task content precedes the retained reason. Native before-unload protection warns
when input differs or a failed form is returned, preserves original retry/source
values, permits deliberate submit and rearms on page restoration. It neither
autosaves nor persists private input in browser storage.
The full seven-width/200-percent/keyboard/screen-reader matrix remains #92; source
tests and synthetic rendering do not certify it.

Non-database tests cover strict forms, command forwarding, unchanged conflict
tokens, disclosure ordering, each independent layer, no-store output, CSRF,
escaping and dormant production routes. Maintain native scope, coherent-version,
audit rollback and real command cases without executing PostgreSQL under ADR
0100. No migration or schema-only check is needed for this increment.
