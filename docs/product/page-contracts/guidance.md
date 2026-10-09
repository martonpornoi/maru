# Guides workspace and access decisions

Status: Accepted scope; implementation in progress, not verified
Requirements: KNO-001, KNO-002, KNO-008, KNO-010 through KNO-013, NFR-013, UX-031
Decisions: [ADR 0118](../../architecture/decisions/0118-reviewed-internal-guidance.md)
and [ADR 0119](../../architecture/decisions/0119-guidance-adoption-and-purpose-authority.md)

The product label is **Guides**. Guidance and Knowledge remain the technical
contract and owner-module names. Ordinary pages say Read guides, Write a guide,
Set up Guides, Stop using Guides and Resume Guides.

## Purpose and routes

Help a convention team write useful internal FAQs and runbooks, have another
editor check them, and put current guidance beside the task it governs. Guidance
works alone or as an explicitly approved addition to the same Announcements event.
Adding it retains the organization, convention series, event and existing records.
Adoption and new access are separate accountable decisions, never inferred from
an existing Announcements role. The initial owner is the actual accepted Guidance
operator team for this event; named reassignment is outside this increment.

The native workspace is `/admin/guidance/<organization_id>/<edition_id>/` in
Overview. Its landing selects `work/` for admitted working readers and `current/`
for admitted current-only readers. Reader items use `current/<item_id>/`; private
details use `work/<item_id>/`. Creation, editing, review, withdrawal,
settings and stopped-use controls belong beside the working inventory. There is one
shared shell, selected event, page H1 and main landmark. Reader pages do not
present an editorial dashboard or imply access to Announcements.

## Setup and access

Fresh setup starts at `/admin/platform/setup/guidance/`. Creation redirects to
the exact organization/event activation page, preserving the event while the
platform administrator finishes the existing organizer-responsibility ceremony.
An inactive foundation offers that handoff; it does not grant content access or
lose the event context. The same activation page adds Guides to an existing
Announcements-only event without duplicating its identity or records.

The platform administrator explicitly selects two currently accepted people.
Each receives the same proposal, naming the event, both people, reason, deadline
and responsibilities. All seven content powers and the separate power to manage
Guides access are explained before either person answers. **Accept my
responsibilities and approve the other person's assignment** and **Decline this
setup** are explicit choices without a default. Only the original platform
proposer can apply the fully accepted setup. Neither viewing nor creating a
proposal grants access. Technical profile and role identifiers are secondary.
The final link and submission say **Finish access setup**, explaining whose
accepted responsibilities take effect. Initial access setup leaves the required
record-keeping rules as a separate next step.

The personal **Guides decisions** inbox at `/admin/guidance-tasks/` combines only
currently actionable setup and access decisions from their separate owner queries.
Each card names the request and has a separate **Review setup request** or
**Review access request** link styled as a button. Repeated action labels retain
their card's accessible heading context. Ordinary setup pages say **request**;
technical command and data-contract identifiers remain unchanged.
Retained setup history remains at `/admin/guidance-setup/tasks/` and request pages.
Completed setup offers **Open Guides** only after a separate current
Knowledge admission for the actual actor and exact event. A platform proposer
without content access receives a handoff to the people who accepted.

**Manage access to guides** uses a separate purpose-specific authority query;
being a reader, writer or reviewer never implies that power. At
`/admin/guidance/<organization_id>/<edition_id>/access/`, an admitted person may
request Read guides, Write guides, Review guides or Run Guides for an existing
verified account. The recipient email, responsibilities, optional end time,
reason and actual named approver are visible. An empty end time explicitly means
no planned end. This form sends no invitation and cannot assign access managers.
The named second person answers from their own account through
`/admin/guidance-access/tasks/`. A proposal is not an approval; each exact
decision and its resulting assignment remain separate.

Removal names one exact assignment and keeps its history. Removing an
access-management assignment warns that dependent assignments may also become
unavailable and that a new accepted setup may be needed. Other assignments are
not silently removed. Stale forms retain their original people, scope, request
key, version or fingerprint and reach the owning retry contract without claiming
new consent. Every page rechecks its complete admitted snapshot before release.

## Authority and disclosure

`knowledge.view_current` admits current summaries and copy. Working versions,
feedback and history require `knowledge.view_working`; writing, independent
review, withdrawal, settings and private export each require their own capability.
The shared Access disclosure says **Access for this area** beside the exact scope;
the personal decisions inbox uses **Your own records**. These labels explain
existing permissions without changing the scope, details or available actions.
Reader and working queries are separate: rendering a reader page must never load
private drafts or feedback first and filter them later. Scope and field admission
precede input parsing, identifying labels and content. Every destination and
download authorizes again; navigation is not authority.

Missing, foreign, denied and withdrawn reader objects use the same unavailable
response unless an owning query explicitly admits a safe withdrawn projection.
Dependency failure releases no partial HTML or download bytes. Responses are
private and no-store. Sensitive reads follow the owning audit contract; this
increment adds no reader analytics, acknowledgement or activity tracking.

## Writing and review

The first writing controls are **Title**, **Guide text** and **Language** when the
event offers more than one language. One-language events show the actual language
as text. The owner and audience are fixed visible statements: the accepted
Guidance team and Guidance readers for this event. Neither requires an invented
free-text responsibility, an unrelated team record or a single-option dropdown.

A draft may omit its review date. **Ask for review** requires the date to be set
in the exact saved revision. Optional reviewed placements appear under **Where
to show this guide**. Only code-owned supported tasks are offered: Writing
guides, and Writing announcements when that event deliberately adopts both.
Required decisions and errors stay visible rather than being hidden as technical
detail. Saved drafts retain their original values and versions on failure.

**Save draft → Ask for review → Approve and make available** is the ordinary
journey. Everyone who helped write that version needs someone else to approve it.
Review shows the exact text, language, team owner, audience, review date and task
placements together. A request for changes retains private feedback. A correction
leaves the earlier approved guidance available until the replacement is approved.
Current text and pending work must never be mistaken for each other.

Ordinary states use Draft, Waiting for review, Changes requested, Current and
Withdrawn, with Review overdue shown separately. Review dates do not silently
renew approval or withdraw content. Readers see a clear overdue notice, the
recorded date and responsible team. History identifies replaced versions without
presenting them as current instructions.

## Readers and contextual guidance

The reader journey is Search, Read, then Print or Download text where permitted.
Search results show a title and useful status, not private editorial metadata.
An empty library says that the team has not made guidance available yet; it does
not expose hidden draft counts. Public publishing, attachments, rich text,
acknowledgements, automated translations and reader tracking are outside scope.

**Guides for this task** uses the owning current-summary query beside supported
writing pages. A person must be admitted to both the task and its guide summary.
Opening the guide independently requires current-copy admission.
Only approved current placements appear. A matching guide is a link to the same
canonical reader page, not a copied or separately editable text fragment. Old,
withdrawn or inaccessible versions cannot remain cached in the task surface.

Print and text downloads identify the exact copy, event, language, approval and
review date and warn that saved copies may become outdated. They omit private
feedback and history. **Download full history** is separately admitted and warns
that it includes private notes. Technical identifiers and export formats are
secondary disclosures; current status and consequences are not.

## Withdrawal, stop and resume

**Withdraw guide** requires an explanation and retains its history. It cannot
be automatically undone by resuming the workspace. **Stop using Guides** hides all
reader and contextual copies and pauses writing and review. Authorized private
history, evidence export and withdrawal remain available.

**Resume Guides** previews exactly which retained current versions will become
available again and requires explicit confirmation bound to the current workspace
version. A changed preview requires a fresh decision; a stale form cannot publish
newly changed content by accident. Withdrawn copies never appear in that preview.
These controls affect Guidance only and do not change Announcements behavior.

## Errors, accessibility and acceptance

Use native forms, links, buttons, fieldsets and disclosures with visible focus.
Validation links to associated fields, retains entered text and exposes any
section containing an error. Conflicts explain that the original form still
refers to an earlier version; do not silently replace its retry key or source.
Success redirects to the actual resulting state. No GET changes adoption, content,
review, availability or acknowledgement.

Long multilingual content and names wrap without page-level horizontal scrolling.
Print, keyboard navigation and the complete workflow work without scripts. Existing
shared navigation, context and Access disclosure remain authoritative. Formal
specialist accessibility and independent-person acceptance remain separate gates.

Focused verification must cover reader/private separation, all current scope and
field denials, independent approval, retained retry intent, current-copy replacement,
overdue dates, reviewed placement, withdrawal, stopped reads, exact resume preview,
safe downloads and native error/no-script behavior. The operator walkthrough owns
the concrete synthetic rehearsal. No browser or test result is claimed by this
contract while implementation and certification are pending.


### Bounded personal Guides decisions

The paged Guides access-decision and history facade applies across the existing
admitted profiles without changing manifests, canonical roles or field authority.
The original unpaged owner API retains its 100-request complete-or-unavailable
contract, and the existing access-workspace assignment limit remains unchanged.
Personal pages scan at most 100 requests plus one locator lookahead, newest first
with a signed actor/mode-bound `(created_at, id)` cursor. Every disclosed row
rechecks current exact source authority. An empty scan keeps **Next access
requests** or **Next page** when candidates remain; it does not claim completion.

Shared navigation distinguishes proven current work (**Guides decisions**) from
unexamined candidates (**Check Guides requests**). The latter continues a bounded
scan without labels, counts or a promise that remaining requests are actionable.
Only the existing setup owner's explicit capacity condition can leave an
independently admitted access section available with a generic setup notice.
Native protection failures, including final rechecks, produce an unavailable
response rather than false emptiness or continuation. Ordinary denied rows remain
hidden. No matching personal candidates means no Guides readiness check, so an
unused Guides workflow cannot block unrelated personal work. Compatible owner
integrity exceptions remain subclasses of `PermissionDenied`. No history-wide
scope scan, new storage limit, cached authority or Reading capability is added.
