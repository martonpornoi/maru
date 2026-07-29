# Effect worker runbook

Status: Executable local baseline  
Last updated: 2026-07-27

## Scope and safety boundary

This runbook covers Maru's transactional outbox worker for INT-002, INT-003,
AUT-002, and NFR-004. The canonical database transaction is already committed
before the worker runs. Never repair a delivery problem by rewriting its domain
event, attempt ledger, audit evidence, or outbox status directly.

A failed external effect can be retried. A disputed canonical fact requires its
own domain correction workflow. Urgent real-world safety action never waits for
this queue.

## Process topology

Run at least one supervised process per configured workload pool:

```powershell
uv run python src/manage.py effects_worker --pool core
```

Add one supervised process for every additional pool introduced by a vertical
slice; never have a general worker silently consume an unknown pool. The process
supervisor restarts unexpected exits. One worker rotates fairly across eligible
tenant queues in its pool. Each delivery runs in a disposable child process
with these default boundaries:

```text
handler execution deadline: 30 seconds
child hard timeout:          40 seconds
database lease:              60 seconds
```

Keep `execution timeout < hard timeout < lease`. A hard-killed child leaves a
processing lease, not a fabricated result. The delivery becomes eligible after
lease expiry and recovery records the lost attempt.

For a finite local drain:

```powershell
uv run python src/manage.py effects_worker `
  --pool core `
  --stop-when-idle `
  --max-cycles 1000
```

## Tenant-safe diagnosis

Always start with an explicit organization and pool:

```powershell
uv run python src/manage.py effects_status `
  --organization ORGANIZATION_UUID `
  --pool core

uv run python src/manage.py effects_metrics `
  --organization ORGANIZATION_UUID `
  --pool core
```

The status command can act as a scheduled quarantine check:

```powershell
uv run python src/manage.py effects_status `
  --organization ORGANIZATION_UUID `
  --pool core `
  --fail-on-quarantine
```

Metrics expose stable series for message status, attempt outcome, oldest ready
age, oldest expired-lease age, and replay count. Organization UUID and workload
pool are the only labels. Event payload, person, destination detail, and error
text are deliberately absent.

## Baseline alert definitions

Thresholds are starting values and tighten for a declared live-edition window.

| Alert | Planning threshold | Live threshold | Severity | First action |
| --- | --- | --- | --- | --- |
| Security pool ready age | over 60 s for 2 min | over 20 s for 1 min | SEV-2 | confirm worker and database health |
| Default pool ready age | over 5 min for 10 min | over 2 min for 3 min | SEV-3 | inspect pool saturation and child failures |
| Expired processing lease | any age over 120 s | any age over 60 s | SEV-2 | confirm supervisor is reclaiming work |
| Quarantined delivery | count above zero | count above zero | SEV-2 | classify poison input/provider state before replay |
| Worker child failure | three in 5 min | one in 2 min | SEV-2 | inspect safe error code and release correlation |
| Replay growth | ten in 1 h | three in 15 min | SEV-3 | stop replay loop and reconcile root cause |

Deduplicate by organization, workload pool, alert kind, and release. Do not use
message or person fields as metric labels. Link alerts to authorized detail
tools using opaque correlation identifiers.

## Quarantine and replay

1. Confirm exact tenant and workload pool.
2. Inspect status, attempt outcomes, release history, and handler-safe error
   code.
3. Determine whether retry can duplicate an ambiguous external success.
4. Correct poison configuration, adapter behavior, or provider availability.
5. Confirm the handler uses the domain-event UUID as its idempotency key.
6. Grant the operator `effects.replay` through the normal authority workflow.
7. Replay one exact message with a concrete reason:

```powershell
uv run python src/manage.py effects_replay `
  --organization ORGANIZATION_UUID `
  --message OUTBOX_MESSAGE_UUID `
  --actor operator@example.invalid `
  --reason "Provider incident resolved and reconciliation found no delivery." `
  --additional-attempts 3
```

The command fails closed across tenant boundaries and emits a correlation ID.
Verify the corresponding allow/error/deny audit and observe the new attempt.
Do not batch-replay until one representative message succeeds and provider
reconciliation is current.

## Failure injection rehearsal

In a local/test environment:

1. publish or use a synthetic registered event;
2. configure its test handler to return a permanent failure;
3. run a finite worker and confirm quarantine plus a permanent-failure attempt;
4. run `effects_status --fail-on-quarantine` and confirm non-zero exit;
5. repair the handler;
6. replay through the authorized command;
7. drain once and confirm succeeded state, append-only attempts, and replay
   audit.

The automated integration suite covers poison payload, transient/permanent
failure, hard timeout, expired lease, replay, and tenant isolation. A release
rehearsal records the observed timestamps and operator rather than copying
payload content.

## Recovery validation

Recovery is complete only when:

- ready and expired-lease ages return within objective;
- quarantined work is explained or deliberately left for review;
- provider-side idempotency/reconciliation finds no duplicate harm;
- canonical domain and audit integrity checks pass;
- affected user-facing state is current; and
- the incident record links release, correlation IDs, operator actions, and
  follow-up owner.

Database recovery uses
[`rehearse-db-recovery.ps1`](../../scripts/rehearse-db-recovery.ps1), which
restores only into the guarded `maru_restore_drill` namespace, validates
representative tables, and cleans up the isolated database.
