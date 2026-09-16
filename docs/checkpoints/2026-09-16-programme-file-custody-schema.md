# Programme supporting-file custody schema

Date: 2026-09-16. Scope: a dormant persistence prerequisite beneath #108 / #48;
neither parent is complete. Base: protected PR #146, `4faef0f75979e61427f829ee4342cd24ad1593c3`.

## Contract and outcome

ADR 0105 selects Applications-owned private transactional byte custody for bounded
supporting PDFs. Metadata binds the exact proposal/question/uploader, original
proposal/call/schema versions, retry and scan time; a separate relation stores
immutable bytes. The existing answer command remains the sole proposal cursor and
success-evidence owner. Deferred guards require exact first answer/receipt and bytes
together. Later uses bind the same purpose/uploader; generic receipts alone cannot
fabricate Programme custody. Limits are 10 MiB per file, 64 intakes and 64 MiB per
proposal including history, serialized with the existing edition/proposal boundary.

Migrations 0019–0021 install schema, owner-only integrity functions and populated
contraction fencing. Existing unproven non-null Programme file answers or reserved
`programme-db/` keys make installation fail closed; no unverifiable backfill is
inferred. Both new relations remain runtime SELECT-only, and current profiles,
routes, roles and scanner settings are unchanged. No original filename, public URL
or quarantine copy is retained. Clear-answer is not deletion or hold release.

## Explicitly approved schema-only observation

The maintainer approved one bounded disposable migration/catalog check while
keeping PostgreSQL suites skipped. PostgreSQL 17.11 Alpine image
`sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73`
ran on loopback port 62052, with 2 CPUs, 1 GiB memory and 768 MiB temporary PGDATA.
The exact task-labelled container was removed afterward with its temporary data;
no other container or volume was removed.

- Whole fresh schema migration plus metadata collection: **150.437 seconds**.
- The three new migrations installed, reversed while empty and reapplied.
- Existing 455 constraints and 313 indexes retained their exact old fingerprints
  after excluding only the new relations and new receipt-custody constraint.
- New complete Applications catalog: 474 constraints,
  `9e65c723d031f87274dc574bb0eb5cee1aeb8741dce5f18d23873ef3c5f82b76`;
  324 indexes,
  `bb8f85fea9ef260d808431f319329271fbd9aab82ab1ca17ae546152e24d35d0`.
- All integrity, schema, ownership and execute-boundary facets passed;
  `applications_database_integrity_is_ready()` returned true.

This was not a PostgreSQL test run, native feature exercise, logical recovery
rehearsal, scanner deployment, runtime-role workflow proof or production approval.

## Verification and remaining work

Database-free tests cover model isolation/immutability, closed writers, migration
chain, native guard declarations, runtime provisioning inventory, readiness drift
and downgrade preflight. The initial complete unit pass caught two stale inventory
assertions; those were corrected without weakening acceptance. Fresh complete
feedback passed **8,681 units in 53.69 seconds**, plus Ruff/format and configured
NumPy/semantic docstring checks. Exact clean-commit eight-gate certification
precedes protected delivery;
the resulting receipt must say `postgresql_deferred`, not native success.

Twenty-eight native cases are maintained without collection/execution: canonical
first-answer custody/reuse, incomplete evidence rollback, wrong scope/actor/
question/versions, digest/length mismatch, untrusted receipt attributes, orphan
reserved key, cross-proposal reuse, native mutation refusal, populated fence and
unused reverse/reapply. The empty migration case is declared independently
restorable Applications history. The new diagnostic whole-file timing entry uses
the existing **29.955-second median fallback**, not a measurement; no authoritative
group timing, coverage, budget or headroom is claimed. #102 must run and measure
these plus exact quota/race, conditional-question, runtime-role and broader final
workflow acceptance; existing native coverage thresholds remain unchanged.

The next #108 increment must implement authorized pre-body admission, scan outside
the transaction, locked reauthorization, atomic upload-and-use/retry and the
independent exact-answer private reader, then visible selection/download journeys.
Anonymous omission must precede identifying lookup. #109 integrated isolation,
scanner/capacity/recovery and stop-use proof, #97 logical restore, #92 human
acceptance and governed retention/hold/disposal remain activation gates. No current
profile or live department may rely on this schema-only prerequisite.
