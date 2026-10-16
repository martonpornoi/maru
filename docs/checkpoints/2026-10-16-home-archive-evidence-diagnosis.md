# Administration-home certification: archive evidence diagnosis

Date: 2026-10-16
Status: Failed certification preserved; focused diagnosis prepared

Auto certification of `b22a58747df3ef7c1a450edcb5add31bc9069bbf` against
`19eadfe05b6d56af11b9bc837b44af17aa095c0c` failed after 2,751.625 seconds.
All 14,285 units and 21 database batches passed. Batch 22 had 150 passing cases
and a setup error in `test_cancelled_claim_cannot_publish_bytes_when_generation_resumes`.
Seven other active batches were interrupted by pool fail-fast. They are not
passing batches or separate product failures. All 29 owned containers are absent.
Complete failed local evidence is retained in a 4,488-file hash-verified archive.

The error was `Programme archive lifecycle lacks exact current audit evidence`
from the native event guard while `request_programme_archive` recorded its queued
event. The guard enforces real timestamp bounds and exact Audit/witness/actor/
scope/operation identity. The command already obtains time from PostgreSQL, and
the failure traceback alone does not identify a false predicate. No causal link
to the home UI changes has been established. ADR 0109, AUD-001/AUD-003, QRY-006
through QRY-008 and the Programme archive contract remain unchanged.

The bounded diagnostic replays precisely the 151 original batch node IDs on one
fresh owned PostgreSQL database, with all original tests and native guards.
An ignored diagnostic observer adds read-only SELECTs before queued lifecycle
inserts, emitting only predicate booleans, relative time intervals and test names.
It neither repairs nor replaces evidence, authority, timestamps or guard results.
The observer and runner join the exact source inventory. Extra queries may alter
timing, so even a pass would not prove a repair or replace exact certification.
All earlier failed evidence remains preserved. No dormant Programme workflow is
activated and no demo coverage is added or claimed by this diagnostic.

## Observed replay result and bounded follow-up

All 151 original cases passed in 497.02 seconds, 503.656 including the wrapper
and exact owned cleanup. The before/pre-pytest/after source inventories match
`664f161c68431266c4d36421de5c3a395b550c56afd024321fd8a48343acd233`.
All 26 artifact hashes match. All 20 observed queued events had true audit and
time predicates; no event insertion failed. The exact container is independently
absent. No matching Windows system clock-change event was found in the failed
certification interval; this does not establish Docker clock stability.

The cause remains unconfirmed. The next bounded run removes all observation
SELECTs and replays the unchanged original batch with the one cancellation case
parametrized 40 times: 150 other cases plus 40 original cases, 190 total. Ordinary
fixtures reset for each repetition, and the test body and native guards are
unchanged. An ignored, source-pinned collection plugin supplies only the unused
repetition parameter and refuses unexpected collection counts. No retry-on-failure
or suppression is used: the first failure stops the diagnostic and is retained.
This is focused intermittent-failure investigation, not a changed production
contract, new activation, demo-coverage extension or success receipt.

## Repetition result and acceptance decision

The no-observer run passed all 190 cases in 604.13 seconds, 610.953 including
the wrapper and owned cleanup. This includes all 40 independent fixture runs of
the unchanged original cancellation regression and the 150 other batch cases.
The before/pre-pytest/after inventories match digest
`74177068e0e038017cdc370ce612cad7d509073ca9dcc120c0f63d529e50eb07`;
all 25 artifact hashes match and the exact created container is independently
absent. There were no failures, errors or skipped tests. No SQL observations,
failure retries, guard changes or source-test changes were used in this run.

The evidence supports an unreproduced intermittent rejection, not a claimed
cause or repair. The next acceptance step is one deliberate fresh complete Auto
certification of the clean candidate with normal eight-worker concurrency and
all unchanged gates. This exercises the setting absent from the focused serial
diagnostics. No permission, audit witness, timestamp bound, migration, coverage,
worker count or timing budget is changed to obtain acceptance. A recurrence
requires preserving and inspecting the new evidence before further action;
success would not retroactively turn the earlier failure into passing evidence.
The PR must retain this limitation honestly. Demo behavior remains unaffected.
