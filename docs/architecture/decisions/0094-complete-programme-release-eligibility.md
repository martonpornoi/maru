# ADR 0094: Separate complete release eligibility from planning and publication

- Status: Accepted
- Date: 2026-09-11
- Extends: ADRs 0081, 0088, 0092 and 0093
- Requirements: SCH-004, SCH-007, SCH-010, SCH-012, PRG-008, HR-015,
  NFR-001, NFR-002, NFR-005, NFR-008, NFR-009 and NFR-013
- Issue: [#91](https://github.com/martonpornoi/maru/issues/91), child of #48

## Context

The dormant planning evaluator correctly declares only three conflict sources.
Its complete result does not evaluate staffing, rest, physical accessibility
fit or release readiness. Programme readiness and Workforce coverage are useful
separate owner projections, not permission to publish a candidate. A release
implementation must not turn this intentional partial planning boundary into
an accidental all-clear.

## Decision

### Require complete eligibility evidence before independent review

Scheduling owns the pure `scheduling.release-eligibility@1` policy. It requires
exactly one result for each category below. Its result means only that supplied
evidence is eligible for independent review. It is not an authorization token,
authenticated owner receipt, approval, artifact manifest or active release.

| Category | Required meaning of a satisfied complete source |
| --- | --- |
| Candidate | Exact current draft/immutable manifest, complete membership, supported policy/profile, current edition/day/occurrence versions and time bounds. |
| Programme readiness | Every placed item's complete current concern set is satisfied or explicitly inapplicable under Programme policy. |
| Public copy | Every public occurrence has a current independently approved rendition; working titles and private notes are never a fallback. |
| Hosts | Required current relationships, confirmations and deliberately shared availability cover exact selected presence. |
| Physical approval | Every placement has its exact current independently approved Venue binding; a draft hold is insufficient. |
| Physical constraints | Current availability, occupancy, configuration and all physical-member capacity constraints pass. |
| Accessibility fit | An explicit current fit decision binds delivery needs and the exact selected physical configuration; free text or a generic readiness tick cannot establish fit. |
| Staffing | Complete exact-source requirements/bindings and current confirmed suitable coverage; claims, stale bindings and accepted underfill are not full coverage. |
| Person conflicts | All selected host presence and relevant retained volunteer commitments are checked together without exposing unrelated calendars. |
| Rest | Applicable versioned Workforce break/rest rules pass for the affected commitments; host-presence overlap alone is not a rest check. |

Only hosts, staffing, person conflicts and rest permit `not_applicable`. The
future owner collector must prove applicability, not infer it from missing
rows or unavailable authority. Hosts require explicit Programme inapplicability;
staffing requires an explicit accountable no-staffing decision, not an empty
requirement list. Person/rest inapplicability requires a complete person-source
inventory showing no applicable obligation. Other categories remain mandatory.
An accessibility assessment may find no unmet need, but still has to run.

This decision does not invent a universal minimum-rest interval or an automated
accessibility judgment. The owner-specific accepted policy and exact evidence
must exist before their collector can emit success. Pending adapters remain
unavailable, so neither approval nor profile activation can proceed prematurely.
An empty initial timetable is not a public release. Deliberately withdrawing
every released occurrence requires the successor's separate reasoned withdrawal
command and impact evidence; an empty check collection is never that command.

### Bind all evidence to one exact snapshot

The future collector computes a canonical fingerprint containing the exact
organization/edition, profile code/version, candidate ID/revision/version,
manifest digest, eligibility policy, and complete sorted owner-dependency
identities, versions and minimized outcomes. A policy, scope, placement, public
copy, host, physical approval, staffing or applicable rule change requires a
new fingerprint. Do not hash only the three-source planning report or omit an
unavailable owner. No private calendars or free-text rationale enter persisted
Scheduling source evidence, logs or broad events.

The policy consumes immutable typed check, finding and acknowledgement tuples.
Digests are exactly 64 lower-case hexadecimal characters. Check count is bounded
by the ten-category vocabulary; findings and acknowledgements each by the
existing 10,000-finding bound. Unknown enums, duplicate categories/fingerprints,
mutable containers, generators, overflow, foreign-snapshot evidence and orphaned
acknowledgements fail with a stable content-free validation error. It never
truncates, deduplicates or coerces input into success.

Missing checks become unavailable. Explicit blocked, stale and unavailable
results remain distinguishable. Findings remain effective even if a category
incorrectly claims success. Only an exact current warning may have a retained
acknowledgement; blockers and unavailable findings cannot be acknowledged away.
Existing planning acknowledgements are historical evidence, not automatically
release acknowledgements. A successor collector must verify each receipt's
actor, authority, retained rationale and exact current release fingerprint.

Output is deterministic: categories use policy order and findings use digest
order. Sensitive result disclosure remains the caller's independent obligation.
The pure policy makes no query, write, event, external call or authority decision.

### Mandatory application-service successors

The next child must implement the owner collectors and persisted independent
approval; callers never submit these success flags through a browser or API.
Authorization precedes protected collection, each owner independently checks
field scope, and sensitive read evidence commits before disclosure. Complete
bounded collections are validated against their expected item/person/member
sets; filtering denied records out is not a complete result.

Approval binds the exact immutable source manifest and complete dependency
fingerprint. Its current verified approver must be independent of the retained
candidate and selected placement authors, including inherited placements copied
from other candidates. Copy/restore cannot launder authorship. Public-copy and
Venue approval retain their own independent decisions. The publisher must have
separate publication authority and be distinct from the timetable approver;
planner and publisher may be the same person when each action is authorized.

Publication prepares and verifies all mandatory minimized release artifacts
before changing one active-release pointer. Under canonical shared parent,
person, owner-aggregate and physical-member locks, it rechecks exact authority,
approval, applicability, sources, artifact digest and expected active release.
The release, supersession/impact evidence, active pointer, audit, registered
event and outbox commit atomically. Stale approval is refused; retries cannot
publish a different intent. Late failure leaves the prior release wholly active.
No network provider call is part of the database transaction.

The same successor must connect every accepted Venue mutation that can invalidate
released occupancy or approval to Scheduling's same-transaction boundary.
Concurrent cross-edition physical mutations must follow one checked complete
lock order, not acquire another edition opportunistically after holding shared
physical locks. If the complete affected closure cannot be locked and rechecked,
the mutation fails closed. It cannot silently invalidate a timetable and queue
repair for later. Existing live-source scope remains independently authorized.

Invalidation retains the immutable release and adds an exact reasoned safety
overlay, or activates an already approved safe successor, in the same transaction
as the physical change. Normal serving/export paths must check that overlay;
draft geometry and historical approved bytes never become a current safe fallback.
Revoked relationships and withdrawn public content likewise cannot leak through
retained release material. The owner-source implementation must specify and test
those current disclosure consequences rather than freeze permission at publication.

Already downloaded paper or a disconnected client cannot receive instant
revocation. The continuity child must visibly stamp version/freshness, bound
offline validity, provide controlled correction/withdrawal notices and require
operators to retire superseded copies. It must not promise remote erasure or
current safety while disconnected. Once invalidation is known, no normal newly
served or generated artifact may repeat the invalid approved-room claim.

### Delivery and activation boundaries

Issue #91 delivers only this contract and its pure executable rule matrix.
It introduces no migration, runtime grant, adapter registration, profile, HTTP
route, worker, approval record, release artifact or public output. Existing
planning evaluation, its deferred-check list and current profile fingerprints
remain unchanged.

The next children deliver owner collection and protected approval/publication/
invalidation, then shared release-derived outputs and change impact. Continuity,
guided surfaces and integrated acceptance remain separate mandatory #48 work.
Tests and future manual acceptance must distinguish each boundary. Genuine
human checks may be separately tracked but never recorded as completed merely
because the user authorized unattended development.

## Consequences

Every release category has an explicit failure and applicability meaning, and
the small rule matrix can be tested without a database. There is more source
integration work before publication, but no new alternate source of truth.
Existing planners retain their useful partial reports without a misleading
upgrade to approval. Nothing here authorizes production use or human data.

## Alternatives considered

- Use `is_complete` on the planning report: rejected because mandatory release
  categories are deliberately not evaluated there.
- Treat missing requirements or unavailable sources as inapplicable: rejected
  because partial disclosure and missing configuration are not positive evidence.
- Store a caller-supplied `ready` flag: rejected because owner facts and current
  authority must be resolved and rechecked by protected application services.
- Let warning acknowledgement bypass every failure: rejected because consent,
  authorization and hard physical constraints cannot become optional warnings.
- Publish now and invalidate asynchronously: rejected because it creates an
  interval where known-unsafe placement remains advertised as approved.

## Requirements affected

SCH-012 now explicitly separates complete eligibility, independent approval and
atomic publication. SCH-004/SCH-007 retain immutable review and exact warning
evidence. SCH-010, PRG-008, HR-015 and NFR-013 retain owner/field boundaries and
purpose-bounded adoption. NFR-001, NFR-002, NFR-005, NFR-008 and NFR-009 require
tested finite contracts, honest continuity limits and complete recovery evidence.
