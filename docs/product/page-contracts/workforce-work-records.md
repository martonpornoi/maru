# Work records and handover

- Status: Accepted target contract under #24; no implemented route or new authority
- Last updated: 2026-10-31
- Requirements: HR-009, HR-018, SCH-012, PRI-001 through PRI-004, AUD-001,
  UX-029, NFR-001, NFR-002, NFR-004 through NFR-009, NFR-013
- Decisions: ADRs 0078, 0080 and 0130

## Human outcome and current boundary

A volunteer can report when they worked, see what a reviewer verified and
challenge a correction without sharing why they could not attend. An authorized
organizer can distinguish a plan, a reported observation and a reviewed Work
record. A handover recipient can understand exactly what they accepted.

Today **Complete shift** closes ended locked planned work and its confirmed
commitments. It records no arrival, departure, actual interval or accepted
handover. The [existing Shift pages](shift-planning-and-my-shifts.md) remain
unchanged. This contract adds no route, form, permission, schema or collection.

## Proposed placement and roles

The future personal continuation is **My shifts → Work record** on one retained
commitment. The organizer continuation is **Shift detail → Work records**.
These are target labels, not existing links or permission to mount a page.
Use the existing shells, one H1 and `main`, edition-local times with explicit
offsets, accessible forms, keyboard/focus recovery and truthful status text.

| Actor | Permitted purpose | Required boundary |
| --- | --- | --- |
| Actual subject | Own retained work, submit report, inspect/dispute correction | Current verified account, exact-self retained-work proof and dedicated adopted purpose |
| Operational observer | Record a narrowly scoped observation | Dedicated exact-edition/Department/Position write authority; no inferred general directory |
| Independent reviewer | Inspect complete permitted report and verify/return one version | Separate current read/review fields, actual actor different from report author/subject |
| Handover recipient | Accept or return one addressed checklist version | Own session and genuine current work purpose; no proxy acceptance |
| Policy/technical owner | Record actual rules and rehearse recovery | Separately governed policy or operational responsibility, never an alternate ordinary-user login |
| Denied/read-only person | Safe explanation or authorized retained history only | No private names/counts, disabled writes and no implied escalation grant |

No role is created by reporting work. Existing profile versions and permissions
gain no new function. Implementation must define and deliberately adopt its new
exact-version purpose before exposing collection.

## State and action language

Present planning, observation, reporting, review, dispute and handover separately.
Do not collapse them into a green **Done**, attended percentage or hours score.

| Area/state | Meaning and next action |
| --- | --- |
| Planning: Completed | Existing closeout retained; actual work may still be unknown |
| Observation: Unknown | No admitted observation; never display **Absent** by inference |
| Observation: Reported check-in/out | Show source, reported occurrence and recording times; no independent-presence claim |
| Observation: Cannot attend / Not observed | Explicit personal report or scoped operator declaration; no private cause or automatic plan change |
| Work report: Not submitted | Subject may report eligible ended retained work |
| Work report: Submitted | Immutable version awaits a different reviewer's decision |
| Work report: Returned | Explain a fixed discrepancy code; preserve inputs for a successor |
| Work report: Verified | Identify the exact verified report version; acknowledgement remains separate |
| Correction: Proposed / Effective | Show changed operational fields and lineage; never label subject agreement without their action |
| Dispute: Open / Resolved | Keep challenged version and exact recorded decision; no silent overwrite |
| Handover: Pending / Accepted / Returned | Recipient explicitly decides an exact checklist version; changed content needs new acceptance |

Lateness needs an explicit reviewed policy version and authorized declaration.
An offline device, missing report or elapsed planned start cannot create it.

## First implementation slice: report and review actual time

1. The actual subject opens eligible retained ended work. Demand must be locked
   or completed, with genuine confirmed/completed commitment provenance.
   Current identity/purpose admission happens before private work labels.
2. The page identifies the exact planned source, IANA zone and report/policy
   versions. It clearly says **Reported work**, not verified attendance or pay.
3. Enter the complete actual interval set (at most 32) and explicit contained
   break intervals (at most 32). Positive aware intervals must be nonoverlapping
   within each set, within the recorded policy horizon, and structurally valid.
   Reject DST gaps/ambiguity in local entry. A planned break is never prefilled
   as an actual deduction. The closed request is at most 64 KiB.
4. Preview reported gross/break/net time and exact changes, then deliberately
   submit with the current version and retained retry key. Preview writes no
   Work record and grants no current eligibility. Final submission rechecks all
   source, policy and authority facts inside its transaction.
5. A different currently authorized reviewer sees **Submitted**, exact version,
   interval/break details and fixed discrepancy warnings. They choose **Verify**
   or **Return for correction**. They cannot submit as the subject or approve
   their own report. Cross-record overlap is shown for explicit review rather
   than turning an observation into hidden planning changes.
6. The subject sees the exact result and any correction's operational effect.
   A returned report is corrected through a successor, never an edit of retained
   evidence. Fixed-code dispute and acknowledgement actions bind exact versions;
   acknowledging receipt is visibly separate from accepting a correction.

Define transactional record/receipt/event/audit invariants and immutable database
guards before implementing persistence. All browser/API adapters use the same
commands. Preserve idempotency after ambiguous responses; exact replay rechecks
current authority, while a changed intent using the same key conflicts.

This slice does not implement live check-in/out, bulk/manual-note ingestion,
lateness, handover storage, notifications or new schedule publication. Each needs
its own bounded implementation and acceptance before a link becomes available.

## Correction, disclosure and failure

The subject sees their own reports, source kind, occurrence/recording distinction,
review state, changed operational fields and dispute outcomes. They receive no
other person's details, organizer private rationale, exact Availability values or
unrelated history. Independent operator reads have a fixed field ceiling and
mandatory sensitive-read evidence before disclosure. Missing authority fails
without names; missing audit or moved scope releases no partial data.

No free-text personal absence explanation, medical/accommodation fact, attachment,
GPS, biometric identifier, productivity score or disciplinary inference is accepted.
Private exceptional cases belong in an independently governed purpose.
Correction preserves original, author/source, policy and decision versions.

| Condition | Required visible behavior |
| --- | --- |
| Missing/expired collection policy | Explain that new collection is unavailable; retained subject rights are not erased |
| Foreign or denied scope/person | Generic safe denial without private work existence or counts |
| Unsupported/unconfirmed source | No substitute identity or manufactured confirmation; explain authorized absence/conflict |
| Invalid interval or break | Field-associated fixed error; retain safe entered data and retry identity |
| Source/version moved | Conflict; retain original submission context, request deliberate refresh/review |
| Duplicate/ambiguous response | Recover exact authorized receipt; no extra review or second report |
| Over 1,024 demands, 4,096 retained commitments or 32 record revisions | Complete-or-unavailable response; never hide retained history to fit a list |
| Dependency/audit outage | Fixed unavailable state, no partial private output or success claim |
| Disputed correction | Explicit unresolved state, no automatic agreement or deletion |

## Handover, publication and manual fallback

A later handover shows exact work, checklist version and intended recipient.
Recipient acceptance uses their own account and current purpose. Changing content
or recipient produces a successor; no checkbox, timer, Shift completion or message
delivery implies acceptance. Pending acceptance uses the existing supervisor/manual
communication path. Sensitive exception narratives stay outside the checklist.

Scheduling owns personal timetable publication under SCH-012. Reporting or review
does not change a planned calendar, publish a public schedule or notify anyone.
Later publication/communication needs its own reviewed source, scope and explicit
action. Personal acknowledgement records receipt only, not agreement or verified
external delivery.

During an outage, use the organization's approved minimal manual record and
custody procedure. Mark occurrence time and actual observer/source distinctly
from later entry time. Record a temporary duplicate reference; no offline note
is authorization. Reconcile later using current scope/policy/source/version checks,
preserve conflicts and verify exact accepted outcomes before approved disposal.
Do not restart/reseed the preserved maintainer rehearsal to manufacture evidence.

Work facts are C2. Collection requires the organization's actual reviewed purpose,
owner, recipients, retention triggers, review date, subject rights, holds, export,
disposal and backup rules. An implementation must register every field and bind
policy versions; this contract chooses no legal basis or retention duration.
Exports preserve status, source and correction/dispute lineage under fresh
authorization. Restore the complete mutually consistent evidence graph; once
records exist, repair forward rather than editing or deleting history.

## Observable acceptance and human handoff

Use distinct synthetic people **Ari** (subject), **Bryn** (independent reviewer)
and **Cedar** (other person/denial), plus a second organization and edition.
Use fictional policy text explicitly labelled as a test fixture.

| Scenario | Automated evidence required | Human/operational evidence still required |
| --- | --- | --- |
| Completed plan without report | No generated attendance/interval; UI says unknown | Volunteer understands planned versus reported work |
| Report/review/correct/dispute | Exact immutable versions, separate actors, fixed codes, truthful receipt state | Subject/reviewer can explain a returned and disputed correction |
| Tenant/person/field denial | Each cross-scope and restricted-field path denies without leakage; audited reads fail closed | Representative roles understand available actions and limits |
| DST, breaks, bounds and overlap | Offset/gap/fold cases, contained breaks, 32/64 KiB limits, policy horizon, explicit overlap discrepancy | Operators confirm interval meaning for their real workflow |
| Concurrent decision/retry/source movement | Native locks, version conflicts, replay, rollback, no duplicate receipt or side effects | Recovery instructions remain understandable after ambiguous failure |
| Policy expiry and subject rights | New collection blocked; authorized retained access/correction and holds preserved | Actual organization owner accepts purpose, recipients and rules |
| Manual outage/reconciliation | Duplicate/source conflicts retained; no note grants authority or success | Representative owner rehearses custody, reconciliation and disposal |
| Restore/exit | Full source/record/review/dispute/audit graph, unused reverse or retained-use fence | Technical owner demonstrates representative recovery/PITR and exit |
| Personal/organizer UI | Empty, denied, returned, stale, unavailable and disputed states; keyboard, themes, named-zone time and narrow widths | Real 200% zoom, representative screen reader and owner acceptance |
| Progressive adoption | No Participation, Registration, payment, grant, calendar/publication or unrelated module row | Convention deliberately adopts the new purpose and accepts operating responsibility |

Implementation must update the maintained fictional demo and a reproducible role
walkthrough. Record actual passed, failed, blocked and deferred steps; preserve
the original #42 password/self-acceptance boundary and #23 specialist matrix.
Contract acceptance, documentation checks and protected merge do not complete
implementation, any human row above, deployment activation or production approval.
