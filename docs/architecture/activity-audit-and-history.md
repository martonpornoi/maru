# Activity, audit, and history

Status: Initial registration and record-history projections implemented;
dormant Applications Programme facts have no mounted timeline
Last updated: 2026-09-11

“Track user activity” has three legitimate meanings in Maru. Combining them
would create a surveillance system, an unusable audit log, and poor historical
records.

## Three separate products

| Stream | Purpose | Typical audience | Examples |
| --- | --- | --- | --- |
| Security and administrative audit | accountability, investigation, control evidence | authorized security, privacy, audit, and subject views | sign-in, grant, sensitive read, export, privileged mutation |
| Operational timeline | explain work and decisions | subject and authorized workflow participants | application submitted, payment reconciled, shift assigned, schedule changed |
| Engagement measurement | improve services with proportionate evidence | authorized product/event analysts | aggregate feature use, programme interest, queue observation |

An event may produce entries in more than one stream, but each entry has its own
schema, visibility, purpose, and retention. Audit is not the product history.
Analytics is never reconstructed from privileged audit.

Where a privileged mutation requires independent approval, the actor and
approver exercise authority separately and therefore receive separate,
correlated audit events. A command must not collapse them into one synthetic
principal. Access removal may be intentionally single-control when waiting for
approval would prolong exposure; the capability definition and audit
obligations make that distinction explicit.

## Domain event versus audit event

A domain event states a business fact:

```text
workforce.shift_commitment.accepted.v1
```

An audit event states that a principal exercised access or authority:

```text
workforce.shift_commitment.change AUDIT allow
```

The first may drive projections and the user's timeline. The second proves
control use and includes the evaluated capability and result. Their identifiers
and correlation link them without duplicating sensitive payload.

## Audit event

Minimum fields:

- event identifier and schema version;
- trusted server timestamp;
- principal kind and opaque identifier;
- authenticated session/workload/device identifier;
- organization, edition, and resource scope;
- capability and safe operation;
- target type and opaque identifier or bounded target-set digest;
- allow/deny and policy reason code;
- obligations such as approval, step-up, or reason;
- safe changed-field names and before/after digests where appropriate;
- request, correlation, causation, and idempotency identifiers;
- source channel and coarse network/device risk context;
- delegated/elevated/break-glass context;
- outcome and safe error code; and
- retention and integrity batch.

Audit does not record secrets, form contents, message bodies, medical detail,
raw search text, or an entire before/after object by default.

### Same-transaction native mutation attribution

`audit.mutation_evidence.audited_mutation` is an internal replacement for an
owner's existing successful `append_audit` call when a required derived owner
must join that same mutation. It appends exactly one native event, inside the
already active owner transaction and a nested atomic scope. It lends a frozen,
minimized reference to that exact append; it does not issue human authority or
authenticate an arbitrary caller-selected target.

The consumer first calls `require_audited_mutation`, then validates its closed
native-operation, changed-field and target contract through the source owner's
documented seam. Evidence must be the exact live object on the same thread and
database connection, with a retained audit row and a usable atomic transaction.
Copied/reconstructed objects, old audit identifiers, expired copied contexts and
rolled-back evidence cannot substitute. An inner mutation temporarily supersedes
the outer lease. Exiting the scope revokes it even if the outer transaction stays
open. A required derived-join failure must propagate through the native owner
transaction; catching it and committing the earlier mutation is not supported.

The proposed Audit migration adds `AuditNativeMutationWitness`, not a field to
historical audit rows. The owner scope reserves one new audit UUID and sets a
transaction-local capture selector for that exact insert. A narrowly scoped
`SECURITY DEFINER` AFTER INSERT trigger captures the witness only on the actual
Audit relation; transplanting it onto another table is rejected. Witness writes
are database-owned and immutable. A selector alone cannot capture an old audit
or grant authority; direct witness inserts fail the native trigger guard.
Ordinary audit appends create no witness state.

The internal stamp hashes the full top-level `xid8`, backend PID and server-start
epoch, so savepoints share the actual native transaction without casting a row's
32-bit `xmin`. Server/session context prevents treating copied transaction
counters as portable provenance. It requires no elevated statistics/control-file
access. It adds no activity tracking or audience, and is not included in public
audit summaries, the historical semantic audit digest or long-term authority.
Existing audit rows, table shape, unrelated append callers and sealed digests
remain unchanged.

Application verification also compares the witness stamp with the current
transaction and requires the actual successful audit row. A restore must finish
and commit before ordinary commands
or activation resume; inserting restored historical rows in a maintenance
transaction cannot authorize work in a later runtime transaction. Real restore,
runtime SELECT-only witness grants and exact readiness remain pending
verification in #96. The trigger guard is not a substitute for runtime privilege
containment: a database owner can alter protected definitions and is not a
runtime acceptance role. Populated witness reversal is fenced for fix-forward
recovery before any trigger or table is removed.

This attribution is not a database privilege, source freshness or release-safety
proof. Those remain separate owner integration and database guard requirements
in proposed [ADR 0096](decisions/0096-atomic-programme-release-and-invalidation.md).
No current source command uses the new lease and no release is enabled yet.

## Events requiring audit

- authentication, recovery, session, MFA, and account link changes;
- organization membership, role, capability, delegation, and elevation;
- sensitive or restricted reads;
- person lookup using protected identifiers where justified;
- bulk query and export of C2/C3 data;
- financial, eligibility, allocation, credential, custody, bid, and archive
  overrides;
- safety-case assignment, access, break glass, and evidence movement;
- emergency or mass communication;
- schedule release, supersession, and emergency change;
- integration install, credential, scope, replay, and disconnect;
- automation activation, high-impact run, pause, and permission ceiling;
- retention policy, legal hold, deletion, restore, and archive amendment;
- support diagnostic/elevated access; and
- audit query or export.

Ordinary viewing of a public schedule does not create a permanent
person-associated audit record.

## Operational timeline

A timeline item is an audience-specific rendition of a domain fact. It answers:

- what changed;
- when and in which edition time zone;
- current consequence;
- actor or responsible team if appropriate;
- reason or linked decision when visible;
- affected next action; and
- whether it was corrected or superseded.

Examples:

- The attendee sees “Refund requested” and later “Refund confirmed.”
- Finance sees provider reference and reconciliation state.
- The payment provider payload remains in a restricted diagnostic record.

Modules publish timeline projectors for:

- the data subject;
- assigned staff;
- department operations;
- cross-department dependency; and
- archive.

There is no universal timeline that makes every fact visible to every staff
member.

Programme-call activation, proposal invitation, sealing, acknowledgement,
reopening, submission, and withdrawal are registered dormant domain facts but
do not create a mounted operational timeline in issue #63. Future renditions
must remain audience-specific: a contributor may see their own invitation,
included snapshot, and response; the lead may see aggregate acknowledgement
state; neither may infer another proposal, private profile, review, decision,
Programme item, or host relationship. Audit remains separate control evidence
and contains no proposal values.

Call-owner reassignment, Active-call retirement, import-batch reassignment,
explicit disposal, and exact-ID orphan recovery are also registered dormant
facts. Their operational rendition may name the action, exact aggregate,
source/destination ownership references, resulting version, actor, time, and
directly inspectable reason only to a future authorized audience. The audit and
event envelopes stay minimized and never copy a Department name, dependency
kind/count, source key, email, answer, payload, identity-match state, or digest.
No current timeline, route, or profile exposes these facts. A refused
Department retirement creates neither a successful Applications fact nor a
Workforce structure-history entry.

The first executable projection is the registration timeline. Submission,
confirmation/payment reconciliation, entitlement consequence, and check-in
produce attendee and purpose-limited staff renditions. Form answers remain in
the exact submission snapshot and are not copied into the general timeline.

Convention series record and Event edition record add the first controlled-shell record histories. They project a
bounded allowlist of convention-series and edition domain facts, safe actor
display labels, changed-field labels, and edition/organization-local time. They
do not copy entered values, email, raw actor identifiers, source channel, or
security-policy detail. This aggregate history does not complete the later
cross-domain, department/resource-aware Activity workspace.

## User-visible account history

`My Maru / Security` includes:

- successful and failed sign-in patterns at a safe level;
- new authenticator, linked identity, or recovery method;
- active and recently revoked sessions;
- account merge/split or contact verification;
- organizer/application installation consent;
- account export or deletion request;
- important public-profile or communication-preference change; and
- an action to report unfamiliar activity.

Location is coarse and privacy-preserving. Raw IP and user agent are retained
only under their security policy.

The bootstrap implementation records successful sign-in and sign-out events
and exposes only the signed-in account's minimized history at
`/api/v1/me/security-history`. MFA, recovery, linked identity, session
inventory, and unfamiliar-activity reporting remain future identity work.

## Participation history

The personal archive is a curated domain projection:

- editions attended;
- attendee/supporter or configured level as it existed;
- accepted and delivered hosting contributions;
- completed volunteer assignments and approved recognition;
- staff positions and departments;
- dealer, artist, performer, guest, charity, or other capacities; and
- optional certificates or public profile.

Disputed completion has a correction process. Managers cannot use hidden
behavioral telemetry to create a permanent “good/bad volunteer” score.

## Engagement measurement

Before adding a measure, document:

- decision it will improve;
- minimum signal and whether aggregate data is sufficient;
- user expectation and notice;
- subject identity or pseudonymization requirement;
- lawful basis/consent behavior;
- cohort threshold;
- owner, access, and retention;
- known bias and misuse; and
- deletion/disable verification.

Preferred event metrics derive from operational facts already needed—capacity,
completed check-ins, service demand, or schedule state—rather than cross-page
tracking.

Prohibited by default:

- third-party advertising trackers;
- cross-organizer behavioral profiles;
- message-content analysis for staff performance;
- hidden live-location histories;
- attendance inference from unrelated scans;
- emotion, protected-trait, misconduct, or loyalty inference; and
- public or managerial leaderboards that punish people for accommodations,
  breaks, role type, or incomplete data.

## Integrity

Audit events are append-only through application interfaces. Infrastructure
uses:

- a restricted write path and separate read capability;
- immutable event identifiers and sequence within integrity batches;
- regular canonical batch digest;
- signed or independently stored integrity checkpoints;
- database and object backup;
- alert on gaps, late events, mutation, checkpoint mismatch, or disabled
  collection; and
- periodic verified export.

Hash chaining provides tamper evidence, not magical prevention. Database,
deployment, key, and human access controls remain necessary.

## Corrections and redaction

- An inaccurate operational fact is corrected by a new domain action linked to
  the original.
- An audit event is not edited; a review annotation may explain it.
- A message or timeline item may be redacted from an audience with a visible
  tombstone while restricted evidence follows its policy.
- A subject-rights action may remove personal payload and retain a minimized
  control receipt.
- Restoring a backup must reapply completed erasure and restriction work.

## Access and use

Audit search is itself audited. Default views use metadata and reason codes;
opening protected detail requires explicit capability and, for some classes,
reason or approval.

Audit data cannot be exported as a general staff activity report. HR
investigation, security response, subject rights, and platform troubleshooting
use distinct purpose-specific projections and procedures.

## Verification

- schema tests reject classified payload fields;
- domain action and audit correlation tests;
- sensitive read and denied-access coverage;
- timeline audience snapshot tests;
- user security-history tests;
- integrity gap and checkpoint-mismatch tests;
- retention and subject-rights tests;
- high-volume partition/query performance tests; and
- analytics-disabled and small-cohort suppression tests.
