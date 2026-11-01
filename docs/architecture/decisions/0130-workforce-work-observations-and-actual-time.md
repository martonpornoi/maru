# ADR 0130: Separate Workforce work observations from planned completion

- Status: Accepted contract; implementation and activation remain future work
- Date: 2026-10-31
- Extends: ADRs 0078 and 0080; preserves their implemented lifecycle and profiles
- Requirements: HR-009, HR-018, SCH-012, PRI-001 through PRI-004, AUD-001,
  NFR-001, NFR-002, NFR-004 through NFR-009, and NFR-013
- Issue: #24

## Context

The implemented `complete_shift_demand` command closes ended locked demand and
its confirmed commitments atomically. Its completion time records the command,
not a person's arrival, departure, breaks or worked interval. The current
handover field is an instruction, not another person's acceptance. Reusing those
fields as attendance would invent evidence and alter existing history.

The maintainer authorized progressing the next tasks through their automated
boundary, including issues with later manual validation. This decision resolves
the engineering contract for #24. It does not accept a convention's operating or
retention policy, collect real work records or activate dormant Programme routes.

## Decision

### Preserve separate owners and independent facts

Workforce owns a future Work record against one immutable retained commitment
in one organization and edition. The subject is the commitment's actual person;
neither caller input nor a display label can select another identity. It retains
the accepted demand/commitment source versions and original planned UTC interval,
edition IANA zone, and offset-bearing display. Later source changes never replace
that snapshot or transfer a record to a successor commitment.

Keep these facts independent:

| Fact | Meaning | It does not establish |
| --- | --- | --- |
| Planned completion | Existing HR-009 closeout decision | Attendance or worked hours |
| Check-in/out observation | A self-reported or operator-recorded occurrence | Independent verification or complete work |
| Cannot-attend report | The person's fixed operational report | A private reason or removal from the plan |
| Not-observed declaration | An authorized operator's explicit observation | Proof of deliberate absence or misconduct |
| Actual intervals and breaks | A versioned report of when work occurred | Payroll, entitlement or verified hours |
| Verification | A different authorized reviewer's decision on one report | The subject's agreement or handover acceptance |
| Correction/dispute | A retained successor or challenge to an exact report | Silent erasure or an automatic winner |
| Handover acceptance | The named recipient accepts an exact checklist version | Shift completion or schedule publication |

Observation state starts as **Unknown**. Lack of a device event, report or network
connection must remain unknown. Lateness is an explicit declaration against a
recorded reviewed policy version, never a background timer or public label. Do
not infer whereabouts or discipline. A person may report **Cannot attend** without
a cause; organizer removal still uses its existing separately authorized command.

Every observation retains an aware `occurred_at`, server `recorded_at`, actual
authenticated author and closed source kind: self, operator or later manual
entry. Backdated input is labelled as reported occurrence, never server-observed
presence. Named local times reject DST gaps/ambiguity; API instants have explicit
offsets. Late entry is bounded by the edition's recorded policy and review state.

### Admit collection through a deliberate new contract

Existing `workforce_only@1`, RoleBundles and Shift capabilities do not acquire
new behavior because these records belong to Workforce. An implementation must
review a new exact-version adoption/expansion manifest and dedicated read,
self-report, operator-observation, review and handover permissions. None are
registered, granted or pinned by this documentation change. A visible link,
Assignment, check-in or reported work never grants another permission.

The actual verified person needs current exact-self retained-work purpose.
Retained purpose may outlive an Assignment's end so truthful history remains
inspectable; it must not authorize a new Shift or another person's record.
Organizer reads and decisions need independent exact-edition and, when relevant,
Department/Position scope plus complete permitted fields. Read does not imply
write; review does not imply source editing. Denial precedes private inputs and
identifying labels. All response boundaries reauthorize and audit before release.

Before collection, the organization must record its actual purpose, policy owner,
review date, permitted recipients and applicable retention/disposal/hold rules.
These are deployment-owned facts, not invented legal approval or a code-chosen
duration. A missing or expired collection policy blocks new collection while
retained subject access, correction and lawful hold handling remain available.
Implementation must version the governing policy and bind each submitted record.

### Report actual work before adding live attendance

The first persisted implementation slice is an exact-self actual-time report
for an ended locked or completed demand with retained confirmed/completed
commitment provenance. Removal or cancellation does not establish eligible work
for this slice. Unexpected work requires a later separately accepted exception
contract, not manufacturing confirmation. Do not require reopening completed
planning, a current Availability window or an unrelated Registration record.

The subject deliberately submits the complete interval set. A report has at most
32 nonoverlapping positive work intervals and 32 nonoverlapping positive break
intervals, with every break contained in exactly one work interval. Store explicit
UTC instants and preserve the named zone; do not subtract a planned break or
round to a payroll unit. Gross, break and net durations are derived and labelled
as reported. Per-record input has a 64 KiB ceiling. The recorded edition policy
must bound the admissible operational horizon and late-entry window; there is
no unbounded default. Cross-record overlap is a review discrepancy and must not
erase a truthful report or rewrite planned overlap/rest protection.

The subject's submission and a different eligible reviewer's verification are
separate immutable decisions. **Return for correction** uses a closed reason
code such as interval, break, source or overlap discrepancy, not an absence
narrative. The subject submits a new version; the first report remains retained.
A reviewer cannot submit as the subject, review their own report or cause an
unacknowledged correction to look agreed. A correction proposal binds its source
version, changed fields and independently reviewable rationale. Its effective
state, the subject's acknowledgement and any dispute remain explicit. A dispute
keeps the original and successor visible with fixed operational codes; settlement
requires a separately authorized recorded decision, never last-write-wins.

The implementation must set explicit complete query bounds (initially 1,024
demands, 4,096 retained commitments and 32 revisions per record), fail unavailable
on overflow and never discard older revisions to satisfy a display ceiling.
This first slice excludes live check-in/out, lateness declarations, handover
storage, bulk/offline import, notifications and new personal publication. Their
contracts below guide later separately reviewed increments.

### Make handover and degraded operation accountable

A future handover binds exact work references, a bounded versioned operational
checklist, current author and one named recipient with genuine current purpose.
Do not use a general account directory or copy medical, safeguarding, HR or
private absence notes. The recipient accepts or returns that exact version in
their own session. Editing invalidates earlier acceptance for the changed version;
reassignment is an explicit successor. A missing recipient, outage or deadline
does not imply acceptance. Record a pending handover and use the established
supervisor/manual communication path; real emergency procedures remain external.

First-slice degraded operation is a minimized paper/manual record held under the
organization's approved custody rules. It retains the work reference, occurrence
instants, observer/source and temporary local duplicate reference. It is neither
an offline credential nor trusted proof. Re-entry later repeats current authority,
scope, source-version, duplicate and policy checks; conflicting entries remain
unresolved. One canonical retry identity recovers the exact accepted outcome after
an ambiguous response. Technical failure must not create a second report, hide a
dispute or claim that a saved note reached Maru. Retain the manual fallback until
reconciliation and approved disposal are confirmed.

### Keep personal publication and communication separate

Scheduling continues to own SCH-012 personal timetable composition. Reporting,
verification, late entry or handover never publishes a public calendar, changes
planned times or sends a message. Any later personal work-history contribution
needs its owner's exact-self proof, bounded minimized fields and explicit source
versions. An affected person must see the material operational correction and
its acknowledgement status; acknowledgement is not agreement or delivery to an
external channel. Notification delivery, subscriptions and public publication
require their own accepted contract and independently adopted purpose.

### Protect evidence, privacy and recovery

Use closed inputs, canonical identifiers, expected versions and caller-owned
idempotency. Require current authority even for replay; changed intent with the
same key conflicts. Resolve canonical scope and person/commitment locks before
the final in-transaction source check. The new Work record aggregate advances
once, atomically with minimized immutable receipts, registered domain events,
audit and outbox evidence. It never changes the existing Shift aggregate as a
side effect. Native constraints must fence scope/subject drift, history edits,
forged actor/source, missing receipts, invalid transitions and destructive removal.

No personal input text, instants, labels or work durations belong in generic
events, logs, analytics or a global search index. Subject output shows their own
reported/verified/corrected/disputed state and operational consequences, excluding
other people and private organizer rationale. Operator output has a separate
fixed field ceiling and mandatory sensitive-read audit. Exports require current
purpose/field authorization and repeat the report's status, provenance, correction
chain and policy version; a rota snapshot is not a complete Work record export.

The field inventory must classify work facts as C2 and keep private exceptional
case material outside this model. Bind source, recipients, active-use/retention
triggers, holds, subject rights, permitted export, disposal and backup propagation
to actual reviewed organizational policy. No new retention executor or automatic
deletion is implied. Complete-graph restore must retain record/source/receipt/
decision/dispute/audit consistency; once evidence exists use fix-forward recovery
or an approved complete earlier restore, never a partial history rewrite.

## Acceptance and consequences

The [page and journey contract](../../product/page-contracts/workforce-work-records.md)
defines actor/state scenarios and the first slice's observable acceptance.
Implementation needs unit, PostgreSQL concurrency/migration/recovery, restricted
runtime, browser and separately recorded human/owner evidence. The policy owner,
representative volunteer and reviewer must validate operational meaning and
accessibility before adoption. No green test, accepted ADR or document merge
completes that validation.

Existing Shift behavior, API schemas, grants, profile meanings, data and ongoing
fictional demos are unchanged. Later interfaces must extend the maintained demos
with distinct synthetic subject/reviewer accounts and truthful policy setup.
Payroll, surveillance, geolocation, biometric identification, performance ranking,
automatic discipline/benefits, attendee Participation and payment remain excluded.
