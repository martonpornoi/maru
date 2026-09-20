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

## Second exhaustive attempt: schema inventory and clock-bound evidence

Candidate `71898fd4ea87cbb3529e337c4c93d3308edaeaa4` (tree
`36adb9ee8e9a8d4ca4b79ba2b8133748010b636b`) used source-bound plan
`39e5be172e4ffcd165d42829e530270666ad3be636c28726bddfc765a34dba81`:
53 shards, 351 groups and 106 historical groups, at most eight databases.
All non-database gates passed; exact-head units passed 11,789 cases in 187.37s
under load. Shards 1–9 passed in 452.703–996.625 seconds with measured headroom
and cleanup, including the earlier shard-9 conversion fixture repair.

Shard 14 failed one exact Department foreign-key inventory assertion (138 passed)
in 824.43s, owned duration 834.968s. Native catalog inspection confirmed that the
test omitted two accepted successors: `authorization_programmerolerequest` and
`events_programmeadoptionsetupreceipt`. Add those exact Department references;
retain the independent native current-contract, target-column and safe-delete
checks. Do not accept an arbitrary observed inventory or weaken its closed set.

Incremental shard-11 evidence also records four role-schema failures before the
pool cancelled it. Earlier retained logs include the same decision-time guard
failure in an actual public command, not only raw fixture inserts. Application
wall-clock values are compared with database transaction/clock timestamps by
the native guard. A deliberate host-clock-offset regression is being run before
repair; the earlier passing reruns did not resolve this contract mismatch.

The failed pool cancelled active shards 10–13 and 15–17 and removed every owned
container; an empty Docker inventory was verified. Preserve the entire artifact
tree under `.tools/certification-evidence/programme-postgresql-71898fd-failed`
and the outer `.tools/issue102-certification-71898fd.log`. No full success receipt,
combined coverage, push, hosted acceptance or merge is claimed.

### Clock and Department-reference repairs

The deliberate pre-fix native probe reproduced all six host-clock-offset cases
(request followed by approve/decline/cancel, clock one day ahead/behind). Its
other failure confirmed that merely updating the test inventory was insufficient:
the installed `maru_workforce_department_fk_contract_is_current()` also returned
false. The run retained 63 passing/seven failing cases in 174.14s, owned duration
178.484s, under `.tools/issue102-native-a79af8e1ce9c4691bb0f52d07f08f387`;
the owned container was removed.

Role commands now sample aware PostgreSQL `clock_timestamp()` inside their
transaction for request/decision evidence and deadlines, matching the native
guard clock. Invalid/unavailable database time has no host fallback. The native
time bounds and exact assignment/audit/person/source conditions are unchanged.
Direct guard fixtures use an independently queried database timestamp; four
additional negative cases retain rejection of pre-transaction and future intent.
Public-command skew cases check real requests and all three decisions, while
eight units cover valid/malformed/unavailable database-clock results.

The still-unpublished Workforce 0028 is extended to replace only the existing
Department-reference function with its closed 21-reference successor. It adds
the two exact accepted references, retains metadata/owner/ACL/search path, and
runs the shared used-evidence preflight before any reverse SQL or recorder change.
Released historical migrations are untouched. Current readiness requires 0028
and function fingerprint
`6f17d789d9762f24b0b4f3adc284d81a4444d83a8c6cdbe186a8260dd2058761`;
the source-derived predecessor fingerprint exactly reproduced the previously
observed value before deriving the successor. Actual metadata still needs native
verification. Unknown references and cascading known references have explicit
negative native regressions; this is not a permissive observed-schema allowlist.

Complete unit feedback passed 11,798 cases in 69.17s with three existing warnings;
strict typing and semantic Python documentation passed. Native role/schema and
recovery/unsafe-reference reruns are underway before freezing another candidate.

The repaired role/schema batch passed all 153 cases in 263.59s (owned duration
267.938s), under `.tools/issue102-native-ae83da15e923441883fa9abc48da7af4`.
It confirms all six public-command clock-offset cases, invalid timestamp denials
and the actual successor fingerprint/current native Department contract. The
recovery/unsafe-reference batch passed 21 cases in 473.92s (owned duration
478.703s), under `.tools/issue102-native-35594c84572d4d329e349a6da54d0e97`.
Unknown relations and cascading known references are rejected; empty full-graph
reversal and retained-record refusal still pass. Both containers were removed.

Inspection found the same bounded-time assumption in the related Volunteer
starter commands. Apply the same owner-local database-clock contract there,
retaining all native guards and adding six real approve/decline/cancel skew cases
and eight malformed/unavailable-clock units. The existing application-expiry
probe now overrides its explicit clock seam, not global host time. A final native
starter/required-migration-marker batch and complete units are running before the
next clean candidate. No released migration or timing/coverage threshold changes.

Final starter/required-marker feedback passed all 28 cases in 185.03s (owned
duration 189.453s), under
`.tools/issue102-native-4fcf45e6e9944df09b6eed24dd76246e`. This includes all six
starter clock-offset decisions and refusal when the new 0028 recorder marker is
missing. The container was removed and the Docker inventory is empty. Complete
units passed 11,806 cases in 67.05s; Ruff/format, strict typing, NumPy/semantic
documentation and all repository docs passed. Freeze the repaired candidate for
the next exhaustive exact-head attempt against unchanged protected main. No
focused or prior-commit evidence is being promoted to a full success receipt.

## Third exhaustive attempt and exact truncate-guard probe repair

The exhaustive candidate `32158f9688ebc465fb5fcccac79542e15943b51e`, tree
`4c251fb945bac028fbf4b1303549e7e2d806eade`, used the unchanged base and plan
`9b65bd09302946ee71a452e313d9636f21557b0d9af4734f58c7e70c9b9122f4`.
Non-database gates and all 11,806 units passed; units took 189.01s under concurrent
load. Shards 1–39 passed, each with measured headroom and verified cleanup. The
longest was 2,980.781s (49m41s), not a hosted measurement or runtime guarantee.

Shard 41 then failed one Workforce structure-integrity test, with 14 other cases
passing. The single-table TRUNCATE probe was rejected by PostgreSQL's FK preflight
because the later `events_programmeadoptionsetupreceipt` now references the
Workforce receipt. It did not reach the intended native immutability trigger.
This is a stale test setup, not permission to remove the FK, relax the trigger,
accept any database error, or truncate real data. The corrected probe explicitly
names those two receipt tables, keeps the test-reset exemption off, requires the
Workforce-specific immutability message and SQLSTATE `23514`, and asserts the
original receipts are unchanged after rollback.

The pool canceled shards 40 and 42–47; 48–53 never started. All 47 owned
containers were removed. The complete failed tree is preserved at
`.tools/certification-evidence/programme-postgresql-32158f9-failed`, with outer log
`.tools/issue102-certification-32158f9.log`. No success receipt, final combined
coverage, push, hosted acceptance or restored protected-main gate is claimed.

Focused uninstrumented native feedback passed all eight Workforce integrity
cases in 170.99s (owned duration 175.422s), under
`.tools/issue102-native-e5b9a0f69fe345f891f836d3346a64b0`; cleanup was verified.
Ruff and formatting passed. To expose remaining debt before another expensive
full run, all 14 unfinished exact shard selections are being diagnosed without
coverage, with four isolated databases at a time. The runner revalidates unchanged
group assignments against the repaired source. These diagnostics retain every
selected current/history case, fail on skipped cases, and cannot emit a full
certification receipt. Fresh complete exact-head acceptance remains mandatory.

All 14 unfinished selections passed under
`.tools/issue102-remaining-7af40b40bd1a4def878cc48a14d0f21e`: 1,494 selected native
cases, zero failures/errors/skips, every owned database removed. The diagnostic
plan `bf33935f08b6eb3deb38a098ddc98e96f5b4972bad7420bc53a03e1f3a50651d`
retained the same 53 assignments and every current/historical case. Diagnostic
owned durations were 988.593–1,504.547s without coverage and with four workers;
these are not eight-worker instrumented headroom or full certification. No
additional defects were found. Complete units passed again (11,806 in 79.10s,
three existing warnings), along with Ruff/format, documentation validation and
diff whitespace checks. Remote main remains the exact original protected base.
Freeze this repaired candidate for a new complete exact-head run; none of the
partial or uninstrumented observations is reused as a success receipt.
