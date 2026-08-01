# Exact authority-provenance migration and recovery

Status: additive writer-stage procedure; fail-closed policy activation is not
yet approved
Last updated: 2026-08-01
Scope: ADR 0044, authorization `0006`, and the compatible Board/authority
writers

## Purpose and current boundary

Authorization `0006` adds the append-only `AuthorityIssuance` and
`AuthorityControl` ledger. New compatible writers retain the exact persistent
grant or role assignment used by an actor and independent approver. Initial
Executive Board activation instead records the exact platform activation and
accepted cross-approver appointment, avoiding a circular authority root.

This is an additive deployment stage. It does **not** infer sources for legacy
authority, require every old target to have an issuance, or activate the final
fail-closed policy/completeness guards. Existing production readiness remains
blocked until the later provable backfill, explicit legacy reconciliation,
readiness, policy cutover, and downgrade-fence stages in ADR 0044 are complete.

Never treat an account identifier, current matching grant, familiar role name,
Django Group, staff flag, or platform-administrator status as historical source
evidence. A source is valid only when the ledger pins the exact earlier
issuance selected by the compatible command.

## Schema and writer guarantees

- Every issuance has one monotonic database ordinal, one non-guessable public
  identifier, one policy/evaluation timestamp, and exactly one typed grant,
  role-bundle, or role-assignment target.
- Ordinary root targets retain distinct actor and approver controls. Their
  exact earlier sources must match principal, command capability, organization,
  scope, current term, and requested horizon.
- A delegated grant retains its exact parent in `delegated_from` and has an
  issuance with no actor/approver controls.
- Initial Executive Board bundle and assignments retain one platform-
  activation control and one exact accepted-appointment control. The platform
  account is evidence, never the convention authority recipient.
- Issuances and controls reject update, row deletion, target deletion, malformed
  target/control shape, attribution mismatch, self-approval, later or foreign
  sources, and malformed Board evidence at both model and PostgreSQL boundaries.
- Role-bundle provenance is historical. A bounded but current controller may
  authorize an immutable definition; later controller loss does not rewrite
  that history. Every role assignment still needs current exact dual control.
- Target, ledger, audit, domain event, and outbox writes share one transaction.
  A failure leaves no orphan target or partial provenance.

The fresh-install graph explicitly places identity `0010` before organizations
`0009`, because the Board integrity SQL reads `account_kind`,
`email_verified_at`, and related identity fields. This dependency is required
even when another leaf happened to produce a safe order in an older graph.

## Before the maintenance window

1. Name the application, database/recovery, security, and verification owners.
2. Record the release commit, target database, maintenance window, backup/PITR
   position, and communication channel without recording credentials or
   personal data.
3. Stop every web, worker, scheduler, integration, management-command, and
   operator writer. Mixed old/new authority writers are unsupported.
4. Restore a representative backup into an isolated rehearsal database and
   prove that the restore can be used.
5. Run the existing privacy-minimized preflights:

   ```powershell
   & ".\.venv\Scripts\python.exe" src/manage.py check_representation_readiness
   & ".\.venv\Scripts\python.exe" `
     src/manage.py check_scope_v2_readiness --no-fail
   & ".\.venv\Scripts\python.exe" src/manage.py makemigrations --check --dry-run
   & ".\.venv\Scripts\python.exe" src/manage.py check
   ```

   `check_scope_v2_readiness` may report migration-data `status: ready` while
   production remains blocked on provenance. `--no-fail` is inspection only;
   it does not waive any blocker.
6. Inspect the exact plan and confirm identity `0010`, organizations `0009`
   through `0012`, authorization `0005`, and then authorization `0006` are
   ordered safely:

   ```powershell
   & ".\.venv\Scripts\python.exe" src/manage.py migrate --plan
   & ".\.venv\Scripts\python.exe" `
     src/manage.py showmigrations identity organizations authorization
   ```

## Apply and verify

With writers still stopped:

```powershell
& ".\.venv\Scripts\python.exe" src/manage.py migrate
& ".\.venv\Scripts\python.exe" src/manage.py check
& ".\.venv\Scripts\python.exe" src/manage.py makemigrations --check --dry-run
& ".\.venv\Scripts\python.exe" `
  src/manage.py check_authority_provenance_readiness --no-fail
```

The provenance command is available only after authorization `0006` has
created the ledger tables. Its `status` describes reachable data readiness;
its `production_status` must remain `blocked` during this additive stage and
names the unresolved policy-cutover, completeness-guard, and downgrade-fence
gates. Without `--no-fail`, any data blocker makes the command fail after
printing the same count-only JSON. Record the JSON, not identifiers or sampled
personal records.

## Provable-only reconciliation

Keep writers stopped and inspect the backfill plan first:

```powershell
& ".\.venv\Scripts\python.exe" `
  src/manage.py backfill_provable_authority_provenance --no-fail
```

The default is a read-only dry run. `planned_counts` may include only the
initial code-owned Executive Board bundle/assignments and delegated grants
whose exact parent chain is already present. `review_counts` deliberately
leave ordinary root grants, ordinary role definitions, and ordinary role
assignments untouched. The command never chooses a plausible controller source
from current state.

Resolve every `blocker_counts` item before mutation. With all application,
worker, scheduler, integration, and operator writers still stopped, append the
provable rows in one transaction:

```powershell
& ".\.venv\Scripts\python.exe" `
  src/manage.py backfill_provable_authority_provenance `
  --apply --acknowledge-writers-stopped
```

Both flags are required. Apply mode locks the identity, organization,
representation, authority-target, issuance, and control snapshot in a stable
order; writes Board evidence before parent-first delegated chains; rereads the
graph; and rolls the whole transaction back if any planned row remains or any
post-write blocker appears. Repeating apply is idempotent and reports preserved
counts without appending another issuance.

An initial Board remains historically provable after later emergency
suspension, ended controller terms, or platform-operator deactivation because
its activation attribution, timestamp, exact initial appointment cohort,
cross-approvals, role assignments, and end/revocation timestamps are durable.
Current inactivity never becomes generic organizer authority. A conflicting,
partial, duplicate, later replacement, or otherwise non-exact ceremony stays a
blocker; do not disable guards or manufacture evidence to make it pass.

Before reopening compatible writers, use synthetic accounts in an isolated
Draft organization to prove:

1. two eligible people accept their exact Executive Board invitations;
2. activation produces one reserved bundle issuance and one issuance per
   assignment, with a different accepted controller as each approver;
3. the platform account has no organization membership, participation,
   registration, workforce assignment, grant, or role-assignment principal row;
4. an authorized Board pair creates one bounded direct grant, one immutable
   role definition, and one role assignment with exact earlier sources;
5. a missing, revoked, expired, malformed, foreign-tenant, or wider-than-target
   source fails without creating a target, ledger, audit-success, event, or
   outbox row;
6. revoking one pinned source invalidates the dependent lineage without
   silently selecting an equivalent source; and
7. sensitive inspection and denial evidence contains no password, email,
   display name, reason text, session material, or submitted profile value.

Re-run all three readiness commands:

```powershell
& ".\.venv\Scripts\python.exe" src/manage.py check_representation_readiness
& ".\.venv\Scripts\python.exe" `
  src/manage.py check_scope_v2_readiness --no-fail
& ".\.venv\Scripts\python.exe" `
  src/manage.py check_authority_provenance_readiness --no-fail
```

During this additive stage, the provenance data status may remain blocked for
unreconciled legacy rows; even zero data blockers do not complete the three
activation gates. Record the count-only output and do not relabel it
production-ready.

## Failure and recovery

### Migration has not committed

Keep writers stopped. Preserve the bounded error, plan, and database state.
Correct an understood blocker in a restored rehearsal first and rerun forward.
Do not use `--fake`, disable triggers, insert guessed controls, or edit audit
history.

### Migration committed but no issuance exists

A clean reverse can remove the additive tables. Rehearse the reverse and full
forward graph before using it on a target. Prefer a forward fix whenever
practical.

### Any issuance or control exists

Authorization `0006` refuses downgrade. The target, issuance, controls,
representation, audit, event, and outbox records form one history. Keep
compatible code and fix forward, or restore the **whole** database and
application to one mutually consistent pre-write recovery point after an
explicit data-loss decision. Never delete only provenance evidence or deploy
an old writer over the populated ledger.

### A command or publication fails

The transaction must roll back the target and every provenance/control row.
If the transaction committed and only asynchronous delivery remains, replay
the durable outbox through the effects runbook; do not reissue authority merely
to force delivery.

## Later activation stages

Do not activate fail-closed policy from this runbook. The remaining ADR 0044
maintenance work is deliberately separate:

1. complete and record the provable-only backfill described above;
2. report count-only missing/malformed/cyclic lineage;
3. revoke and recreate effective ordinary legacy authority under current dual
   control, replacing referenced unproven bundles;
4. prove zero effective/reachable blockers on a restored database;
5. install deferred completeness guards and switch policy to exact dynamic
   lineage; and
6. set the durable provenance-write downgrade fence and verify old-writer
   rejection.

The deployment record must retain the release, plan, pre/postflight counts,
backup/restore evidence, synthetic correlation identifiers, and any
fix-forward decision. It must not retain credentials or production personal
data.
