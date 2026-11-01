# ADR 0133: Keep new authority creation evidence on the database clock

- Status: Accepted; exact-head verification pending
- Date: 2026-11-01
- Clarifies: ADRs 0044 and 0106
- Requirements: IDN-002, IDN-004, IDN-005, IDN-012, IDN-014, AUD-001,
  AUD-005 and NFR-013
- Discovered during required acceptance for #235; activates no Programme profile

## Context

Programme requests and decisions already sample PostgreSQL time inside their
transaction. Their native approval guard requires an exact new assignment whose
creation and provenance evaluation are no earlier than the decision. Generic
authority commands instead sampled the application clock for new controller
provenance, and Django stamped assignment creation on that clock as well.
Different clock order can therefore reject a genuine new approval.

A fixture-only correction was insufficient: three real public approval cases
also failed. An isolated public-command diagnostic held only the application
clock. Both grant timestamps preceded the valid native decision while all
seventeen other exact new-grant predicates matched. The unchanged native guard
correctly rejected that evidence. This requires correcting the production
writer, rather than accepting an older grant or adjusting the native bounds.

## Decision

After locking both controllers, ordinary dual-control grant, role-definition
and assignment commands sample PostgreSQL `clock_timestamp()` for their new
immutable provenance evaluation. Missing or malformed time fails closed; a
database failure has no application-clock fallback. Source choice, identities,
scope, capability, current validity, horizons and lock order remain unchanged.
Callers receive no time argument or way to choose their provenance instant.
Programme's exact recipe-bundle proof then samples another validated native
instant under the existing locks, after loading or creating the bundle. Its
immutable version/name/capability and historical-lineage checks remain exact;
a held host clock cannot make newly created native evidence appear future.

New RoleAssignment creation uses a narrow DateTimeField subclass that emits
Django's `Now()` in the actual INSERT. PostgreSQL renders that expression as
`STATEMENT_TIMESTAMP()`, so a long transaction cannot backdate a new assignment
to transaction start. The field keeps automatic creation semantics, replaces
caller-supplied creation values and obtains the stored aware timestamp through
the pinned Django INSERT returning protocol. Normal create and bulk-create use
the same field path. Updates retain the existing immutable creation value.

Programme proposal creation also belongs to the actual owning INSERT. Its
existing early native observation remains input to admission/horizon checks;
the durable requested instant and its deadline are generated in the INSERT
statement, after validation and mandatory audit. Both use the same stable native
statement instant, with exactly `interval '168 hours'` for elapsed approval time
even in a connection timezone whose calendar week crosses a DST transition.
The stored values are returned to the normal command result.

The timestamp field uses only the existing private owner append context to
choose this expression. That context grants no database privilege and retains
the model writer check. Outside the owner context, explicit raw native probe
values pass unchanged to the native guards, including deliberate future and
pre-transaction inputs. Existing requests never save again on replay, so retries
cannot renew or replace their original interval. No timestamp is clamped, no
clock tolerance is introduced and no operation is retried until accepted.

Existing Board/root ceremonies keep their governed activation evidence; other
ordinary record timestamps retain their existing meaning. These timestamps are
not grants, approvals or new authority sources. Native exact-new-grant, lineage,
audit, scope, future/pre-transaction and immutable-evidence predicates remain
unchanged. Any clock rollback that violates those predicates still fails closed.

Migration 0048 records the three field implementations in ORM state through an explicit
SeparateDatabaseAndState operation. Both field types have the same physical
PostgreSQL column type, nullability and constraints. It changes no database
default, data, function, trigger or runtime privilege. Forward and reverse SQL,
actual current schema and ordinary migration drift must be verified; no fake
migration or schema-pin exception is permitted.

## Consequences and recovery

The Programme decision, later control evaluation and assignment INSERT can now
retain their actual database order without a clock tolerance, sleep or retry.
This does not promise that every application clock or policy evaluation ignores
host time. Operational clock synchronization and representative deployment
validation remain required; dormant Programme development is not activation.

Stored records remain ordinary aware datetimes, with no rewrite or backfill.
Reversing migration state changes no stored record. Rolling back application
code can restore the earlier clock-order availability defect; it cannot justify
loosening the database guard or changing retained timestamps. Existing coherent
backup/restore and provenance activation boundaries remain in force.

## Alternatives considered

- Relax the new-grant comparison or add tolerance: rejected because older
  output must remain inadmissible.
- Repair only the direct native fixture: rejected by actual public-command
  failures and minimized field observations.
- Sleep, retry or adjust machine clocks: rejected as a substitute for causal
  production timestamp ordering.
- Replace every timestamp in the application: outside this bounded defect.
  Only new controller provenance, RoleAssignment creation and proposal creation
  with its derived deadline need this repair.

## Acceptance

Require invalid/unavailable-clock unit cases and real public approval with a
held application clock. Assert native decision, evaluation and INSERT order,
the actual returned datetime, exact effective start and all existing negative
approval cases. Retain the strengthened old-output case with a matching future
effective start, so freshness cannot be hidden by a separate start mismatch.
Supply a deliberately stale/future preflight observation in a real proposal
command and require its stored/returned interval to use actual native INSERT
time. Direct raw invalid-time probes must still reach and fail the native guards.

Run fresh complete inexpensive feedback, complete ordinary exact-head Auto and
independent protected hosted acceptance with all required history, coverage,
timing, cleanup and runtime checks. Earlier failed or partial receipts remain
failed and cannot certify this source. Human, recovery, operational and production
acceptance remain separately recorded.
