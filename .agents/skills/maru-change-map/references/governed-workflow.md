# Governed workflow reference

Read this reference for a domain command, protected query, API, event, migration,
or runtime-database change. Apply only the sections relevant to the request.

## Ownership and contracts

- Identify the owning Django module and the requirement that defines the
  behavior.
- Cross-module work uses documented commands, queries, or domain events. It
  does not import another module's private models or services.
- Browser and API adapters share the same application command or query. An
  adapter does not become a second source of domain behavior.
- External providers remain adapters and never become the canonical Maru
  record.

See the [modular-monolith architecture](../../../../docs/architecture/overview.md)
and [module catalog](../../../../docs/modules/index.md).

## Authority and disclosure

- Resolve trusted organization, edition, resource, and principal scope before
  reading private input or loading identifying labels.
- Deny by default. Test capability, relationship, object, field, lifecycle,
  cross-edition, and cross-tenant boundaries independently.
- Mutation authority does not imply read authority, and a visible destination
  or selected context does not grant either.
- Protected reads are bounded, complete-or-unavailable, reauthorized before
  disclosure where state can move, and audited before releasing sensitive
  names or relationships.
- Failure shapes do not disclose hidden people, records, counts, or tenant
  existence.

See the [authorization model](../../../../docs/security/authorization-model.md)
and [data classification](../../../../docs/security/data-classification-and-retention.md).

## Commands and evidence

- Use closed, typed input contracts with explicit blank/null meaning,
  normalization, bounds, actionable validation, trusted scope, optimistic
  versions, and idempotency where a retry can repeat a mutation.
- Recheck security-critical facts inside the transaction under a canonical lock
  order. Treat capacity and uniqueness decisions as concurrent decisions, not
  preflight hints.
- Commit aggregate state, immutable minimized command receipt, audit evidence,
  registered domain event, and outbox work atomically when those contracts
  apply.
- Required administrative rationale is visible where the decision is made.
  Routine personal actions do not collect unnecessary private explanations.
- Stable errors distinguish invalid input, non-disclosing denial, authorized
  absence, stale or lifecycle conflict, and unavailable dependencies.

## Database, migration, and recovery

- Review database-enforceable scope, version, lifecycle, evidence, protected
  deletion, and concurrency invariants.
- Migrations belong to the owning module. Rehearse forward migration, safe
  reverse while unused when supported, and the documented fix-forward fence
  once durable evidence exists.
- Update runtime relation/function/sequence permissions, trusted search path,
  trigger fingerprints, readiness checks, and recovery guidance when schema or
  privileged execution changes.
- Never use a fake migration, disabled guard, direct model save, or owner login
  as proof that the runtime contract is safe.

See the [operations and recovery guides](../../../../docs/operations/index.md)
and [resilience architecture](../../../../docs/architecture/resilience-and-offline.md).

## Verification

Cover successful behavior plus denial, cross-scope isolation, malformed input,
stale state, replay, dependency failure, rollback, concurrency, migration drift,
runtime readiness, and recovery as applicable. Keep generated OpenAPI, client,
frontend, and documentation artifacts deterministic. Record what was actually
run without turning focused evidence into a whole-repository or production
claim.
