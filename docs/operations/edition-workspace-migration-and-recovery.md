# Edition workspace migration and recovery

Status: Required deployment procedure; production rehearsal pending
Last updated: 2026-08-01
Scope: organizations `0005`–`0007`, events `0006`–`0009`

This runbook covers the M1 schema change that introduces convention-series
profile versions, edition aggregate versions, append-only edition-creation
receipts, a 31-day edition-span constraint, and PostgreSQL integrity triggers.
It is not a production approval. Rehearse it against a restored, representative
database before handling production personal data.

## Why a maintenance window is mandatory

Old and new application nodes are not write-compatible:

- old series writers do not advance `profile_version`;
- old edition lifecycle writers do not advance `aggregate_version`;
- new code depends on append-only creation receipts and the new constraints;
  and
- the database triggers correctly reject mixed-command or version-skipping
  writes.

Stop every web, worker, scheduler, management-command, and integration writer
before applying the migrations. Do not use a rolling deployment for this
change. Keep reads unavailable too unless the deployment topology can prove
that no old process can write.

## Change summary

| Migration | Durable effect | Reverse implication |
| --- | --- | --- |
| organizations `0005` | Add `ConventionSeries.profile_version`, default 1 | Dropping it loses concurrency state |
| organizations `0006` | Guard stable organization/slug and exact profile-version movement | Removing the trigger also removes this database defense |
| organizations `0007` | Fence destructive downgrade while any convention series exists | Only an empty workspace can traverse the guarded reverse path; populated recovery uses fix-forward or approved backup/PITR |
| events `0006` | Add `EventEdition.aggregate_version`, backfill it to at least `lifecycle_version`, verify language/currency bounds, create scoped creation receipts, and add 31-day span check | Backfill has no automatic reverse; dropping receipt/version data can lose committed control history |
| events `0007` | Guard stable edition scope/slug, separate profile/lifecycle commands, aggregate monotonicity, editable lifecycle, and append-only receipt scope | Removing triggers removes these defenses |
| events `0008` | Require the receipt request digest to be exactly one lowercase SHA-256 value at the database boundary | Reversal removes this defense while leaving receipt scope and immutability intact |
| events `0009` | Fence destructive downgrade while any edition or creation receipt exists | Only an empty workspace can traverse the guarded reverse path; populated recovery uses fix-forward or approved backup/PITR |

## Preconditions and ownership

Name a deployment operator, database/recovery operator, incident decision
owner, and application verifier. Record the build commit, database identity,
backup/PITR position, migration plan, start time, and communication channel in
the deployment record.

Before the window:

1. Verify a recent backup and perform a restore rehearsal in an isolated
   database. A backup that has not been restored is not evidence of recovery.
2. Confirm sufficient PostgreSQL capacity and that no long transaction will
   hold the affected tables.
3. Run the read-only span preflight:

   ```sql
   SELECT id, starts_on, ends_on
   FROM events_eventedition
   WHERE ends_on > starts_on + INTERVAL '31 days'
   ORDER BY starts_on, id;
   ```

   The result must be empty. Do not silently clamp or rewrite historical
   dates. Correct every result through an approved, evidenced data-recovery
   change before migration.
4. Run the read-only collection-size preflight:

   ```sql
   SELECT id, cardinality(language_codes), cardinality(currency_codes)
   FROM events_eventedition
   WHERE cardinality(language_codes) > 16
      OR cardinality(currency_codes) > 8
   ORDER BY id;
   ```

   The result must be empty. The migration additionally validates every stored
   currency against its pinned ISO 4217 allowlist and aborts with a bounded
   count if any code is unsupported. Prove that check on the representative
   restored database; correct unsupported historical codes through an approved
   recovery change rather than weakening or faking the migration.
5. Check the exact plan and drift from the release source:

   ```powershell
   uv run python src/manage.py showmigrations organizations events
   uv run python src/manage.py migrate --plan
   uv run python src/manage.py makemigrations --check --dry-run
   ```

6. Confirm the full M1 test/schema/document gate passed for the release commit.

## Apply

1. Enter the announced maintenance window and stop all application writers.
2. Confirm the target database URL and build identity without printing
   credentials.
3. Capture the final backup/PITR marker and current migration list.
4. From the new release source, apply migrations:

   ```powershell
   uv run python src/manage.py migrate
   ```

5. Do not restart an old build if migration succeeds. Continue only with the
   aggregate-version-aware release or a forward fix.

The events migration intentionally aborts with bounded counts if any existing
edition exceeds the span limit, language/currency collections exceed their
bounds, or a currency is outside the pinned allowlist. A preflight abort is safe
to investigate; do not bypass it with fake migration state.

## Verify before reopening writes

Run:

```powershell
uv run python src/manage.py showmigrations organizations events
uv run python src/manage.py check
uv run python src/manage.py makemigrations --check --dry-run
```

Then verify the database invariants with read-only queries:

```sql
SELECT COUNT(*) AS invalid_series_versions
FROM organizations_conventionseries
WHERE profile_version < 1;

SELECT COUNT(*) AS invalid_edition_versions
FROM events_eventedition
WHERE aggregate_version < GREATEST(1, lifecycle_version);

SELECT COUNT(*) AS overlong_editions
FROM events_eventedition
WHERE ends_on > starts_on + INTERVAL '31 days';

SELECT COUNT(*) AS oversized_code_collections
FROM events_eventedition
WHERE cardinality(language_codes) > 16
   OR cardinality(currency_codes) > 8;

SELECT COUNT(*) AS mismatched_receipts
FROM events_editioncreationreceipt receipt
JOIN events_eventedition edition ON edition.id = receipt.edition_id
WHERE receipt.organization_id <> edition.organization_id
   OR receipt.series_id <> edition.series_id;

SELECT COUNT(*) AS invalid_receipt_digests
FROM events_editioncreationreceipt
WHERE request_digest !~ '^[0-9a-f]{64}$';
```

All counts must be zero. Successful events `0006` application also proves that
every migrated currency was in the pinned ISO allowlist. In an isolated smoke
tenant, verify:

1. Page 5 opens and a changed series save increments profile version once.
2. A no-op series save increments nothing.
3. Page 6 creates one Draft edition with aggregate version 1.
4. Repeating the same browser retry or API `Idempotency-Key` reuses it; changing
   the payload conflicts.
5. Page 7 changes one profile field and increments aggregate version once.
6. A lifecycle transition increments aggregate and lifecycle versions in the
   expected independent sequence.
7. Audit, domain event, and outbox rows are correlated and contain no entered
   profile values.
8. The platform administrator still has no organization membership,
   participation, registration, or workforce assignment.

Only then restart the new web and worker release, observe readiness/error/outbox
signals, and reopen traffic.

## Failure decision tree

### Migration has not committed

Keep writers stopped. Preserve the exact error and migration state without
request payloads or credentials. Correct an overlong-record preflight or other
understood cause through an approved forward data fix, then rerun. Escalate an
unexpected partial DDL state to the database/recovery owner; do not use
`--fake`.

### Migration committed, but no new application write occurred

Keep the window closed and prefer fixing forward. The downgrade fences refuse
mechanical reversal whenever any convention series, edition, or receipt exists,
including records that predate this migration. For a populated database, use
the approved pre-window backup/PITR recovery path only after proving that no
post-backup canonical writes exist and recording the data-loss/reconciliation
decision. Only an actually empty workspace can traverse the guarded reverse
path.

### Any new M1 write occurred

Do **not** deploy old application code or attempt to bypass the downgrade
fences. New series
versions, edition aggregate versions, and creation receipts are now canonical
control history; an automatic downgrade would lose semantics and allow unsafe
writes. Keep the compatible release in maintenance mode, prepare a reviewed
forward fix, and restore from backup only under the incident/recovery plan with
an explicit data-loss/reconciliation decision.

### Application or outbox failure after reopening

Disable affected writes and retain canonical rows. The application transaction
ensures a failed required publish does not leave a partial mutation. Inspect
safe correlation IDs, readiness, database health, and outbox state. Follow the
[effects worker runbook](effects-worker-runbook.md) for delivery recovery; do
not edit domain events or receipts.

## Evidence to retain

- release commit/build identifier and migration plan;
- named operators and maintenance timestamps;
- backup/PITR reference and restore-rehearsal result;
- preflight and postflight counts;
- migration output and Django checks;
- synthetic smoke result and correlation identifiers;
- worker/readiness observation; and
- any incident, forward fix, reconciliation, or rollback decision.

Do not retain database passwords, raw idempotency keys, entered profile values,
or production personal data in the deployment record.
