# Programme archive private custody and dormant requester workflow

Date: 2026-09-20. Local continuation of #189 within #108/P11/#48; not a protected
delivery, final integrated acceptance or production activation.

## Outcome

Building on local owner/composition commit `06bb6b7`, the bundle now implements
Programme-owned requester tasks, immutable lifecycle evidence and private derived
chunk custody. Migrations 0020/0021 enforce coherent scope, immutable request and
generation identity, fixed database-clock expiry, exact state/version transitions,
native current Audit witnesses, capacity and complete chunk storage/disposal.
Unused reversal and the used-evidence fix-forward fence are exercised natively.
Actual PostgreSQL 17.11 schema metadata supplies 45 new constraint/index pins;
five guard functions and eight triggers extend the reviewed readiness contract.

Requests are exact-requester/edition and idempotent. Explicit cancellation retains
source/task evidence; deliberate retry creates a new linked request. Generation
claims separately then retains the whole owner closure through encoding, chunks
and ready evidence. A failed or interrupted process cannot commit partial custody.
The purpose worker has a real PostgreSQL single-worker session lock, finite DB
statement/lock timeouts and a supervised 20-minute child process limit. Subsequent
bounded cleanup fails stale running work without impersonating revoked people.
Request, generation, cancellation and retrieval transactions also bound DB waits.

Private inspection repeats all owner checks. Ready source drift blocks download,
while authorized metadata exposes the changed-source state so the requester can
cancel and replace the stale archive. Retrieval verifies every chunk and whole
ZIP before disclosure and checks expiry again after verification/audit. Access
expiry is not misreported as proof that worker disposal already ran.

The dormant shared-shell screen supplies preview, explicit acknowledgement,
request/status/cancel/retry and a fixed-name private/no-store ZIP. It has no shared
bearer link, directory, impersonation, automatic polling or public storage. The
page contract, operator runbook and module documentation state private custody,
scope omissions, resource/retry limits, inspection and recovery boundaries.

Production profiles and URLs remain unchanged. The three relations are SELECT-only
in actual runtime inventories/provisioning and the current isolated candidate.
No service/scheduler was installed or archive write privilege granted. Source-only
rehearsal baseline pins were updated after reviewing the exact added tables/guards;
this is not a native candidate runtime-role acceptance claim.

## Verification and retained failures

- Native custody/whole-owner workflow: **51 passed in 89.64s**,
  `.tools/programme-exit-custody-workflow-native-2.xml`. Covers complete private
  ZIP retrieval, current independent source denial, later source drift, exact
  requester/tenant, audit rollback, partial custody rollback, original idempotency,
  concurrent same-key requests, cancellation before resumed completion, excluded
  module invariance, real worker serialization, crash deadline and downgrade fences.
- Full corrected fast suite: **12,517 passed in 70.13s**, three existing Django
  URL-field warnings, `.tools/programme-exit-bundle-units-6.xml`.
- Focused UI/resource/worker/ACL batch: **98 passed in 1.25s**,
  `.tools/programme-exit-adapter-units.xml`.
- Reviewed schema/fixture regression batch: **193 passed in 2.01s**,
  `.tools/programme-exit-schema-adjacency-units.xml`.
- Documentation validation: 652 Markdown files, four skills, 215 requirements
  before this additional checkpoint. Focused mypy/docstring checks passed during
  iteration; final bundle-wide quality/coverage/certification is still required.

The initial native custody fixture used ordinary read-audit append rather than
the native audited-mutation witness. Correcting the fixture, not weakening the
guard, yielded 14/24 passing focused batches. The first full workflow drift test
omitted required withdrawal arguments; correction yielded eight passing cases.
An initial unit parameter embedded a large synthetic payload in its pytest ID;
short explicit IDs corrected that test-harness defect. Runtime provisioning tests
caught missing SELECT-only SQL inventory entries, which were added explicitly.

The first broad suite after schema additions returned 48 failures, seven setup
errors and 12,462 passes in 72.92s, preserved in
`.tools/programme-exit-bundle-units-5.xml`. These identified stale exact schema,
model-boundary, candidate read-only and source-fingerprint expectations. Reviewed
updates retain all old checks and add only the new exact schema. The subsequent
193-test and complete 12,517-test runs passed. Initial documentation validation
caught missing toctree entries; both runbook and page contract are now indexed.

## Remaining acceptance

This is a local component checkpoint in the larger archive/P11 bundle. It is not
exact-head certification, hosted acceptance, #189 closure or complete P11. Native
runtime promotion, resource measurement, integrated synthetic archive wiring and
actual browser observations remain. Full risk-selected local/hosted gates and
measured shard headroom remain mandatory before protected delivery. No human
observation, logical restore, P11/P12 acceptance or current profile activation is
inferred from ordinary tests. #190, #175, #108, #109, #97 and #92 remain on the
documented #48 completion path.
