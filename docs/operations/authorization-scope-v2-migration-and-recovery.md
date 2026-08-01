# Authorization scope-v2 migration and recovery

Status: verified maintenance-window procedure for ADR 0041  
Last updated: 2026-08-01

## Purpose

Authorization scope v2 adds exact department and typed-resource authority to
the existing organization and edition lattice. It is an ordered, stopped-writer
change:

```text
authorization 0004 additive schema
  -> workforce 0004 owning-record integrity
  -> authorization 0005 preflight, binding backfill, guards, and fence
```

Existing organization- and edition-scoped grants and role assignments retain
their broad meaning. The migration does not infer a department or Position
from a workforce link. Review and narrow historical authority only through a
later explicit, audited command.

This procedure establishes migration-data readiness. It does **not** clear the
separate actor/approver authority-source provenance production gate recorded
in ADR 0041.

## Before the maintenance window

1. Confirm a restorable PostgreSQL backup and the recovery point objective in
   [`deployment-and-service-objectives.md`](deployment-and-service-objectives.md).
2. Stop every web, worker, scheduler, and operator writer that can create or
   change workforce or authorization rows.
3. Keep one application version and one migration owner. Mixed writers are not
   supported once department/resource authority is enabled.
4. Run the representation and subject-boundary preflights first:

   ```powershell
   & ".\.venv\Scripts\python.exe" src/manage.py check_representation_readiness
   ```

5. Apply migrations in a rehearsal database restored from representative
   backup data. Django follows the dependency order above automatically:

   ```powershell
   & ".\.venv\Scripts\python.exe" src/manage.py migrate --plan
   & ".\.venv\Scripts\python.exe" src/manage.py migrate
   ```

The migrations report counts only. They do not print account identities,
authority UUIDs, department names, or capability values.

## What activation verifies

The stopped-writer preflights reject:

- malformed organization/edition/department/resource tuples;
- foreign parent chains and invalid typed bindings;
- unknown, relationship-only, or too-broad persisted capabilities;
- empty, duplicate, null, or otherwise invalid role capability arrays;
- delegation scope or time-horizon violations and recursive cycles;
- incomplete revocation evidence;
- department or Position scope mismatches and hierarchy cycles; and
- PositionAssignment role evidence that does not match the exact person and
  workforce position.

Authorization `0005` creates a reproducible binding for every Position that
exists during migration. A valid preexisting binding is preserved. Positions
created later use the explicit owning-module binding service before exact
resource authority is assigned.

## After migration

Run the privacy-minimized readiness report:

```powershell
& ".\.venv\Scripts\python.exe" `
  src/manage.py check_scope_v2_readiness --no-fail
```

Interpret its top-level fields separately:

- `status` is `ready` only when migration-data blocker counts are zero;
- `review_counts` identifies broad legacy evidence that remains valid but may
  deserve explicit reconciliation;
- `production_status` remains `blocked` while the separately documented
  actor/approver source-provenance gate is unresolved; and
- `known_production_gates` names that gate without exposing people or records.

Then verify:

```powershell
& ".\.venv\Scripts\python.exe" src/manage.py check
& ".\.venv\Scripts\python.exe" src/manage.py makemigrations --check --dry-run
```

Exercise an organization, edition, exact department, and exact Position target
with authorized and sibling/foreign-tenant principals. Confirm that denials are
non-disclosing and that sensitive reads and privileged mutations produce audit
evidence.

## Write and recovery semantics

After activation:

- authority issuance fields are append-only;
- replacement creates a new grant or role assignment;
- revocation requires a revoker and nonblank reason, and cannot be undone or
  rewritten;
- authority records are revoked rather than hard-deleted;
- resource bindings are immutable;
- a department applies only to that exact department, never its tree; and
- revoking or expiring any delegation ancestor invalidates descendants
  immediately.

The first department- or resource-scoped authority write creates a durable
singleton recovery marker. Reversal of authorization `0005` checks this marker
before changing functions, triggers, or bindings. Deleting or revoking the
authority does not clear it.

## Failure and downgrade

If forward migration preflight fails, leave writers stopped, inspect the
count-only exception and the readiness JSON, reconcile the exact rows through
an approved data-repair change, and rerun forward. Do not weaken or disable the
guards to force deployment.

Before the first scoped write, a clean rehearsal reverse removes only bindings
whose deterministic identifiers prove that `0005` created them; valid
preexisting bindings remain. After the durable marker exists, downgrade is
refused by design. Keep compatible code and fix forward, or restore the whole
database and application to one mutually consistent pre-write recovery point.
Do not reverse only the workforce guard layer.

## Evidence

The automated migration tranche covers fresh and populated forward migration,
deterministic and idempotent binding backfill, database-bypass containment,
hierarchy cycles, delegation cycles and horizons, append-only issuance,
one-way revocation, clean reverse, durable downgrade refusal, and migration
graph restoration. The command tranche verifies exact counts and absence of
email, name, capability text, or UUID disclosure.
