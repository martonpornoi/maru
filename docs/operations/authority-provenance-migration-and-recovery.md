# Exact authority-provenance migration and recovery

Status: staged writer and irreversible exact-lineage activation procedure
Last updated: 2026-08-02
Scope: ADR 0044, authorization `0006` through `0009`, audit `0005` and `0006`,
organizations `0013`, workforce `0005`, compatible Board/authority writers,
count-only readiness, and the one-way activation command

## Purpose and current boundary

Authorization `0006` adds the append-only `AuthorityIssuance` and
`AuthorityControl` ledger. New compatible writers retain the exact persistent
grant or role assignment used by an actor and independent approver. Initial
Executive Board activation instead records the exact platform activation and
accepted cross-approver appointment, avoiding a circular authority root.

Audit `0005` first adds the permanent no-truncate audit boundary and a unique
activation-audit key. Authorization `0007` then adds the immutable activation
singleton, dormant deferred completeness checks, an old-writer serialization
boundary, same-transaction activation proof, and authority
downgrade/truncation fences. Audit `0006` adds the reciprocal reserved-operation
guard and rejects an upgrade over orphan, extra, or malformed legacy activation
audit evidence. Authorization `0008` moves only the latch row lock into a
fixed-search-path, `SECURITY DEFINER` helper whose `PUBLIC` execution is revoked;
the writer trigger remains invoker-security. The dedicated runtime login may
execute that one helper but retains only `SELECT` on the latch and marker.
Organizations `0013` and workforce `0005` harden the four remaining
runtime-executable Board/workforce helpers plus their persistent trigger
callers. Authorization `0009` converges those owning migrations with `0008` and
adds a central reverse fence; each owning migration also refuses an activated
reverse if that convergence recorder row is lost.

Applying the migrations does not itself switch policy: compatibility readers
remain selected while the marker is absent. The marker may be inserted only by
the guarded activation service after provable backfill, explicit legacy
reconciliation, a zero-blocker graph, and an acknowledged stopped-process
preflight. Once it commits, exact lineage and the database completeness boundary
are irreversible.

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
   through `0013`, workforce `0004` and `0005`, authorization `0005` through
   `0008`, audit `0005` and `0006`, then authorization `0009` are ordered
   safely:

   ```powershell
   & ".\.venv\Scripts\python.exe" src/manage.py migrate --plan
   & ".\.venv\Scripts\python.exe" `
     src/manage.py showmigrations `
       identity organizations workforce audit authorization
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

The provenance command is available after authorization `0006` creates the
ledger tables. Authorization `0007`, audit `0006`, authorization `0008`,
organizations `0013`, workforce `0005`, and authorization `0009` let it verify
the complete guard, migration, function-definition, and least-privilege helper
catalog as well as the data. `status` describes reachable data,
`activation_status` describes whether the one-way transition is presently
allowed, and `production_status` remains blocked until the marker exists and
every guard/policy/fence gate is resolved.
Without `--no-fail`, either a data blocker or unresolved production gate makes
the command fail after printing the same count-only JSON. Record the JSON, not
identifiers or sampled personal records.

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

Before cutover, provenance data may remain blocked for unreconciled legacy
rows. With the `0007`/audit `0006`/authorization `0008` boundary intact and zero
blockers, `activation_status` becomes ready but the absent marker still keeps
`production_status` blocked. Record the count-only output and do not relabel it
production-ready.

## Failure and recovery

### Migration has not committed

Keep writers stopped. Preserve the bounded error, plan, and database state.
Correct an understood blocker in a restored rehearsal first and rerun forward.
Do not use `--fake`, disable triggers, insert guessed controls, or edit audit
history. An audit `0006` preflight failure means the database is neither
pristine dormant nor one exact durable marker/audit/latch state. Restore the
whole database to a consistent point or fix forward from independently verified
evidence; never delete only the orphan or fabricate its companion.

### Migration committed but no issuance or activation exists

A clean reverse can remove the additive ledger/activation schema only while no
issuance, control, or activation marker exists. Rehearse the reverse and full
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

## Irreversible exact-lineage activation

Activation is a separate maintenance decision after reconciliation. Rehearse
the exact release and a representative restored database first. A zero data
blocker count alone is not permission to proceed.

1. Confirm backup/PITR and restore evidence, named application/database/security
   owners, the release commit, rollback decision point, and maintenance channel.
   Confirm the activation connection uses PostgreSQL `READ COMMITTED` isolation;
   the application service and database trigger reject higher isolation because
   an older MVCC snapshot cannot prove actor eligibility after waiting on the
   cutover barrier.
2. Stop **every** web process, API process, worker, scheduler, integration,
   management command, and interactive/operator writer. Stop old readers too:
   an old binary does not understand the marker and can continue making legacy
   existential access decisions even though the database rejects its writes.
3. Apply the complete authorization `0007`, audit `0006`, authorization `0008`,
   organizations `0013`, workforce `0005`, and authorization `0009` boundary
   while processes remain stopped, then run:

   ```powershell
   & ".\.venv\Scripts\python.exe" src/manage.py migrate
   & ".\.venv\Scripts\python.exe" src/manage.py check
   & ".\.venv\Scripts\python.exe" `
     src/manage.py makemigrations --check --dry-run
   & ".\.venv\Scripts\python.exe" `
     src/manage.py check_authority_provenance_readiness --no-fail
   ```

   The report must have `status: ready`, `activation_status: ready`,
   `production_status: blocked`, `blocker_total: 0`, no marker, and every
   policy/guard contract installed. `--no-fail` is only needed because the
   deliberately absent marker keeps production blocked before cutover.
   The reported activation `policy_version` is the frozen historical release
   used by this cutover. Do not rewrite it when the ordinary capability catalog
   advances; the provenance `contract_version` selects exact-lineage runtime
   compatibility.
   Set `MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE=true` in the recorded release
   configuration before activation. With processes still stopped, its expected
   pre-activation effect is to deny organizer authority and keep
   `/health/ready` unavailable. This is the external restore fence, not a
   substitute for the database marker or readiness command. Confirm the target
   uses the rehearsed PostgreSQL 17 major; the required-exact health probe fails
   closed on any other major without disclosing its value.
   Set `MARU_RUNTIME_DATABASE_ROLE` to the exact dedicated login-role name; it
   contains no credential. Provision it through an audited database role
   administrator/owner with authority to create roles, change database/schema
   ACLs, and alter defaults for the distinct migration role by adapting the
   reviewed
   [`postgresql-runtime-role-provisioning.sql.example`](postgresql-runtime-role-provisioning.sql.example).
   Keep the migration and break-glass roles separate. The runtime role must
   positively prove database `CONNECT`, `USAGE` on every intentional
   non-system schema, four-operation DML on ordinary runtime relations,
   `USAGE`/`SELECT` (never `UPDATE`) on sequences, and `EXECUTE` on the exact
   versioned 19-function v2 policy/trigger-helper closure. Materialized views
   and the exact control trio (`django_migrations`, activation marker, and
   generation latch) are SELECT-only. `PUBLIC` must not execute any non-system
   function and the runtime role must not execute a function outside that
   allowlist. It must not:

   - inherit superuser, `CREATEDB`, `CREATEROLE`, replication, `BYPASSRLS`, a
     reserved/predefined `pg_*` identity, another privileged role, or any
     membership edge carrying `ADMIN OPTION`;
   - own the database or any non-system schema, relation, or function;
   - have effective database `CREATE`/`TEMPORARY` or `CREATE` on any non-system
     schema, whether directly, through `PUBLIC`, or through membership; or
   - have effective table `TRIGGER`, `TRUNCATE`, or `MAINTAIN`;
   - have table- or column-level migration-recorder/marker/latch mutation,
     sequence `UPDATE`, or a grant option on the database, a non-system schema,
     relation, column, sequence, or function;
   - receive any explicit effective parameter `SET`/`ALTER SYSTEM` ACL; or
   - receive an applicable persistent `session_replication_role` value other
     than `origin` through global, current-database, or role settings.

   Run the readiness command as the migration owner. Its parameterized catalog
   probe evaluates the configured future runtime role, not the connected owner,
   and exposes only pass/fail gates. A missing or non-login role, unsafe direct
   or inherited path, unexpected ownership, missing data-plane access, public
   function execution, or missing/extra allowlisted function execution is a
   blocker. The probing owner session must itself have live
   `session_replication_role=origin`; otherwise activation is unsafe even when
   the future role's stored ACLs are correct. Never record the role credential
   or database URL.
   After activation, start web and worker processes with that role and require
   `/health/ready` to prove that `CURRENT_USER`, `SESSION_USER`, and the
   backend-authenticated `pg_stat_activity` identity all match the configured
   role. `SET ROLE` and `SET SESSION AUTHORIZATION` are not deployment smokes;
   use a genuine password- or managed-identity-authenticated connection.

   Activation remains a controlled migration/cutover-owner operation. The
   application login reads but never mutates the migration recorder, marker,
   or latch. Its ordinary
   audit INSERT cannot forge the reserved activation operation: the audit
   database guard accepts that operation only with the frozen payload, matching
   marker/latch, and marker creation in the current transaction.

   Maru owns the libpq `options` value and rejects a database URL that supplies
   one; every process receives the code-owned `search_path=public,pg_temp`.
   Drain old pooled sessions as already required; never rely on a role or
   connection setting change while an old session remains alive.
4. Activate once with an active platform-administrator account. Supply an
   operational reason, never a password, token, personal case narrative, or
   production subject data:

   ```powershell
   & ".\.venv\Scripts\python.exe" `
     src/manage.py activate_authority_provenance `
     --actor "platform-admin@example.invalid" `
     --reason "Approved ADR 0044 maintenance cutover." `
     --acknowledge-processes-stopped
   ```

   The service refuses to run unless the exact-required fence is true,
   autocommit is enabled, no outer transaction exists, and the session uses
   `READ COMMITTED`. It pins `public` ahead of explicit trailing `pg_temp` for
   its transaction. The command then obtains the global cutover lock before
   inspecting actor eligibility and the graph, writes one database-timestamped
   marker and one matching append-only security audit in the same PostgreSQL
    transaction,
   reruns readiness, and commits only when the postcondition is
   production-ready. Lock acquisition is bounded at ten seconds: a timeout
   means a process or transaction was not actually drained, so inspect and stop
    it rather than widening the timeout casually. The audit's partial unique
    index rejects a duplicate correlation, while audit `0006` rejects any later
    reserved-operation append even when it uses a fresh correlation. Its JSON
    is count-only apart from contract, policy, and correlation identifiers; it
    does not echo the actor or reason. A repeat is idempotent and returns
    `already_active` without another marker or audit.

   A failed command returns one opaque correlation identifier and a bounded
   diagnostic code: `actor_unavailable`, `process_acknowledgement_required`,
   `readiness_blocked`, `postcondition_invalid`, `environment_invalid`,
   `transaction_boundary_invalid`, `activation_request_invalid`,
   `writer_drain_timeout`, `concurrent_writer_conflict`,
   `database_unavailable`, or `internal_error`.
   Search restricted structured logs by that correlation. They retain only the
   code and exception class, never the actor identifier, reason, authority
   graph, or database message. `writer_drain_timeout` specifically means the
   ten-second advisory boundary expired; other codes must not be diagnosed as
   writer drain by guesswork.
5. Run the readiness command again **without** `--no-fail`. It must report
   `status: ready`, `activation_status: blocked`, `production_status: ready`,
   and all production gates resolved. Activation is now blocked because the
   one permitted transition has already occurred. `/health/ready` must now
   report both the database and minimized `authority_provenance` dependency as
   ready under the required-exact configuration.
6. Prove, on the stopped production release or a transactionally identical
   rehearsal, that an unissued raw grant, role definition, or role assignment
   fails; a compatible issued record succeeds; loss of one pinned source denies
   its dependent record despite equivalent authority; marker/ledger mutation,
   deletion, truncation, and migration reverse fail; and readiness detects a
   disabled or altered guard without exposing identifiers.
7. Start only processes built from the recorded compatible release. Exercise
   sign-in, Board authority, a harmless authorized read, one denial, audit
   append/seal, worker health, and the count-only readiness probe before ending
   the maintenance window.

The production application role must satisfy the complete configured
least-privilege catalog proof above. The migration and break-glass database
roles remain separate, tightly controlled, and audited.
Database triggers defend normal and stale application writers; they cannot
protect against a database owner intentionally removing its own guard.
All web, worker, scheduler, integration, and management-command workloads must
use the same recorded exact-required release mode. Compatibility-mode health
returns unavailable if it sees an active or malformed cutover database, so a
post-cutover replica accidentally configured `false` cannot appear healthy.

## Activation failure and recovery

- If the activation command errors before commit, its marker and audit roll
  back together. Keep processes stopped, preserve only minimized diagnostics,
  correct the understood blocker in a restored rehearsal, and rerun forward.
  The required-exact configuration intentionally keeps organizer policy closed
  and public readiness unavailable during this state.
- If the full authorization `0007`/audit `0006`/authorization `0008`/
  organizations `0013`/workforce `0005`/authorization `0009` boundary is
  installed but no marker or reserved audit exists, database-selected
  compatibility remains
  available only while the required-exact setting is `false`. The cutover
  release's `true` external fence instead keeps organizer policy closed and
  public readiness unavailable. The reciprocal audit guard and latch helper
  reverse only from the exact pristine dormant state and only after rehearsing
  the full graph and respecting authorization `0006`'s issuance downgrade
  fence.
- If a marker or reserved activation audit exists, never reverse authorization
  `0009`, organizations `0013`, workforce `0005`, authorization `0008`, audit
  `0006`, or authorization `0007`; never delete or truncate
  evidence, disable guards, fake a migration, or deploy an old reader/writer.
  Fix forward with
  compatible code. If forward recovery cannot preserve the history, restore
  the **whole** database and application to one mutually consistent
  pre-activation point after an explicit data-loss decision.
- Never turn the required-exact setting off merely to make a partial or damaged
  post-cutover restore appear healthy. Returning to a complete pre-cutover
  release, database, and `false` configuration is allowed only as the explicit
  whole-system restore/data-loss decision described above.
- If the marker committed and only asynchronous work or audit sealing remains,
  replay from durable records; never recreate authority or activation merely to
  force delivery.
- If post-cutover readiness becomes blocked because a pinned controller source
  legitimately ended, do not remove the marker. Restore needed responsibility
  through a new independently approved authority record and retain the ended
  lineage as history.

The deployment record must retain the release, migration plan, pre/postflight
counts, backup/restore evidence, synthetic correlation identifiers, database
role proof, and any fix-forward decision. It must not retain credentials or
production personal data.
