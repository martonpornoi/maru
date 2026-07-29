# Documentation standards

Status: Baseline  
Last updated: 2026-07-26

Documentation is maintained with the implementation.

## Required document types

- **Product requirements:** Stable behavior and acceptance intent.
- **ADRs:** Durable technical and architectural decisions.
- **Module documentation:** Ownership, public contracts, data, permissions,
  events, failure modes, and operational considerations.
- **API documentation:** Generated OpenAPI plus human explanations and examples.
- **Runbooks:** Deployment, migration, backup, restore, reconciliation, incident,
  and external-integration procedures.
- **Role guides:** Task-oriented help for attendees, Front Desk, Registration,
  HR, department leads, programme staff, IT, and other operators.
- **Release notes:** User-visible behavior, breaking changes, migrations, and
  known limitations.
- **Checkpoints:** Concise current handoff and append-only milestone records.

## Module README template

Each implemented module documents:

1. Purpose and requirements served
2. Owned data and invariants
3. Public commands, queries, and events
4. Permission and sensitivity model
5. Dependencies and consumers
6. User and operational workflows
7. Failure, retry, and reconciliation behavior
8. Retention and archival behavior
9. Tests and observability
10. Known limitations and future work

## Writing rules

- Prefer task and domain language over framework terminology.
- State what is authoritative and what is derived.
- Include examples with synthetic data.
- Explain permission failures and sensitive boundaries.
- Date operational assumptions that depend on external providers.
- Link instead of duplicating normative content.
- Mark proposed behavior as proposed; do not describe it as implemented.
- Remove stale instructions in the same change that makes them stale.

## API documentation

OpenAPI is generated and checked in CI. Every public operation has:

- a stable operation identifier;
- purpose and audience;
- authentication and required capabilities;
- organization and edition scoping;
- request, response, and error schemas;
- idempotency and pagination behavior where relevant;
- examples without personal data;
- deprecation information.

## User documentation

Role guides are organized around questions and outcomes, not database models.
Common workflows include screenshots or short recordings when the UI exists.
Terminology must match the interface.

## Documentation review

Every material task reviews:

- `docs/project/CURRENT.md`;
- affected requirements;
- relevant ADRs;
- module and API documentation;
- operations and role guides;
- checkpoint need.
