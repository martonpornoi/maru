# Synthetic OCI runtime rehearsal

Date: 2026-08-29
Issue: [#37](https://github.com/martonpornoi/maru/issues/37)
Parent evaluation: [#29](https://github.com/martonpornoi/maru/issues/29)
Requirements: OPS-008, NFR-001 through NFR-004, NFR-008, NFR-010 through NFR-013
Decisions: ADRs 0044, 0046, 0060, 0065; no new ADR

## Outcome

Maru now has one canonical, executable synthetic evaluator path for the first
immutable release candidate. It composes exact OCI/source identity,
PostgreSQL 17, migration-owner/runtime-login separation, the reviewed runtime
ACL contract, a minimal activation-compatible bootstrap, exact authority
activation, public health interpretation, ordinary stop/start, persistent
state, and sanitized evidence.

This closes the runtime-path defect found during the first candidate
evaluation. It does not change the immutable candidate, select production
infrastructure, or claim gold/production readiness.

## Implemented boundary

- `scripts/rehearse_oci_runtime.py` is a standard-library orchestrator with
  immutable digest validation, bounded subprocess/health deadlines,
  fail-closed source and SQL matching, exact resource namespaces, internal
  networking, no host ports, staged cutover/restart, label-verified cleanup,
  and schema-versioned count-only evidence.
- `scripts/oci_runtime_bootstrap.py` is streamed to the immutable image over
  standard input. It creates or verifies one deterministic `.invalid`
  platform administrator with an unusable password. It creates no organization
  or ordinary authority record and refuses all identity/state collisions.
- The PostgreSQL administrator, `maru_migration`, and `maru_runtime` receive
  three distinct generated credentials. Credentials live only in mode-`0400`
  Docker secret volumes or in-memory SQL standard input; they do not enter
  argv, environment values, URLs, output, evidence, or committed files.
- `maru_migration` owns the database/schema and applies migrations and the
  controlled cutover. `maru_runtime` is created by the reviewed exact-source
  SQL, owns nothing, receives only the positive data plane and exact negative
  control-plane contract, and is used through a genuine credential-bound
  connection rather than impersonation.
- The comprehensive `seed_demo_data` fixture remains the local educational
  path. It is explicitly excluded because its ordinary role/grant examples are
  not exact historical issuance evidence and would correctly block or fail an
  ADR 0044 activation.
- The runbook is linked from README, operations navigation, release process,
  deployment, readiness, development setup, demo-data, and testing guidance.

## Exact live rehearsal

The definitive local execution used:

- release candidate `v2026.08.27-rc.1`;
- application source
  `be0b21db9ba2d2a956bd192a1d66c537d702c4c4`;
- OCI digest
  `sha256:a44de03a4fe7bd5b3a5aaf73dd83b565b727a98bf895bf80416981e869eeb445`;
- PostgreSQL
  `postgres:17.11-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73`;
- exact-source provisioning SQL SHA-256
  `709f644dbea546351e210fd58c6fe5ee6a502882b0b94058c049412533f7b49e`;
  and
- sanitized ignored receipt run `6316f3c4a7d4`, from
  `2026-08-29T18:10:29Z` through `2026-08-29T18:13:22Z`.

All 16 stages passed:

1. both immutable images and the source/SQL/helper relationship verified;
2. isolated internal network, persistent data, and distinct secret volumes
   created;
3. 170 migrations applied by the migration owner with no schema drift;
4. the missing runtime-role reproduction returned live `200`, ready `503`,
   with only Logistics unavailable;
5. the reviewed runtime-role SQL applied without ownership or impersonation;
6. the runtime login created one non-login synthetic actor and zero ordinary
   authority or organization records;
7. dry-run/apply/replay backfill was idempotent, with activation ready,
   production blocked, and zero blockers before the marker;
8. compatibility mode through the genuine runtime login returned live/ready
   `200`, every dependency `ok`, and exact build identity;
9. exact mode before the marker returned live `200`, ready `503`, with only
   authority provenance unavailable;
10. activation ran with zero application processes, returned `activated`, then
    `already_active`, and produced production-ready postflight with zero
    blockers;
11. a fresh exact-mode Gunicorn pool through the genuine runtime login returned
    live/ready `200`, including authority and Logistics `ok`;
12. web stop/start preserved build identity and full readiness;
13. PostgreSQL stop preserved liveness and returned ready `503` with only the
    database unavailable;
14. database-before-web restart reused the persistent volume and restored full
    readiness;
15. migration replay reported no migrations, bootstrap replay returned
    `already_present`, and counts remained one account, one activation marker,
    one reserved activation audit, and 170 migrations; and
16. the final fresh pool returned complete synthetic readiness.

The receipt ended `result=passed` and `cleanup.status=removed`. A separate
label-filtered readback found no remaining container, network, or volume for
the run.

A second full run, `5289d9f67ebb`, ran from `2026-08-29T18:14:00Z` through
`2026-08-29T18:16:52Z` with `--retain-resources`. Its receipt ended
`result=passed` and `cleanup.status=retained_stopped`; the retained inventory
contained 19 containers with zero running, one internal network, and four
volumes. The standalone `--cleanup-retained 5289d9f67ebb` path then removed
that exact disposable inventory, and a separate label readback returned zero
containers, networks, and volumes.

## Automated verification

- `tests/unit/test_oci_runtime_rehearsal.py`: 37 tests pass for digest/source
  validation, exact SQL, deterministic resources, secret-safe pgpass, cutover
  ordering, top-level JSON parsing, evidence redaction, genuine-login
  environment, no host ports, container-loopback HTTP, exact minimized health,
  irreversible activation postflight, safe evidence location, static bootstrap
  input, fail-closed inventory, foreign-collision refusal, interrupted-job
  rediscovery, retained stopping, nonexistent-run refusal, and verified final
  cleanup.
- `tests/integration/test_oci_runtime_bootstrap.py`: four PostgreSQL tests pass
  in 62.16 seconds for first create, exact replay, unusable password, count-only
  output, zero authority/organization side effects, collision rollback,
  modified-actor refusal, and explicit synthetic-settings fence.
- The live rehearsal itself is the release-environment smoke. Existing
  integration coverage remains authoritative for the deeper role ACL matrix,
  exact catalog fingerprints, activation atomicity, genuine backend identity,
  guard tampering, and downgrade fences.

## Recovery and limitations

Default success or failure cleanup removes only exact run-labeled containers,
the internal network, the data volume, and three secret volumes. A retained run
is stopped and can be removed only by the explicit `--cleanup-retained` path,
which validates every label before irreversible synthetic deletion. No global
Docker prune or broad project deletion is used.

The evaluator path uses Gunicorn from the immutable image but selects
`maru.settings.local` to keep adapters synthetic. Neither Gunicorn nor
PostgreSQL is host-published; health is probed over container loopback. The
result does not cover static delivery (#38), production settings, edge/TLS,
external providers, supervised workers, representative restore/PITR, load,
accessibility, partner policy, or human acceptance.

## Smallest next action

Resolve [#38](https://github.com/martonpornoi/maru/issues/38) as its own exact
static-delivery topology/contract pull request without changing the runtime
authority evidence established here.
