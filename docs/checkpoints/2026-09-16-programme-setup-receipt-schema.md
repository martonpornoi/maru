# Dormant Programme setup receipt schema (#108)

Requirement mapping: IDN-011/012, EVT-001/002/006/007, HR-009, UX-020/030 and
NFR-013 under ADR 0081. This implements the retained-evidence part of accountable
setup, not its command, UI, operator approvals, integrated fixture or activation.

Events migrations 0012–0014 retain exact setup intent and scope, original edition
and Department creation receipts, representation provenance and matching audit.
Native guards enforce supported receipt shapes and same-scope evidence, current
platform actor, first Department and new Programme edition; both current profiles
remain unchanged and cannot receive such receipts. History is append-only with
anti-truncate protection and serialized used-evidence downgrade fences. The
application role is SELECT-only and ordinary ORM writes remain closed.

The domain-neutral integrity inspector now also supports explicit purpose-specific
owned relations. Its default whole-app behavior is unchanged. The subset must be
nonempty, unique, actually owned and exactly covered by primary attachments; it
cannot omit a same-owner supporting attachment. All actual native attachments on
the selected table are still compared exactly, including unexpected duplicates.
Events independently pins the full receipt shape and schema/fence sources. This
result does not claim whole-Events readiness or actor permission.

## Approved schema-only observation

The maintainer explicitly approved one bounded disposable migration/metadata check
while keeping PostgreSQL suites deferred. On PostgreSQL 17.11, pinned image digest
`18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73`, forward
migration and catalog observation completed in **201.704 seconds (3m22s)**.
The task-only container used loopback port 62054, two CPUs, 1 GiB memory and tmpfs
storage, with a ten-minute process deadline, 120-second statement limit and
ten-second lock timeout. It did not use a production database, runtime grants,
profile activation, fixture journey or PostgreSQL test runner.

The complete receipt relation fingerprint observed was
`8f7eed1463c6214ec8b5153fcc67856cd4f96dc24cdcd111892d599941183ab5`.
Every source/native catalog field was current, including migration recorders,
trigger attachments, function definitions, ownership and execution privileges.
A separate data-free recheck of the pinned wrapper returned true. This is metadata
evidence, not proof of constraint negatives, races, replay, reverse migration or
workflow correctness. The exact labelled task container and temporary database
were removed afterward; observation logs were retained. No user containers or
persistent volumes were removed.

## Feedback and remaining debt

Focused units initially exposed that the shared integrity builder expects one SQL
operation. The guard and used-evidence fence were separated into 0013/0014 without
loosening that source check. Corrected focused feedback passed 59 tests; after
source-pin coverage, full database-free feedback passed **9,141 tests in 70.25s**
with three existing Django URL-field deprecation warnings. Ruff, strict types and
NumPy docstrings passed; semantic documentation passed 715 Python source files.
The initial migration-preview command used the wrong root entrypoint; the actual
`src/manage.py` preview and drift check completed with no changes detected. Its
unreachable-database warning is not native acceptance.

Twenty-seven maintained native scenarios remain uncollected and unexecuted under
#102: exact metadata/receipt, both current-profile denials, wrong owner/evidence
references and intent/state shapes, immutable row/truncate protection, populated
fences and empty reverse/reapply. The positive receipt fixture temporarily admits
one exact candidate pair inside its rollback transaction and reuses real foundation
commands. Its deliberately limited Workforce-derived manifest is schema-test
scaffolding, not the complete Programme manifest, a runtime-role proof or integrated
acceptance; no policy is replaced with always-allow and no native guard is disabled.
The empty reverse/reapply is explicitly inventoried as historical; all other cases
remain current. Diagnostic file cost uses the existing 29.955-second median estimate,
not measured execution; authoritative new groups retain the largest-known fallback.

Fresh clean exact-commit certification and protected hosted delivery remain pending.
Next implement atomic setup through public owner locks/commands, actual actor/key
replay and rollback boundaries, independently approved operational authority and
guided genuine-person continuation, then the real isolated fixture. #108 and final
#102/#97/#92/#109 gates remain open.
