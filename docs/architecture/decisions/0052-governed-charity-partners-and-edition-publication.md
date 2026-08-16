# ADR 0052: Governed charity partners and edition publication

- Status: Accepted
- Date: 2026-08-09
- Clarifies: ADRs 0002, 0003, 0005, and 0016
- Requirements: FUR-005, FUR-011, FIN-007, PRI-001, AUD-001, and AUD-005

## Context

A convention may consider several charities each year and retain reusable
identity, imprint, contact, location, description, and photographs. Rejection
reasons and reviewer comments are not public profile fields. A charity is also
not necessarily a Maru tenant or convention organizer, and confirmation for
one edition must not silently carry into another.

## Decision

`charities` owns reusable organizer-scoped partner records and governed media.
It does not create an `Organization`, membership, representation, or software
authority for the charity. Each edition creates an exact CharitySelection with
a responsible Department and an append-only proposal, review, decision,
comment, and publication timeline.

Submission, confirmation or rejection, media approval, and publication are
separate expected-versioned commands. Confirmation, media approval, and
publication require independent authorized actors. Private comments and
decision rationale remain in restricted projections and are never copied into
public event metadata. Publication writes an immutable minimized snapshot and
requires a currently active partner, confirmed selection, and currently
approved non-expired media. Withdrawal is append-only. Public queries release
only active, confirmed, currently published snapshots and revalidate their
media.

Catalog products may refer to an exact confirmed edition selection as their
beneficiary. That reference communicates intended beneficiary; it does not
claim that funds were settled, acknowledged, or publicly reported. Those
finance and stewardship steps retain their own evidence.

## Consequences

- Multiple candidates and multiple published charities are supported without
  confusing annual decisions with reusable facts.
- Rejection reasons and internal discussion do not leak through directory,
  event, audit, or catalog projections.
- Partner identity can be maintained once while every edition performs its
  own accountable decision and publication.
- Charity fundraising, settlement, restrictions, and public impact reporting
  remain explicit future workflows rather than inferred states.

## Alternatives considered

### Register each charity as a Maru organization

Rejected. A partner relationship does not imply tenancy, governance, accounts,
or convention authority.

### Publish directly from the reusable partner profile

Rejected. It bypasses annual confirmation, media review, dual control, and an
immutable record of exactly what the public saw.
