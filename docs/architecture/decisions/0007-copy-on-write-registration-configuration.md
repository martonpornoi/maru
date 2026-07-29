# ADR 0007: Copy-on-write registration configuration and templates

- Status: Accepted
- Date: 2026-07-27
- Requirements: EVT-002, EVT-003, REG-001, REG-002, REG-003, ARC-002,
  PRI-001

## Context

Registration differs materially between conventions and often between annual
editions of the same convention. Organizers need to define questions,
agreements, products, prices, eligibility, and capacity without requesting a
custom software fork. They also need to reuse a reviewed setup from a prior
edition or a reusable template.

Sharing one mutable configuration across editions would let a later edit change
an open registration or rewrite the meaning of an earlier submission. Blindly
cloning last year's setup would preserve stale prices, dates, wording, and
policy assumptions without review.

## Decision

Registration configuration is edition-owned, versioned, and copy-on-write.

- A draft configuration may start empty, from a published registration
  template, or from another edition in the same organization.
- Import copies questions and products into new edition-owned records. It never
  makes the target edition depend on mutable source records.
- Every imported draft is marked `review required` and retains immutable source
  provenance.
- Activating a configuration freezes that version for new submissions. Later
  changes use a new version.
- A submission retains its exact configuration version, schema snapshot,
  product and price snapshot, and validated answers.
- Published templates are immutable versions. A changed reusable setup is a new
  template version, not an edit to an already-used version.
- Templates may be organization-wide or limited to one convention series.
- Configuration may be copied only within one organization. Cross-organizer
  sharing requires a future explicit export/import contract and cannot bypass
  tenant governance.
- Dates, prices, capacity, agreements, and policy wording are review-sensitive
  even when inherited. Import never activates them automatically.

The first implementation supports classified C1/C2 question types. Restricted
C3/C4 collection is deliberately excluded until a purpose-specific domain and
retention workflow owns it.

## Consequences

Organizers get reusable setups without hidden live coupling. Historical
submissions remain explainable, and one edition can diverge safely from its
source. Storage contains deliberate copies, and template promotion and
activation require explicit commands and audit evidence.

The Staff Console can present inheritance as a source choice plus a review
queue. Django admin remains a bootstrap editor for draft questions and
products until the full form-builder interaction arrives.

## Alternatives considered

- One mutable series configuration: rejected because it can alter several
  editions and historical meaning at once.
- Unversioned JSON blobs on the edition: rejected because ownership,
  validation, classification, review state, and useful administration become
  opaque.
- Automatic inheritance from the immediately previous year: rejected because
  stale assumptions would become active without accountable review.
- Cross-organizer template browsing: deferred because tenant ownership,
  licensing, policy provenance, and safe import need an explicit contract.

