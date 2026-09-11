# ADR 0095: Collect release evidence through exact owner boundaries

- Status: Accepted
- Date: 2026-09-11
- Extends: ADRs 0081, 0087, 0088, 0093 and 0094
- Requirements: SCH-001, SCH-003, SCH-007, SCH-010, SCH-012, PRG-008,
  HR-009, HR-014, HR-015, AUD-001 and NFR-001/002/005/008/009/013
- Issue: [#94](https://github.com/martonpornoi/maru/issues/94), child of #48

## Context

ADR 0094 provides a complete pure rule matrix, not authenticated evidence.
Existing planning sources intentionally omit some release checks. Programme's
generic readiness evidence does not bind accessibility needs to a placement;
an empty staffing inventory does not express an accountable no-staffing decision.
The current public-rendition curation command also permits the working-copy
author to record a rendition. That retained decision alone does not establish
independent release approval.

## Decision

### Separate owner decisions from collected source evidence

Programme owns two closed, append-only placement decision kinds:
`accessibility_fit` and `staffing_not_required`. Each records the exact item,
occurrence, immutable placement, selected candidate revision as provenance,
source fingerprint, sequence, decision state, item command version, actor,
reason and time. States are `satisfied`, `blocked` and `withdrawn`. An explicit
withdrawal retains earlier decisions; a missing decision is unavailable.

Accessibility fit requires Programme delivery-management authority, independent
read authority for the delivery layer and selected Venue configuration, and
Scheduling authority for the exact selected placement. Its dependency proof
contains the current explicit delivery revision, selected physical configuration
and complete physical members, relevant access facts and exact placement
envelope. Empty declared needs may be assessed, but absence of the declaration
is not an assessment. No algorithm infers accessibility suitability from prose;
the authorized owner records the bounded accountable decision.

No-staffing requires Programme staffing-management authority and complete
independent staffing-source disclosure. It can establish inapplicability only
when no active requirement or still-operative bound Workforce demand remains.
Retiring a Programme requirement does not cancel accepted volunteer work. The
fingerprint includes the complete retained requirement/binding dependency set
and exact placement; changed source evidence requires a fresh decision.

Decisions are versioned independently for each placement and kind. A copied
candidate may reuse a decision for the identical retained placement only when
every owner dependency still matches. New geometry, delivery needs, physical
configuration or staffing sources cannot inherit a success by resemblance.
The candidate revision retained with the original decision is provenance, not
permission to disclose or publish another candidate.

Commands normalize closed typed intent after admission, compare an owner-
recomputed source fingerprint and exact optimistic versions, and retain their
receipt, current item version, audit, event and outbox atomically. Their own
placement/kind event sequence advances; the Programme item version does not.
These operational decisions may be made in Draft, Preparing, Ready or Live
without reopening private content-planning commands in Ready or Live. Guarded runtime
containment, raw-DML coherence, source foreign keys, bounded contiguous history
and populated downgrade fences remain mandatory. Private reasons never enter
the minimized release preflight or broad events.

### Collect one exact complete snapshot

Scheduling resolves and authorizes one current retained candidate and its exact
manifest under the shared canonical parent scope. Each source independently
checks its own capability, field ceiling and exact pinned adapter. Discovery
never filters unauthorized objects out and calls the remainder complete.
Complete bounded immutable source results are required for all ten ADR 0094
categories. Their identities, versions and minimized outcomes, the complete
candidate membership, edition/profile/policy versions and retained exact
warning evidence determine the release fingerprint. This source-only child
accepts no acknowledgement input: all warnings remain unacknowledged until the
successor supplies authenticated retained release-warning evidence. Existing
planning acknowledgements cannot be promoted to release acknowledgements.

Programme supplies current item/readiness and approved-copy consequences, exact
selected hosting dependencies, and its placement decisions. Public copy must
refer to the current working revision and have a reviewer distinct from its
retained working-copy authors. The reviewer must also remain active and verified
for current release eligibility; inactive/unverified review is unavailable, not
rewritten history. An author becoming inactive does not erase their
authorship. Old curation records remain immutable; a new qualifying independent
rendition can supply release evidence without rewriting them. No private title,
answer, discussion or delivery text becomes a public fallback.

Venues supplies current exact independent booking approval and complete physical
constraints/configuration facts. Workforce supplies exact source-bound current
coverage and combined-person consequences. Claimed work is not confirmed
coverage; stale bindings and accepted underfill remain failures. Source states
retain blocked, stale, withheld and unavailable distinctions. An absent category
never becomes successful because the rest of the preflight ran.

Preflight data is minimized, audited before disclosure and freshly authorized
under the composition boundary. Existing broad planning and coverage contracts
are not widened implicitly. Private owner inputs are ephemeral; persisted
Scheduling evidence contains only explicit minimized dependency allowlists and
digests. A digest is neither authentication nor permission. Caller identity,
correlation, audit records and caller-only person locks are excluded from the
dependency fingerprint; changing authorized workflow roles alone does not stale
the evidence. Relevant owner identities remain dependencies inside their owner.

The complete person union is resolved before narrower person-locking reads;
failure to establish it aborts collection. Programme and Workforce authority is
rechecked at the final composition boundary. Current Venue sources are re-read
and compared before disclosure because catalog writers do not all share the
edition mutex. This uses owner projections, not an inverted physical-row lock.
It remains a point-in-time preflight, not publication's required atomic closure.

### Preserve combined person and rest protection

Selected host presence and relevant retained volunteer commitments use the
existing edition-bounded Identity conflict key. Workforce owns its retained
commitment/rest semantics and checks claimed and confirmed obligations, including
cross-edition conflicts already protected by its claim/confirmation commands.
It does not disclose foreign scope identifiers, people, titles, calendar entries
or private reasons through the release source. The output identifies only the
selected Programme obligation and its conflict/rest consequence.

Intervals are half-open. A commitment's retained post-work rest endpoint cannot
be shortened by a new candidate. No universal new rest duration, inferred host
consent or automatic volunteer reassignment is introduced. Source completeness,
membership and bounds are explicit; partial or missing person evidence cannot
prove inapplicability. Canonical parent, person and owner lock order remains the
ADR 0093 order. Owner rechecks must not take a foreign edition opportunistically
after a narrower person or physical lock.

### Delivery boundary

#94 delivers trusted source collection and the missing owner evidence. This
implementation split refines the next-child sequencing in ADR 0094 without
changing its mandatory approval/publication contract. The following child must
persist independent approval and connect atomic publication and all required
same-transaction safety/disclosure invalidations. A preflight snapshot is not
a persisted approval token or a release. Publication must collect/recheck the
sources under its own locks, not trust an earlier successful response.

No current adoption profile, route, runtime writer, release artifact or worker
is activated. #92's integrated human acceptance, continuity, guided setup and
the rest of #48 remain mandatory successors. Synthetic evidence is not a
physical accessibility assessment of a real venue or production acceptance.

## Consequences

Release decisions have independently inspectable owners and exact dependencies.
Some otherwise complete drafts will need new explicit assessments or a separate
public-copy reviewer. That is visible missing evidence, not automatic approval
or a request to duplicate private calendars. Source integration is more work
than using the planning report, but preserves its honest partial scope.

## Alternatives considered

- Accept operator-supplied release flags: rejected because they bypass owners.
- Treat missing staffing or a generic accessibility note as success: rejected
  because neither is exact positive evidence.
- Rewrite old self-reviewed copy: rejected because history remains truthful and
  a new independent rendition can provide the missing release evidence.
- Copy complete calendars into Scheduling: rejected because minimized conflict
  consequences suffice and independent disclosure boundaries must survive.
- Let preflight success authorize publication: rejected because dependencies,
  authority and required artifacts can change before the publication transaction.
