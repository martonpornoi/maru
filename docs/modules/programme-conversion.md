# Accepted Programme conversion

Status: implemented dormant command boundary; no profile, UI, API, or runtime writer

Last updated: 2026-09-06

## Outcome and ownership

Under PRG-008 and [ADR 0086](../architecture/decisions/0086-source-bound-programme-accepted-item-conversion.md),
an operator can explicitly turn one effectively accepted, exact submitted
proposal revision into one private Programme item. Review-side acceptance
alone does not perform this conversion. The workflow remains available only
inside the sealed synthetic future-profile test harness.

Applications owns `convert_accepted_programme_proposal`, its closed
`ProgrammeConversionInput`, and the immutable `ProgrammeAcceptedTransition`.
Programme owns `create_accepted_programme_item`, the item, its source binding,
private working revision, initial readiness, and creation receipt. Neither
owner writes the other's models. Applications orchestrates the two public
command/query boundaries in one database transaction.

The input names the exact accepted decision and sealed revision, expected
review-case and Programme edition-control versions, and deliberately supplied
private title and summary. There is no implicit latest decision, answer-sheet
copy, source-system lookup, import match, or automatic public content.

## Authority and freshness

Fresh work requires all of the following independently:

- an active verified person in the exact organization and edition;
- `applications.convert_programme_acceptance` on the current exact owning
  Department, without ancestor inheritance or delegation;
- `programme.manage_items` on the exact edition;
- both exact adapter pins: `applications.target.programme_item@1` and
  `programme.accepted-application-source@1`;
- open private planning, the current submitted and sealed revision, an exact
  accepted decision, current review-case version, and still-effective
  independent scoring and moderation for every required stage;
- the expected Programme edition-control version and remaining item capacity.

Authorization precedes private source lookup and is repeated under the shared
retirement-safe edition lock chain. Withdrawal, reopening, recusal, ownership
changes, and conversion use that same serialization boundary. The internal
Applications source query requires an existing transaction, re-resolves its
own source, and returns identifiers and versions only. Passing a DTO or an
unverified UUID is not source authority.

The current `full_convention@1` and `workforce_only@1` manifests remain
unchanged and deny this workflow. The generic Applications `programme_item`
review/target adapter and discovery seams remain closed. No root capability
grant or production test-authorizer setting is introduced.

## Atomic result and retries

The result comprises one Applications transition, one Programme item of kind
`accepted_proposal` and provenance `applications_accepted`, a reciprocal
source binding at version 1, and one private working revision. The item starts
at version 1 and advances only the Programme edition-control creation cursor.
It does not advance the proposal or review cursor.

All seven readiness concerns start as `required`, each with its immutable
initial requirement revision and no satisfying evidence: public copy, host
confirmation, technical needs, accessibility delivery, media consent, schedule
availability, and required files. Public-copy dependency version is 1; the
other source dependencies are initially unavailable at version 0. Being
accepted is not being ready, scheduled, staffed, or public.

Both owners retain actor, reason, request correlation, command receipt,
minimized audit, domain event, and outbox evidence. Reciprocal deferred foreign
keys and database guards reject a committed half-conversion. Any failure rolls
back the complete success; the best-effort failure audit omits source/result
identifiers and private input values.

The actor/edition/retry key shares the existing Applications namespace. An
exact normalized retry returns only retained creation identifiers and
versions, even after later recusal, source changes, or Department retirement.
It still requires current identity, tenant scope, and both adapter pins. It
does not grant current content access. A changed intent conflicts, and a new
retry key cannot convert the same revision again. The stored version is not a
claim about the current Programme item.

Later source changes preserve the conversion as history; they do not silently
rewrite or erase independent Programme work. Host relationships, availability,
Scheduling, Venue approval, Shifts, public renditions and timetable release
remain separate governed work. No account, membership, Participation,
Registration, payment, attendance, or unrelated relationship is created.

## Evidence, privacy, and recovery

`applications.programme_conversion.completed.v1` carries only `transition_id`
and `programme_item_id`. Programme's existing item event adds the closed
`accept_application_item` action. Neither event discloses proposal answers,
review details, private working text, or contributor identity. Existing
`applications-programme-restricted` and `programme-restricted` retention
purposes apply; this is accountable proposal planning, not activity analytics.
No new production-data use or erasure process is authorized.

See the [conversion migration and recovery guide](../operations/programme-conversion-migration-and-recovery.md).
The source table remains runtime `SELECT`-only; owner-only guards, complete
readiness fingerprints, empty reversal and populated downgrade fences are
part of this boundary, not future profile activation.
