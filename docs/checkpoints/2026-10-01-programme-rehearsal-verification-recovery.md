# Checkpoint: Recovered verification and complete joined Programme rehearsal

- Date: 2026-10-01
- Phase: Programme acceptance preparation; #203 delivery remains pending.
- Related requirements: NFR-001/002/003/005/013, SCH-011/012, UX-007/029.
- Related ADRs: 0063/0064, 0081, 0090, 0098, 0113/0114/0115.

## Outcome

The full populated Programme rehearsal passed all eighteen phases at clean
`0d2a3aa5c862e70f2741cceb6aedc0f03b2042af`, on protected base
`314d593dc98fde705e834ef6374d001d25051942`. This verifies the composed fixture
after planning began granting its existing independent hosting prerequisite and
the notice stage stopped requesting that same grant again. No production
permission, duplicate-grant refusal or separate-account approval was relaxed.

This is native automated evidence, not a human/browser pass or whole-commit
certification. The preceding interrupted certification remains incomplete.

## Recovered interruption

The September 27 certification at `0d2a3aa` lost its tool host. On October 1 no
associated process or `maru-cert-*` container remained. The retained incremental
pool log contains 52 closed results: 47 successes and five abrupt nonzero exits
(shards 55, 49, 54, 50 and 51, each exit 1073807364). Three other started shards
have no final record. The matching abrupt exits are consistent with the host
interruption; they do not establish five assertion defects or timeouts.

All 52 recorded results report owned-container removal and timing headroom. The
slowest successful shard took 2,518.593s (41m59s). The exact-head unit process
passed 13,457 cases in 180.01s, and the non-database gates and 103 frontend cases
had passed. Neither `pool-result.json` nor `certification.json` exists. Passing
subsets cannot be combined into a success receipt.

Before any reset, all 4,495 surviving `.local-ci` files were copied into
`.tools/certification-evidence/programme-local-0d2a3aa-interrupted/local-ci` and
compared individually using SHA-256. A sibling `sha256-inventory.csv` records
paths, sizes and hashes; the original console log is also retained. The earlier
interrupted `1e61a5e` and complete `243e264` evidence remain separate and untouched.

## One-shot process handling

A task-local PowerShell wrapper pins the clean candidate/base and writes console
output and start/finish metadata to a fresh ignored directory. It invokes the
ordinary rehearsal or certification command, with no retries, Git writes,
scheduler, service, acceptance-policy change or synthesized receipt. Its probe
completed after the launching shell exited. No app restart or reboot was tested;
do not claim power-loss resilience.

The first joined launch failed before collection because its report-path argument
was split incorrectly. It ran no tests, returned a nonzero status, and remains
preserved at `.tools/programme-203-joined-20261001`. Correcting only that ignored
wrapper argument produced the separate passing run below; tracked source stayed
clean at the same exact head throughout.

The maintainer separately approved a temporary 30-minute chat check-in for #203
through verified protected merge, then deletion. It is not an OS test scheduler
and does not extend fixture leases or keep the machine running.

## Joined native verification

Command: repository Python, `-m pytest tests/rehearsals/programme_proposal_native.py
-q -p no:cacheprovider`, with a fresh JUnit destination, explicit isolated opt-in,
fresh run identity, original 3,600-second lease and isolated real-scanner refresh.
No certification pool ran alongside it.

- Result: **1 passed / 1,265.44s (21m05s)**; zero failures, errors or skips.
- JUnit records **18 passing phase properties**: proposal, review, items, planning,
  physical approval, staffing, release, change notices, on-site output,
  delivery-layer isolation, continuity, scope isolation, object-mutation isolation,
  archive, active logical restore, incomplete-backup refusal, stop, stopped restore.
- The actual resource identity was `dc8d2841bc3443e4bb98254abbd1475b`, allocated by
  the test rather than inferred from the initial environment value.
- The worker ran from 16:10:49 to 16:31:57 UTC and exited 0. On readback its
  processes, exact database/scanner containers and scanner volume were absent;
  the matching owned certificate directory was absent too. Cleanup was normal;
  no unrelated resources were removed.
- JUnit: `.tools/programme-203-joined-20261001-r2/rehearsal.xml`;
  SHA-256 `7d481fb29646826e2568dc5ef2e13a0c0f098ed81c97f4616e947d17990b3346`.
  Console and start/finish metadata are retained beside it.
- Archive generation took 15.438s for 157,233 bytes; Python-tracked peak allocation
  was 2,865,419 bytes. This is not RSS, production capacity or a deployment test.

The documentation follow-up's complete database-free feedback passed **13,457
unit tests / 78.30s**, with three existing Django URL-field warnings. Documentation
validation passed for 703 Markdown files, four repository skills and 215 requirement
identifiers; changed-rehearsal Ruff checks and diff whitespace checks passed.
These are pre-commit feedback, not the final exact-commit receipt.

## Data, migration and deployment notes

Only disposable fictional data and genuine restricted native fixture roles were
used. No new migration, production profile, runtime grant, route, external delivery,
machine trust or browser setting changed. Interrupted evidence remains recoverable.
The local-certification guide now explains one-shot logging and interruption
recovery without establishing a second verification system.

## Remaining work

Record this evidence, run the appropriate fast checks, then certify the final
clean #203 bundle through the unchanged exhaustive policy and protected GitHub
gate. The documentation-only follow-up does not require repeating this joined
run, but it does require fresh ordinary certification of the changed commit.
No push, PR, protected merge or successful certification is claimed here.

Keep #92/#109/#108/#48 open. Archive/stop and complete disconnected/native-print
browser tasks, specialist screen-reader use, independent people and operational-
owner acceptance remain separate. Preserve valid #87 evidence. Profile promotion
still requires its actual prerequisites or an explicit documented scope decision;
this checkpoint neither supplies nor waives them.
