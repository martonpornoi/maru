# ADR 0070: Clear public maturity description

- Status: Accepted
- Date: 2026-08-21
- Requirements: NFR-002, NFR-003, NFR-011
- Implements: GH-004
- Supersedes: ADR 0068 decision 8 only
- Relates to: ADR 0065 and ADR 0068

## Context

ADR 0068 selected a repository description beginning with **Pre-production**
to make Maru's maturity visible. Before that wording was applied, the owner
asked what it meant and found it ambiguous. In software operations,
pre-production can describe a staging environment as well as a project's
readiness, while Maru needs a short public statement that a potential
contributor can understand without operational context.

The authenticated pre-change readback reported the live description as
**Security-focused Django and PostgreSQL platform for operating
multi-convention events.** The repository remains public and its homepage is
empty. Changing live metadata remains an external mutation requiring explicit
authorization and post-change readback.

## Decision

1. Replace ADR 0068 decision 8 with the exact repository description
   **Security-focused Django and PostgreSQL platform for operating
   multi-convention events, under active development.**
2. Use **under active development** as a plain-language maturity signal. It
   does not declare a release stage, hosted service, production approval, or
   permission to use real personal data. The maintained readiness documents
   continue to own the exact open operational gates.
3. The owner authorized this description-only mutation on 2026-08-21. The
   authenticated post-change readback returned the exact accepted text. The
   repository remained public and its homepage remained empty. The mutation
   command supplied only the description option; no topic or feature update was
   requested or executed.
4. Future description changes require another explicit decision,
   authorization, and readback. Do not silently edit an accepted ADR to make a
   later wording appear original.

## Consequences

- The short repository description communicates active development without
  using a term that may be mistaken for a deployment environment.
- The wording remains honest about maturity while avoiding a claim that Maru
  is unusable, abandoned, released, or production-ready.
- ADR 0068 continues to govern public channels, sole-maintainer continuity,
  topics, feature state, social preview, funding, and newcomer labels. Only its
  exact description decision is superseded.
- GH-004's live metadata reconciliation is complete; ready-state pull-request
  acceptance remains a separate merge boundary.

## Alternatives considered

### Use “Pre-production”

Rejected as the current repository-description wording because it was not
immediately clear to the repository owner and can also name a staging
environment. It remains a valid technical description of Maru's readiness in
detailed operations docs.

### Keep the description without a maturity signal

Rejected because a public visitor could otherwise infer that the platform is
already released or appropriate for live convention data.

### Say “Not production-ready”

Rejected for the short repository description because it emphasizes a
negative without conveying that substantial, tested development is active.
Detailed readiness documentation continues to state the production boundary
directly.

## Requirements affected

- NFR-002 requires public-facing maturity and detailed readiness documentation
  to remain consistent.
- NFR-003 is satisfied by the GH-004 checkpoint and current-state handoff.
- NFR-011 requires the authenticated before/change/after evidence and preserves
  separate authorization for future external mutations.
