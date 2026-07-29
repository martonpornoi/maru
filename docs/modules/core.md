# Core module

Status: Implemented foundation  
Last updated: 2026-07-27

## Purpose and requirements

`maru.core` owns genuinely domain-neutral runtime primitives supporting
NFR-001, NFR-004, NFR-006, and NFR-008.

## Owned behavior

- UUID/timestamp abstract persistence base
- strict reusable value validators
- request correlation
- allowlisted structured JSON logging
- RFC 9457-style DRF problem responses
- liveness, database readiness, and build identity endpoints
- browser-friendly development landing page
- consistent bootstrap-administration branding, safety mixins, and navigation

It does not own tenant context, business rules, permissions, audit, or a generic
`utils` collection.

## Bootstrap administration

The temporary Django administration surface is branded as Maru bootstrap
administration. Shared admin mixins remove destructive bulk deletion and make
command-owned records view-only. Django's generic `Group` page is hidden
because Maru authority is expressed through scoped capabilities and versioned
role bundles, not a parallel unscoped role system.

Module-owned admin pages provide the domain-specific names, filters, searches,
field groupings, and archived-state behavior. Technical UUIDs and timestamps
remain available in collapsed detail sections rather than leading list views.
The header also hosts the ADR 0008 convention-workspace selector. Event-owned
modules declare their scope explicitly; the shared shell does not infer tenant
ownership or treat the selected edition as authorization.

An authenticated Django staff account that has no edition participation is
routed from `/staff/` to `/admin/`, where `All foundation data` remains
available for first-time setup. Active non-administrators without a workspace
retain the Staff Console's safe empty state.

## Public contracts

- `UUIDTimeStampedModel`
- value validators under `maru.core.validators`
- correlation context
- `/`
- `/health/live`
- `/health/ready`
- `/api/v1/meta/build`

## Security and data

Correlation accepts only UUID input and generates a replacement otherwise.
Logs include an allowlist of technical metadata. Exception type may be logged;
exception message and request payload are not.

Health failures name only the affected dependency class. Liveness deliberately
does not contact external dependencies.

## Failure and operations

Readiness returns `503` when PostgreSQL cannot answer a trivial query.
Independent provider health will be added to an authenticated operator
projection, not the public response.

## Tests

Unit tests cover strict environment parsing, validators, request correlation,
safe log output, problem response shape, and health/build behavior.

## Limitations

Audit, metrics/tracing export, error capture, rate limiting, and a public status
service arrive in later V02/operations work.
