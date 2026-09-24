# ADR 0112: Native point-in-time policy observation

- Status: Accepted; implementation and native acceptance pending
- Date: 2026-09-20
- Extends: ADR 0044; its exact-source semantics and writer contract are unchanged
- Requirements: IDN-009, SCH-006, NFR-001, NFR-004, NFR-005, NFR-010, NFR-013

## Context

Issue #198 records a genuine Programme operator and exit-archive latency blocker.
A three-item populated diagnostic takes roughly 17 seconds for a room output,
36 seconds for a Department output, and 23 seconds for archive retrieval. The
maintained isolated HTTP budget is 15 seconds. The longer diagnostic is functional
evidence, not acceptance under that budget.

A separate request profile observes 15,480 database queries for one room output.
The instrumented request takes 26 seconds, including about 20 seconds in ordinary
policy decisions. Profiling overhead means that time is not directly comparable
to an uninstrumented response. Independent owners deliberately repeat scope,
field, source-membership and current-permission checks before releasing data.
Their pure point-in-time policy calls recursively re-read issuance ancestors
through the Python validator, creating many database round trips.

Authorization already has a fingerprinted, runtime-allowed PostgreSQL exact
issuance validator. The explicit non-locking batch boundary uses it for shell
and role projections, with positional results and differential Python evidence.
The single-issuance and locking writer boundaries retain the independent Python
validator. No new function, privilege, schema, index or cache is needed.

## Decision

Use that existing non-locking boundary for each exact issuance considered by
`decide`. Submit one typed check containing the original issuance ordinal,
principal, capability, resolved target and evaluation instant, with
`POINT_IN_TIME` horizon. Never select a replacement source for an invalid
issuance. The ordinary policy may still examine other separately issued grants
or roles, as before; this does not rebind their recorded ancestry.

Keep marker/latch observation, current persisted target resolution, adoption
admission, account rules, role-purpose rules, field intersection, obligations,
reason codes and policy version unchanged. Do not cache results between calls,
owners or requests. Preserve every owner recheck, canonical lock, version and
membership comparison, source collection and required audit.

`decide` remains a non-locking policy observation even when used as a command's
preflight; its result is not a reusable permission token. This change does not
replace transaction-scoped command checks or select persistent control sources.
`authority_issuance_is_current`, lock-capable batch checks, deterministic writer
source selection and control-horizon proofs retain the independent Python path.
Database unavailability propagates to existing fail-closed owner handling; no
Python or compatibility fallback conceals a failed native contract.

## Consequences

The optimization removes recursive client round trips, not security checks.
There is no schema migration, new runtime permission, profile activation or
stored authority change. Recovery still requires the same complete fingerprinted
database contract. Reverting this code changes latency, not stored evidence.

Verification must compare complete decisions for direct grants and roles,
including fields, current scope, expiry, revoked ancestors, missing lineage,
invalid cutover state and both accountable roots. It must preserve writer-path
tests and native/Python differential checks. A genuine populated runtime must
then pass the unchanged HTTP and fixture budgets; instrumentation-only results
cannot establish final performance acceptance.

## Alternatives considered

- Increasing the HTTP deadline: hides the observed cost and worsens on-site use.
- Removing owner or final rechecks: weakens current independent disclosure rules.
- Cross-request or cross-owner permission caching: risks stale revocation and
  converts observations into portable authority.
- Replacing writer validation wholesale: unnecessarily changes locking and
  persistent-horizon boundaries that are not needed for this correction.

## Requirements affected

IDN-009 current exact lineage and field policy; SCH-006 operator outputs;
NFR-001 differential and native acceptance; NFR-004 non-identifying diagnostics;
NFR-005 bounded on-site use; NFR-010 the unchanged pinned execution boundary;
NFR-013 independent selected-owner authority and no excluded-module effects.
