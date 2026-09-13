# ADR 0101: Exact-purpose release change comparisons

- Status: Accepted
- Date: 2026-09-13
- Issue: [#104](https://github.com/martonpornoi/maru/issues/104)

## Context

ADR 0097 admits exact-person approved hosting, not arbitrary planner history.
ADR 0099 admits independently scoped operator output, not a recipient directory.
A new placement reference can change required host presence without changing
effective delivery times. Conversely, a room or copy change need not change
retained Workforce work. A whole-release comparison cannot stand in for any
of these independently authorized purposes.

## Decision

Compare exact canonical publication selections by stable occurrence identity.
Planner/history comparison requires both history and release-manifest fields.
It distinguishes membership, reference changes and actual immutable geometry.
An explicit historical release selects its own retained predecessor; callers
cannot fabricate a baseline or substitute a private candidate.

An exact-person hosting comparison instead uses real Scheduling host-self and
Programme host-self authority. Only currently confirmed own relationships permit
release lookup. The query compares the active publication with its retained
immediate predecessor, never an arbitrary caller-selected historical release.
Each side independently selects only approved presence for those exact own
relationships and verifies occurrence-to-item membership. Pending or ended
relationships do not confer historical schedule access. No confirmed purpose
means no release lookup or release-existence disclosure.

Stable comparison identity is the pair of host relationship and occurrence.
Addition/removal of own presence is separate from addition/removal of an event.
Required own start/end, surrounding phase geometry, service-day bounds, exact
room and selected reviewed-copy references are compared independently. No other
host, private copy, availability, contact, planner rationale or Shift is returned.
Current relationship version and invitation sequence remain distinct from the
immutable publication and placement identities. A copy-reference change is not
permission to display either text or claim which words changed.

Every side uses complete bounded native manifest verification and current
withdrawal/invalidation consequences. Suppressed comparison is explicit, never
an empty successful comparison, invented mass cancellation or last-good fallback.
An available first publication has actual additions from an absent predecessor.
The complete union can be twice the per-side limit; it must not be truncated.
Canonical parent ordering, independently repeated owner purposes and both
manifest observations precede final authorization and mandatory read audit.

This refines ADR 0097 only to permit this exact own-purpose predecessor
comparison. It grants no general history, communication, acknowledgement,
offline-freshness or work-mutation authority. No profile, route or writer grant
is activated. Workforce recipients require their own owner-bound comparison;
filtering planner or hosting output does not implement it.

An operator comparison independently admits the exact room, Department or edition
through ADR 0099's Scheduling geometry and owner scope-link authorities. Current
Venue responsibility and, only when adopted, complete retained Workforce binding
lineage determine membership on each side separately. It compares the active
release and its retained predecessor, with no arbitrary-history selector. An
occurrence leaving a room/Department appears as leaving that purpose: the response
does not imply global cancellation or disclose its now-unadmitted destination.
Both-side geometry and copy-reference differences are exposed only when both
sides remain in the current purpose. Current membership versions accompany the
immutable geometry; they confer no contact, personnel or private-content access.
Owner links, adoption, both native manifests and authority are repeated before
mandatory audit and disclosure, including for an empty or suppressed result.
This extends ADR 0099 only for this bounded predecessor comparison.

## Consequences

- Hosts can distinguish a change to their required presence from a changed
  public timetable without receiving other people's assignments.
- Revoked purpose or newly unsafe historical evidence can suppress comparison;
  an old notification must not restore that disclosure authority.
- Comparison is read evidence, not proof of delivery, acknowledgement, attendance,
  work acceptance or release approval. Governed communication and immutable
  exact-recipient acknowledgement remain separate implementation work in #104.
- PostgreSQL assertions are maintained but unexecuted under ADR 0100; #102 must
  restore database acceptance before integrated acceptance or activation.

## Alternatives considered

- Filter the planner DTO after loading it: rejected because history authority
  and recipient authority are different, independently checked purposes.
- Compare only delivery start/end: rejected because required own presence,
  room, preparation and copy can change independently.
- Treat a suppressed predecessor as empty: rejected because it fabricates
  additions and hides the loss of authoritative comparison evidence.

## Requirements affected

SCH-004/006/009/010/012, OPS-009, AUD-001 and NFR-001/013. ADRs 0096, 0097,
0099 and 0100 otherwise remain accepted.
