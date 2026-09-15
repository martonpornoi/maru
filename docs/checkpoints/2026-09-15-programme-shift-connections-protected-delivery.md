# Programme staffing-to-Shift: protected delivery

Date: 2026-09-15
Parent: #108 under #48; both remain incomplete.

## Exact protected result

[PR #133](https://github.com/martonpornoi/maru/pull/133) squash-merged at
06:48:09 UTC as `13a51848c78330b636cf35d9f65e3916eb2a136a`.
Certified head `eeee0af9646ebf4db3884b432fba98e1a285b0b5` and protected squash
share tree `a1803b4d1d584d6325a7eb5597d3f8d8bb913971`. Clean local main and
origin/main were fast-forwarded to that exact result. The detached repair worktree
was checked clean and untouched; unrelated stashes and containers were preserved.

Fresh exact head/base, ready state, CLEAN mergeability, green PR gate and CodeQL,
and the complete empty review-thread set were verified before ordinary
`--squash --match-head-commit` delivery. No bypass or acceptance exception.

## Local evidence

All eight retained canonical gates passed on the first clean run in **18m07s**
(1,087.324 seconds). Units: **7,624 passed in 45.13s**, with three existing
URLField warnings; JUnit contains 7,624 tests, zero failures/errors/skips and
45.003 seconds. Frontend: **93 passed**, also confirmed in hosted logs.
The [implementation checkpoint](2026-09-15-programme-shift-connections.md) records
iteration, the repaired empty-panel fallback and limited synthetic browser evidence.

Schema-4 receipt completed at `2026-09-15T06:18:16.1970867+00:00` with
`postgresql_deferred`, zero database instances, and null combined coverage and
measured PostgreSQL headroom. Policy SHA-256 is
`36354f14eabc58fa31ae7b2d7ec0e9a5e7afb8ab2c4b48bfa02a1edeff5f528d`.
Five source/copy hashes were compared while archiving the receipt, plan, JUnit,
wheel and source distribution in
`.tools/certification-evidence/issue108-eeee0af-deferred/`.
Receipt SHA-256:
`03bb97933226e75fd69f8e2c17c85cde5b79c93f2e1ed86947db64a05b470b63`.

## Hosted evidence

Exact-head [workflow 34936403918](https://github.com/martonpornoi/maru/actions/runs/34936403918)
passed without repair or rerun:

- Units: **7,624 in 69.53s**; job **1m33s**.
- Quality: **27m44s**, 06:19:31–06:47:15 UTC.
- Documentation: **25m36s**, 06:20:37–06:46:13 UTC.
- Frontend: all **93 tests** across seven files passed.
- PR gate: passed in **3s**; separate CodeQL aggregate and all three analyses passed.
- Workflow latency: **28m09s**, 06:19:12–06:47:21 UTC.

The observed **2m16s** quality margin is not guaranteed future headroom. #113
records it without displacing unblocked #48 work. No timeout or CI policy changed.

## Bookkeeping and limits

#108's nested staffing connection is checked; #108 and #48 were verified open
after delivery. One existing native scenario remains unexecuted #102 debt
([record](https://github.com/martonpornoi/maru/issues/102#issuecomment-5675489397));
human tasks remain #92
([record](https://github.com/martonpornoi/maru/issues/92#issuecomment-5675489565)).
No profile, schema, runtime grant, lifecycle command or production route changed.
No native PostgreSQL, complete responsive/human, integrated #109 or recovery #97
acceptance is implied.

Next: guided #104 source/recipient selections and connections, recorded inside
#108's existing obligation before implementation. #107 continuity, Applications
references/safe files, accountable setup and final mandatory gates remain unfinished.
