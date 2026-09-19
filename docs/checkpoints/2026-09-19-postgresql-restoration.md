# PostgreSQL restoration and coherent Programme delivery bundles

Date: 2026-09-19. Issue #102 within #48. Status: authorized local candidate;
not yet protected delivery or complete native acceptance.

## Authority and unchanged boundaries

The maintainer explicitly requested restoration now, followed by larger coherent
PRs containing related #48/subtask outcomes. This supersedes the earlier sequencing
that deferred execution until all P11/P12 preparations were finished. Existing
ADR 0100 defines restoration by returning the tracked mode to `required`; ADRs
0090/0098, NFR-001/002/003/008 retain complete selection, bounded concurrency,
source-bound local/hosted assignments, timing headroom and 90% combined coverage.
No profile, production deployment, release, omitted test or bypass is authorized.

The candidate starts from protected `42c50e497bc6cfffa399725ad5845617149709c0`
and includes prepared archive authority `04dc33621902e00fd24765a8bfe552a8da305751`.
That related boundary is verified in the restoration rather than sent through a
separate small PR. A bundle closes an issue only when all its acceptance is met.
Keep complete archive/exit, accountable stop-use and integrated isolation/recovery
as coherent future outcome boundaries; do not gather unrelated work just to
increase PR size. Focused feedback precedes final exact-commit certification.

## Accumulated verification inventory

Compared with the last full feature-only baseline
`ff36db6896a0ff0d073e9737086d676f5a8d1e30`, 27 integration test files changed
and 19 migration files were added/changed through the prepared archive component.
The review covers these owner boundaries, not merely a count of merged PRs:

| Area | Native debt to execute |
| --- | --- |
| Applications | Actual private file custody, clean-state/retention/byte read, intake/service and review/decision authorization, accepted-item conversion. |
| Authorization | Notice capabilities; retained operational role requests, exact recipes, real two-person decisions/audit, room authority, archive purpose, native scope/downgrade and runtime-role safety. |
| Events | Atomic Programme setup, retained receipts, schema/guard readiness and used-boundary downgrade refusal. |
| Programme | Layered current/history reads, full pagination, host privacy, retired staffing, independent placement streams and actual core/item/placement collection. |
| Scheduling | Candidate and release command/read behavior, notice persistence/recovery, public/personal/operator output and coherent release-derived projections. |
| Workforce | Accountable starter records, claims/confirmation and retained work, own timetable and no Participation side effects. |
| Cross-owner | Tenant/edition/field denial, final audit, lock ordering, stale inputs, replay, rollback, historical migration recovery and the full runtime-role boundary. |

The exhaustive inventory retains every other module as well. The two new archive
MigrationExecutor cases are explicitly historical under Authorization/Programme;
all unlisted tests remain current behavior. No test is omitted by file naming or
cost. Before execution, the reviewed source plan has 351 groups (106 historical)
and 53 shards, at most eight running concurrently. Old weights/fallbacks predict
roughly 59 minutes per shard including slowdown/overhead; these estimates are not
fresh observed runtime or push readiness. Complete measured headroom is required.

## Initial verification

Policy unit feedback: 30 passed in 0.35s. Complete database-free feedback:
11,774 passed in 68.82s with three existing Django URL-field warnings.

The first native diagnostic used one fresh, loopback-only PostgreSQL 17.11
container with a random run/owner identity, tmpfs storage and a 1,900-second
independent lease. Four selected archive scope/recipe/fingerprint/unused-reverse
and retained grant/bundle downgrade cases passed in 171.17s; full owned-resource
duration was 175.547s and exact cleanup was verified. Initial schema setup took
162.89s; individual calls took at most 1.37s. This includes real migration and
metadata observations, not production/runtime-role or integrated acceptance.

Evidence remains under `.tools/issue102-native-206a0b9ef89944a09481788a38cb31b6`.
No credential is recorded here. A second bounded diagnostic covers retained role
approvals, Programme reads and new archive collectors. Full exact-head local and
hosted acceptance, coverage, fresh timing calibration if needed and protected
merge remain pending. Keep #102/#108/#48 open until their actual gates pass.

## Native restoration repairs

Preserve failed diagnostic attempts rather than treating database-free delivery
as native acceptance. Initial role/query collection exposed a tuple passed to a
string profile fixture, an inconsistent same-organization foreign-edition
factory, and a query authorizer lacking the mutation audit obligations needed by
the public-copy withdrawal command. Starter fixtures omitted the real exact-
edition `workforce.manage_structure` grants and the exact starter catalog entry.
Corrections use existing public grants and transaction-local candidate metadata;
no production authority, manifest or native guard is widened.

Retention probes now flush pending deferred constraints and turn off the test
database's cleanup-only exemption inside their rolled-back transaction. They
assert the actual append-only/truncate guard error, not a pending-trigger error.
The unused starter guard round-trip passes SQL with `params=None` so PostgreSQL
`%ROWTYPE` declarations are not interpreted as client placeholders.

The next batches retained 156 passing/5 failing cases in 352.02s (owned duration
356.359s, directory suffix `927fb5a4d9e44a80bdc884990223569a`) and 94 passing/4
failing cases in 287.89s (owned duration 292.125s, suffix
`a3b038145fd4449cbadde47903f292e6`). Both owned containers were removed. Their
failures drove the retention and SQL-execution fixture repairs above and the
real optional-answer repair below. Two earlier role decision timestamp failures
did not repeat with read-only diagnostics, so an uninstrumented rerun and full
certification are still required; no timestamp guard has been weakened.

### Optional answer clearing (PRG-009)

Actual file custody acceptance exposed a model-validation mismatch: the public
typed command permits clearing an optional answer, and the existing database
column permits null, but `ApplicationAnswerRevision.value` rejected that value
during `full_clean`. Set `blank=True` alongside the existing `null=True` and
record it in new Applications migration 0022. It is validation state only, not
a data rewrite or change to native constraints, privileges, source fingerprints,
required-answer sealing or typed command validation. Reversal restores the old
validation state without deleting rows; use compatible corrected code when
retaining newly cleared answers.

Seven field-validation regressions cover canonical empty values and meaningful
false/zero answers; the model contract file passes 32 cases in 0.25s. The actual
custody regression now also checks a new empty revision, version advancement and
unchanged earlier revisions, alongside retained bytes and unavailable current
file disclosure. Complete native acceptance and exact-head certification remain
pending. This is a related restoration repair, not a separate small PR.

## Repaired candidate feedback

The uninstrumented combined role/starter/setup/file-custody batch passed all 171
cases in 414.34s, owned-resource duration 418.641s. Evidence is retained under
`.tools/issue102-native-7bb36f5330e14bca803dcf0044c34160`; exact container removal
and no remaining diagnostic containers were verified. The prior timestamp
failures did not recur; this observation does not establish their root cause or
replace exhaustive acceptance. A separate 1,000-sample, no-schema clock probe
observed database timestamps up to 5.11ms later than host response timestamps;
its owned disposable container was also removed. No time guard was relaxed.

Complete repaired units passed 11,781 cases in 78.58s with the three existing
Django URL-field warnings. Ruff/check-format, NumPy/semantic documentation and
repository docs passed. Migration autodetection found no missing model-state
changes; its unavailable default database consistency check was a warning, not
native migration evidence. The native batch above applied the actual new graph.
Remote main remains the protected base recorded above. Freeze this candidate for
full certification, preserve the preceding PR #194 receipt/artifacts outside
`.local-ci`, and do not push until complete measured acceptance supports it.

## First exhaustive attempt: retained failure, not a timeout

Candidate `c7461f964a2bfd40d62117aa826bb42d3bc57737` (tree
`7ba03fc33d844651f563734fd71c60960cc49960`) ran exhaustive certification with
plan fingerprint `111ddfffbd7ba3188af8a03acfaca864ab020674a44e246fb3beb7b15d0973b4`.
Packaging, dependency audits, Ruff, strict typing, documentation/NumPy/semantic
checks, warning-fatal Sphinx, frontend and contract gates passed. All 103 frontend
cases passed; the exact-head 11,781 units passed in 215.73s under concurrent load.

Shards 1 through 8 passed with measured cleanup-inclusive durations of 496.593 to
1,056.015 seconds, all with sufficient conservative headroom. Shard 9 failed four
conversion-entry cases (51 passed) after 638.797 seconds; it did not time out.
The pool then cancelled active shards 10 through 16 and did not dispatch the rest.
Every owned container was removed, and an empty Docker inventory was verified.
There is no success receipt or complete combined coverage result.

Preserve the entire failed artifact directory at
`.tools/certification-evidence/programme-postgresql-c7461f9-failed`, and the outer
log at `.tools/issue102-certification-c7461f9.log`. No prior evidence was overwritten.

The conversion fixture patched only the task entry's profile-admission function,
while the real Applications authorizer independently required that same adapter.
Replace those disconnected boolean patches with one isolated exact manifest
consumed by both owners. Preserve actual persisted grants, missing-grant and
missing-adapter denial, real policy and audited empty results. This changes only
the fixture, not production admission. Broader accumulated native feature batches
precede the next full exact-head attempt so additional debt is found sooner.

## Broader native debt and recovery-order repair

The repaired conversion/review batch passed 115 cases in 517.16s (owned duration
521.672s). The runtime retry-ACL and notice-migration batch passed eight cases in
282.66s (owned duration 288.453s). Host/staffing/placement/shift coverage passed
124 cases and failed four in 897.58s; scheduling/release/operator/personal output
coverage passed 217 and failed two in 1,449.70s. All four task-owned containers
were removed. These are diagnostic results, not whole-repository acceptance.

The four recovery failures exposed a real graph-order defect: reversing older
Programme migrations removed Workforce 0025–0027 recorder entries and starter
guards before the existing shared execution fence rejected retained evidence.
New Workforce 0028 depends on starter 0027 and Scheduling 0022 and invokes both
frozen preflights before any successor reverses. It adds no SQL objects and does
not rewrite historical migrations. Starter readiness requires and source-pins
the new marker. Entirely unused boundaries remain reversible; any retained
starter or shared execution evidence requires fix-forward or consistent recovery.
Keep the existing unchanged-recorder and unchanged-guard assertions intact.

Five graph-order units and three preflight-order/short-circuit units supplement
the actual retained/unused migration regressions. The focused source/model unit
file passes all 31 cases. Native reruns remain required at this checkpoint.

The two output failures were stale fixture contracts. Scheduling's exhaustive
table inventory now includes both notice tables, and the real notice lifecycle
checks their populated raw-update/delete rejection rather than merely excluding
them from the matrix. Personal-output fixtures now use one isolated adoption
manifest for all real owner checks, preserving actual grants, independent source
permissions and audit. No current production profile is broadened.

### Focused repaired recovery acceptance (2026-09-20)

All 19 starter and selected host/staffing/placement recovery cases passed in
534.93s (owned duration 539.703s). Evidence is under
`.tools/issue102-native-a264d372b9724c268e83a585b16f056e`; its owned container
was removed. This includes the four previously failing unchanged-recorder
regressions, the fully unused host reverse/reapply and all native starter cases.
Complete unit feedback passed 11,789 cases in 82.30s with three existing warnings;
Ruff, strict typing and NumPy/semantic/repository documentation checks passed.

The release/planning raw-write matrices and all three real operator-notice scope
variants passed in the companion run. Its subsequent personal-output setup
failed because the test registry is immutable; replace that registry within
the test scope instead of mutating its mapping proxy. The retained attempt is
`.tools/issue102-native-5c25c3da00fc4b55b6c32550f12f1acf` (five passed,
ten setup/teardown errors, 299.02s; owned duration 303.422s and container removed).
The corrected personal-output file is being rerun independently. This is a
test-fixture correction, not a production permission or manifest change.

The corrected personal-output run passed all 18 cases in 369.95s (owned duration
374.422s), including actual private HTML/print/JSON/calendar owner rechecks.
Evidence is under `.tools/issue102-native-8c7bf2944bbb4675ad945a66f7d1154a`.
Its container was removed and an empty Docker inventory was verified. Remote
main remains `42c50e497bc6cfffa399725ad5845617149709c0`. Freeze the repaired
candidate for exhaustive exact-head certification; focused results do not waive
that gate, combined coverage, measured headroom or independent hosted acceptance.
