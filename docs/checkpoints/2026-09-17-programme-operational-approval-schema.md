# Dormant Programme operational-approval storage (#108)

This is the retained-evidence prerequisite of #108's accountable setup item under
#48, not a new product or a completed approval workflow. It implements ADR 0106's
storage boundary for IDN-002/004/005/012/014, EVT-006/007, AUD-001 and NFR-013.
The maintainer resumed work with approval for necessary bounded disposable
schema-only checks, keeping PostgreSQL suites deferred until final #102 acceptance.

## Outcome and boundaries

Authorization owns immutable `ProgrammeRoleRequest` and one terminal
`ProgrammeRoleDecisionRecord`. Exact context/target, people, recipe contents,
interval, rationale, actor/key identity and privileged audit are retained.
Approval alone links one exact newly issued canonical RoleAssignment and its
immutable RoleBundle. Decline/cancel cannot carry a grant. Native checks retain
independence, current owner scope/people, the seven-day deadline including lock
waits, non-backdated start, unchanged requested end and exact actual-actor audit.
Existing authority issuance remains the lineage mechanism.

Migrations 0032–0034 add the two tables, four triggers and five owner-only,
fixed-search-path invoker functions. Storage and downgrade source are pinned;
readiness additionally verifies exact relations and native attachments/ACLs without
private-row reads. Runtime provisioning and its exact tested inventory keep both
tables SELECT-only and add no executable-function allowance. Direct ORM save/delete
is refused; native tests deliberately use bulk insertion only to probe guards.

No public command, protected reader, API, route, event/outbox producer, grant,
profile admission or production permission is introduced. Current profiles and
both representation roots are unchanged. Canonical command-level authorization,
locking/replay/rollback/concurrency and genuine own-session action remain next work.
No private test data, external messages or unrelated Docker changes were made.

## Schema and recovery observation

The approved final **empty forward migration and metadata-only** observation used
PostgreSQL 17.11 Alpine image
`sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73`.
It had a ten-minute process deadline, 120-second statement and ten-second lock
timeouts, two CPUs, 1 GiB memory, bounded tmpfs data and loopback-only port 58668.
The finalized run completed in **153.156 seconds** with every native catalog flag
true and the pinned readiness wrapper true. Observed relation fingerprints:

- request: `dffe250128cc2459f2457cf7a612111e339b26627aa868d80b3401324dad842d`;
- decision: `ce773dc6573d27c9e3c44e13777ad9d5a29fc326c83e835292835d491a91fe32`.

The preliminary source check rejected a combined SQL/Python migration before
database work. The existing separate terminal-fence pattern resolved that without
weakening readiness. A first 159.485-second observation preceded the final
post-lock expiry check; it is superseded, not claimed as current guard evidence.
The finalized migration ran fresh on a new empty disposable database. Both exact
labelled task containers were stopped/auto-removed with their temporary databases;
local logs remain. No persistent/user volumes were touched.

This is **not** native behavioral, populated rollback, unused reverse, concurrency,
runtime-role, logical recovery or workflow acceptance. Both tables are locked
before unused-only reverse. Once either retains evidence, preserve it and fix
forward; never delete intent, fake recorders or disable guards. Restore must retain
owner references, canonical authority and audit lineage. #97 logical recovery is
still mandatory and no changed fingerprint may be blindly accepted.

## Verification and maintained debt

Focused database-free schema units passed **23 cases**. Full feedback initially
found two missing inventories (diagnostic file cost and exact runtime read-only
relations). Those and the provisioning example were updated. Corrected complete
feedback passed **9,321 units in 55.00 seconds**, with three existing Django URL
deprecation warnings. Ruff, strict mypy (700 source files), NumPy contracts and
semantic docstrings (721 files) passed. Static migration drift reported no changes;
its deliberately unreachable database warning is not native verification.
The final provisioning parity test also covers these two tables and the existing
setup receipt; combined focused schema/runtime feedback passed 36 cases in 0.38s.

`tests/integration/test_programme_role_schema.py` maintains exact metadata, genuine
controller-backed grant linkage, existing foreign-scope denial, both current-profile
denials, invalid intent/people/interval/output, actual-actor decisions, uniqueness,
retained update/delete/truncate guards, populated downgrade, weakened readiness and
unused reverse/reapply. It remains **uncollected and unexecuted** under #102. The
setup schema's limited transaction-local candidate was moved into shared test
support; it retains real policy/guards and rolls DDL back with rows. It is not the
complete Programme manifest or integrated acceptance. Existing setup cases also
remain deferred. Only unused reverse/reapply is historical in the new inventory.
The old diagnostic file map uses its existing **29.955-second median estimate**,
not measured runtime; authoritative new groups retain the largest-known fallback.

Fresh clean exact-commit development certification and protected hosted delivery
remain pending at this checkpoint. Those results must remain separately identified
from the schema observation and future PostgreSQL acceptance. Then continue actual
independent-approval commands, guarded readers/continuation, guided setup and the
complete isolated fixture. #108/#48 and #102/#97/#92/#109 remain open.
