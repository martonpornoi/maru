# ADR 0001: Python and Django modular monolith

- Status: Accepted
- Date: 2026-07-26
- Requirements: NFR-001, NFR-002, NFR-003, NFR-004, NFR-008

## Context

Maru will contain many related, transaction-heavy administrative domains. It
must be approachable to community contributors, thoroughly tested, exposed
through stable APIs, and maintainable over many event editions.

The public frontend must be replaceable without rewriting the operational
backend. The initial team does not benefit from the operational cost of
distributed services.

## Decision

Use:

- Python;
- Django 5.2 LTS;
- Django REST Framework;
- PostgreSQL;
- a modular monolith with one repository and initially one deployable backend;
- versioned REST APIs described by OpenAPI;
- separate frontend applications;
- background workers for slow and externally delivered work.

Django admin may bootstrap internal management. It is not the final staff
operations console.

## Consequences

Benefits:

- Django provides mature models, migrations, authentication, permissions,
  transactions, testing tools, and an internal admin.
- Python is accessible to the intended contributor community.
- One database simplifies cross-domain transactional workflows.
- A versioned API keeps annual frontend redesign independent.

Costs:

- Module boundaries must be enforced by convention and architecture tests.
- Complex field- and resource-level authorization remains application work.
- Care is required to prevent Django admin or ORM convenience from bypassing
  module boundaries.
- Realtime and offline features need explicit designs rather than a different
  core language.

## Alternatives considered

- Reflex: rejected as the core because it couples Python state and generated
  frontend behavior, conflicting with independently replaceable clients.
- ASP.NET Core: strong alternative, but less aligned with the expected
  contributor pool and provides less immediate internal administration.
- Laravel: capable and convention-proven, but Python contributor familiarity
  makes Django preferable.
- NestJS: attractive for TypeScript teams, but requires more ecosystem assembly.
- Microservices: deferred until measured scaling or ownership boundaries justify
  their operational cost.
