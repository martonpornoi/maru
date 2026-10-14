# ADR 0118: Reviewed internal Guidance beside convention tasks

- Status: Accepted; implementation in progress
- Date: 2026-10-09
- Extends: ADRs 0003, 0005, 0031, 0041 and 0116
- Requirements: KNO-001, KNO-002, KNO-008, KNO-010 through KNO-012,
  IDN-002, IDN-005, AUD-001, UX-031 and NFR-013

## Context

Convention teams need a dependable answer to everyday questions such as how to
announce a fursuit lounge closure or whom to contact about a blocked corridor.
A folder of documents does not establish which copy is current or put the answer
beside the work. A reader should not need to understand approval settings, see
private feedback, or join unrelated attendee and volunteer workflows.

The architecture assigns knowledge to `maru.knowledge`; no existing module owns
this lifecycle. The first useful increment is internal plain-text guidance, labelled **Guides**
in the interface (with guides and FAQs described in its introduction).
The broader Knowledge requirements also cover files, restricted audiences,
acknowledgements, forms and service requests. Those remain separate increments.

## Decision

### One internal owner and one complete journey

`maru.knowledge` owns edition settings, guidance items, immutable text revisions,
exact review decisions, current availability, withdrawal and command evidence.
The journey is **Write guidance -> Ask for review -> Approve and make available
-> Read beside a task -> Revise or withdraw -> Print or download**.

Each guide has one language, a title, text, review date and approved placement.
Its initial purpose is internal convention guidance. Its accountable owner is the
actual accepted Guidance operator team for the edition, not an invented person
named in free text. Its audience is people with current Guidance reading access
for that edition. Named-owner reassignment and narrower or public audiences need
later contracts. An unfinished draft may omit its review date; asking for review
requires it. A single configured language is shown as text rather than a
single-choice form field.

Seven capabilities separate current reading, working-copy/history reading,
composition, review, withdrawal, settings and private evidence export. Selecting
an event or reaching a URL grants none. Every command, query and download checks
current scope and authority. Platform oversight is not ordinary Guidance content
or approval authority. Setup and supplemental access are governed separately by
ADR 0119; these owner services cannot activate themselves through configuration.

### Review the complete version

Another authorized person approves the exact revision, including its title,
text, language, review date and task placements. Everyone who edited that draft
round is an author and cannot approve it. Requested changes and resubmission do
not clear authorship. A new correction round starts from an independently
approved version. Review comments and attribution remain private working history.
There is no self-approval or platform bypass.

Approval makes that exact version current immediately in Maru. This differs from
Announcements, where a person reports publishing copy elsewhere. Preparing a
replacement keeps the prior approved guidance current; approval replaces it
atomically. A review date passing adds **Review overdue** without withdrawing the
copy, advancing its date or claiming a fresh check. Changing that date requires a
new reviewed revision.

Withdrawal immediately removes a guide from current search, contextual placement,
printing and downloads, while retaining separately authorized history. It requires
a reason and the current item version. A review started before withdrawal cannot
silently restore it; restoration needs a fresh explicit review against the changed
item state. Denied, absent and withdrawn reader destinations do not disclose
private history or hidden replacements.

### Reader surfaces select only approved content

Readers search current guidance and open a canonical guide page. The current
projection contains approved text and metadata, the accountable team label,
version and effective/review dates. It does not load draft bodies, private review
notes, reviewer identities or settings descriptions and then redact them.
Search is bounded and paginated; no external index or readership analytics is
introduced. Reading is not an acknowledgement or proof of understanding.

The first reviewed placements are **Writing guidance** and **Writing
announcements**. The latter exists only in the exact combined adoption profile.
The receiving task calls a documented Knowledge query; Knowledge independently
checks reading authority. Missing or denied content produces no hidden titles or
counts. Placement uses a closed catalog, not arbitrary routes or private model
imports. Placement changes require review together with the text.

Print and plain-text downloads contain only current internal copy, its edition,
language, copy number, review date and generation time. They warn that saved
copies may be out of date. They are neither public renditions nor permission
tokens. A private per-guide evidence export separately retains its complete
versions, decisions, withdrawals and command evidence, together with the current
edition control snapshot and all edition settings, stop and resume evidence.
It excludes other guides and their item commands. Scope metadata explicitly
explains that this is not the complete edition command journal; gaps caused by
other guides are intentional. The canonical integrity manifest covers this
declared scope. Control history is bounded to 4,096 commands and the complete
envelope to 16 MiB; an oversized export fails explicitly instead of truncating
history. These are export bounds, not record-retention limits. Pasted imported text
starts as a new draft and never reconstructs trusted approval.

### Settings and stop-use have honest consequences

Before collecting content, an authorized organizer records the real rules for
keeping Guidance records, their responsible owner and review date, and confirms
that the rules cover text, private feedback, attribution and exports. Revisions
bind the actual settings seen by the writer. Overdue record-keeping review blocks
new collection and review until refreshed, while retained authorized history and
withdrawal remain available. This records a decision; it invents neither a lawful
basis nor a retention period and does not execute disposal.

**Stop using Guidance** hides ordinary current-reader and contextual surfaces and
blocks new writing and review. It leaves Announcements unchanged. Authorized
history, evidence export and withdrawal remain available. **Resume Guidance**
requires an explicit confirmation of which retained current versions will return,
bound to the current control sequence and preview digest. Withdrawn items stay
withdrawn. Any intervening command makes the preview stale.

### Integrity and recovery remain owner responsibilities

Commands use closed bounded inputs, optimistic versions, idempotent retries with
changed-payload rejection, deterministic locking and current authorization before
replay. State, immutable receipts, audit witnesses, minimized internal events and
outbox records commit together. PostgreSQL checks scope, version chains,
independent review, immutable evidence, allowed transitions and both directions
of receipt-to-persisted-state correspondence. A well-shaped receipt cannot stand
in for a mutation that did not happen.

The 8 MiB retained-evidence cap includes an 8 KiB allowance for one
maximum-input withdrawal receipt while an item is not withdrawn. Normal
work cannot consume that allowance; refusal leaves the current approved
copy unchanged. Withdrawal uses it without raising the total cap, and
later work must reserve it again. Deferred checks use the final persisted
receipt, allowing an ordinary write and withdrawal in one transaction.
Exact retries retain their original result without new capacity use.
This is an admission guarantee for funded history, not permission to
discard old records or a retroactive repair for already full history.
Existing schemas require a locked retained-state preflight and an explicit
fix-forward choice; the pre-release source repair itself changes no
already installed database.

Runtime grants admit only the reviewed relations and exact helper closure. Native
readiness and fingerprints participate in deployment checks. Unused installation
may reverse; retained Guidance or adoption evidence requires fix-forward or a
mutually consistent restore. Stop-use does not erase records, authority history,
backups or exports. The retention inventory documents their separate custody and
subject-rights handling; no generic disposal executor is claimed.

## Consequences

Occasional editors get a short writing task and a clear second-person check.
Readers get approved answers without an editorial dashboard. Guidance can be
adopted alone or deliberately added to an existing Announcements edition without
Registration, Participation, Workforce, payments or attendance. Native and
browser evidence must cover the real reader/editor boundary and adoption journey;
assistant-operated checks do not establish independent-person comprehension,
specialist accessibility or production acceptance.

## Alternatives considered

- A file upload library first would add storage, malware handling and rendition
  boundaries before proving the basic reader journey.
- Reusing Announcements records would confuse internal availability with reports
  of external publication and expose unnecessary channel concepts.
- Automatic withdrawal on the review date could remove still-useful operational
  guidance without an accountable decision.
- Free-form named ownership would claim responsibility without acceptance.
- Custom document audiences, rich text, acknowledgements, scheduled publication,
  reminders and read tracking are deferred until their own complete contracts.
