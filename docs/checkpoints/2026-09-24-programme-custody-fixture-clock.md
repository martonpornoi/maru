# Checkpoint: Programme native custody fixture clock ordering

- Date: 2026-09-24
- Phase: Progressive adoption and pre-production release evaluation.
- Requirements: PRG-002, NFR-003, NFR-008, NFR-013 and AUD-001.
- ADRs: 0104–0105; no accepted behavior is reversed.
- Issue: #200, supporting #109 within #48.

## Reproduced failure

After the separately certified/protected PR #199 merge, documentation-only head
`9b3add6c5e2e04db1fc9260c63c895ffc95ce396` ran normal local Auto acceptance against
`be83a5764d2d6aac887615ce0d498e237e94fc27`. Its current-schema plan contained
30 shards, with no historical group. Unit/static/docs/contracts/frontend checks
passed, including 13,306 units / 173.24s and 103 frontend cases. Native shard 3
failed six of 77 cases in `test_application_programme_file_custody.py`; shard 1
passed and the remaining started jobs were stopped by the fail-fast pool. All
nine started database resources were removed. No certification success exists.

The complete failed artifacts are retained at
`.tools/certification-evidence/programme-delivery-9b3add6-current-failed`; the
transcript is `.tools/programme-delivery-record-certification-9b3add6.log`.
This does not invalidate or replace the distinct PR #199 exhaustive evidence.

The direct `_persist` fixture supplied `timezone.now()` immediately before its
intake INSERT. The unchanged native guard correctly rejects
`scanned_at > clock_timestamp()`. A bounded separate owned PostgreSQL diagnostic
sampled host time before each actual query: **1,000 of 1,000 timestamps remained
31.460–34.122 ms in the database future after transport**. Its exact container
was removed. This is observed clock ordering, not merely an inferred test order
or evidence that the native guard should be relaxed.

## Bounded repair

Only the direct synthetic fixture now observes PostgreSQL `clock_timestamp()`
for its scan value. All existing positive custody, partial-content/answer,
digest, source/scope, immutable-history and populated-fence assertions remain.
Two new native cases deliberately supply future and pre-call scan evidence;
both must be refused without partial receipt, intake, bytes or source-version
advance. No sleep/retry, machine clock change, test deletion, native guard
disablement, source fingerprint rebaseline or application timestamp change.

Actual preparation still records the real trusted scan observation; this fixture
does not certify a scanner or production clock synchronization. Operational
clock skew remains a fail-closed condition to diagnose, not permission to backdate
real evidence. Owning module and file-handling documentation record this limit.

## Verification and next actions

The exact original 77-case selection plus the two new negatives passed in one
bounded fresh owned database: **79 cases / 256.46s**, no failures, errors or skips.
Report: `.tools/programme-custody-group-1.xml`; the owning context removed its
exact container and independently verified its absence. Ruff/format, diff checks
and documentation validation passed (698 Markdown files, four repository skills,
215 requirement identifiers).

A new clean-head risk-selected local/hosted certification remains the delivery
gate and is recorded with the protected PR. Preserve the failed attempt and do
not credit the feature receipt to a changed test head. No production profile or
route is activated; #92/#109/#108/#48 remain open.
