# Activity, audit, and history

Status: Initial registration and record-history projections implemented
Last updated: 2026-08-01

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
