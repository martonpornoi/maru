# Current project state

Last updated: 2026-09-24
Phase: Progressive adoption and pre-production release evaluation.

Maru is a Django/PostgreSQL modular monolith under synthetic evaluation, not a
production-ready release or supported hosted service. This file is the concise
handoff; [ROADMAP](ROADMAP.md) owns sequencing, [checkpoints](../checkpoints/index.md)
preserve history, and the [production ledger](PRODUCTION_CONSOLIDATION.md) retains
the release baseline.

## Protected baseline and testing policy

[PR #199](https://github.com/martonpornoi/maru/pull/199) delivered the combined
Programme exit/recovery/isolation bundle at protected squash
`be83a5764d2d6aac887615ce0d498e237e94fc27` on 2026-09-24. Its tree equals certified
head `e4b449480ab632962805bea87f3741a76f27a64d`; clean local main and `origin/main`
were synchronized to that squash. The feature branch and unrelated worktrees
remain preserved. The follow-up records that milestone and repairs #200's native
test-fixture clock ordering; it does not certify itself or activate Programme.

[PR #195](https://github.com/martonpornoi/maru/pull/195) previously restored
required PostgreSQL acceptance and archive-purpose authority; #102 remains closed.
Its 53 local/hosted shards and exact-head gates passed. Keep its
[protected evidence](../checkpoints/2026-09-20-postgresql-restoration-protected-delivery.md).
Earlier PostgreSQL deferral is historical, not current permission.

Follow [local certification](../development/local-certification.md): focused
feedback, complete inexpensive units, then clean exact-commit required acceptance
with `CI=true`, pinned pnpm 11.9.0, unchanged coverage and measured headroom.
Preserve artifacts before replacing `.local-ci/`; at most eight native databases
may run concurrently. Require exact-head protected checks, resolved conversations
and match-head squash; verify equal trees and fast-forward clean main. No bypass.

## Combined Programme exit and isolation bundle

PR #199 is merged; #189/#190/#97/#175/#196/#197/#198 are closed. It delivers:

- #189: independent eight-owner archive, complete lineage/original clean files,
  requester-bound asynchronous custody, limits, expiry/cancellation and dormant UI.
- #190: seven-owner minimized stop preview, exact intent/retry, separate withdrawal
  authority, atomic terminal receipt/audit/event, owner fences and historical UI.
  Shared authority and retained volunteer work are not silently revoked/completed.
- #196/#197: genuine invitation-writer cutover and exact native Maru-operator lineage.
- #175/P06: independently approved starter and native Programme assignment evidence
  without Participation; genuine-person acceptance remains separate.
- #198: fresh bounded native policy observations reduce on-site output latency
  without policy caching, wider fields or increased HTTP deadlines.
- #97: unchanged readiness after active/stopped logical restore, immutable bytes
  and partial-backup refusal under ADRs 0113/0114.
- #109/P12: independently approved selected-room delivery fields, all seven
  nonempty subsets, immediate same-session revocation, actual foreign/sibling
  object POST denials between successful owner controls, plus the existing
  49-response scope matrix and 97-table excluded-owner observer.

The isolated overlay remains Events 0019, with 88 explicit writable relations,
thirteen invoker validators and one existing narrow definer helper. Production
ACLs/profiles are unchanged. Additive Events 0016–0018 retain stop proof and
fence partial reverse migration before joined durable evidence loses protection.
Applied migrations and independent authority are not rewritten.

Use the [P01–P12 evidence map](../operations/programme-acceptance-evidence.md),
[executable rehearsal](../operations/programme-integrated-rehearsal.md),
[archive runbook](../operations/programme-exit-archive.md) and
[setup contract](../product/page-contracts/programme-operations-adoption-setup.md).

## Exact-head protected acceptance

The [protected delivery checkpoint](../checkpoints/2026-09-24-programme-exit-protected-delivery.md)
records full local acceptance at `e4b4494`: **13,306 units, 5,079 PostgreSQL cases
across 71 shards, 103 frontend cases and 91.74% combined coverage**, all ten gates,
in **3h50m50s**. Every native job passed measured headroom and owned cleanup.

Independent [hosted acceptance](https://github.com/martonpornoi/maru/actions/runs/35929623040)
passed all 71 shards, combined coverage and the protected PR gate in **4h39m44s**.
All 72 Python reports total **18,385 cases**, with zero failures, errors or skips;
combined coverage is **91.74%**. Hosted shards ranged **6m01s–60m36s**, median
**18m49s**, leaving at least **59m24s** before the unchanged two-hour limit.
[CodeQL](https://github.com/martonpornoi/maru/actions/runs/35929590704) passed.
Two redirect findings were individually reviewed as false positives: fixed local
path prefixes and actual UUID route converters exclude caller-selected origins;
112 focused checks passed. The review evidence and dispositions are linked in the
checkpoint. No source suppression, security-rule change or protected bypass was used.

The eighteen-phase host-only journey and separate host/provisioning evidence below
remain precisely attributed; routine certification does not silently include them.

## Recovered supporting verification

The [2026-09-23 evidence checkpoint](../checkpoints/2026-09-23-programme-acceptance-recovery.md)
records results recovered after the interrupted session:

- Full certification at `ef7b17743b183f2875d015381e9ba836f181f02a` passed all ten
  gates in **3h35m02s**: **13,222 units, 5,079 native cases across 71 shards,
  103 frontend cases and 91.74% combined coverage**. No native failures/errors/skips;
  every database was removed and every shard had measured headroom. Slowest shard
  **41m32s**. Preserved complete receipt:
  `.tools/certification-evidence/programme-exit-ef7b177-success`.
- The expanded populated journey at
  `c063f70731b43574c0b7263f7564c8fd24e87a6c` passed **all eighteen phases /
  1,336.35s**, including connected field/object isolation and both logical restores.
  Its complete fast units passed **13,306 / 82.76s** with three existing warnings.
  Failed initial launch and successful retry remain separate evidence.
- Separate retained host checks at `ef7b177` finished **14 passed, one failed /
  2,073.58s**. Exact reproduction confirmed a stale expected error: schema-only
  runtime correctly refuses missing helper execution before inactive authority.
  The test now expects that exact refusal only for schema-only mode; the writer
  mode still requires the later inactive-authority refusal. Production code,
  permissions and readiness checks are unchanged. All three modes now pass
  against fresh owned databases: **3 / 596.93s**, no skips.
- The prepared isolation commits are now folded into the exit branch, avoiding
  separate full certifications for two related PRs. The old successful receipt
  does not certify this changed bundle. Complete fast run43 passes **13,306 /
  90.94s**, with the same three warnings; Ruff and documentation validation pass.
  The subsequent combined exact-head certification and protected delivery are
  recorded above; earlier receipts do not substitute for that new result.

Earlier failed full attempts and their fixes remain in checkpoints: the
[retained-authority fence](../checkpoints/2026-09-21-programme-retained-recovery-verification.md),
[scope expectation](../checkpoints/2026-09-21-programme-scope-guard-expectation-repair.md)
and [composition repairs](../checkpoints/2026-09-21-programme-native-composition-test-repairs.md).
Do not erase failures or combine them into a false exact-head success.

## Follow-up clock-fixture verification

#200 records a test-only repair exposed by the documentation-only `9b3add6` Auto
run: six custody cases used Windows scan timestamps ahead of PostgreSQL and
correctly hit its unchanged future-scan refusal. The failed evidence is preserved.
Native fixtures now observe the database clock and add explicit future/pre-call
negatives. The original 77-case group plus both new cases passed **79 / 256.46s**,
with owned cleanup verified. Production scan time, database guards, clock settings
and CI policy are unchanged. The [clock checkpoint](../checkpoints/2026-09-24-programme-custody-fixture-clock.md)
records the failure and focused proof; final exact-head acceptance belongs to the
follow-up's protected PR, not an inherited PR #199 receipt.

## Next actions and remaining closure gates

1. Complete #109's joined evidence with #92's genuine representative-person,
   screen-reader and materially changed browser observations. The
   [participant cards](../operations/programme-human-acceptance.md) supply tasks and
   an evidence form, not a human pass.
2. #97 and #102 are delivered. Only after #92/#109 also pass, implement and
   separately verify #108's final profile
   promotion. Close #48 only when the decomposition and integrated criteria pass.

The browser rejected the temporary HTTPS certificate before login
(`ERR_CERT_AUTHORITY_INVALID`). An approved trusted rehearsal origin and actual
independent participants remain necessary. No TLS bypass or machine trust change
was made. Preserve unchanged #87/PR #90 native Cancel, actual 200% Chrome zoom,
visible keyboard focus and the user's disabled Windows Animation effects.
Pinned HTTP/parsed HTML and synthetic actors do not supply human acceptance.

Real twenty-minute process expiry and deployment workload/capacity are not yet
proved; archive Python-tracked peak is not RSS. Production/PITR, supervision,
privacy/safeguarding, training and go/no-go remain separate gates. No production
profile, routes, deployment or data have been activated.

## Continuation boundaries

Previously merged Programme children must not be restarted; their history is in
checkpoints and Git. Keep `programme_operations@1` limited to Applications,
Programme, Scheduling, Venues and Workforce plus required foundations. No
Registration, Participation, payment, attendance, Logistics or general
Communications effects. Owning commands, independent approval and purpose-specific
authority remain mandatory. Notice acknowledgement is not provider delivery or
acceptance of replacement work; signed fallback remains historical read-only.

Unattended bundled delivery and protected merge are authorized, single-agent.
No new schedules, policy bypass, production deployment or broad Docker cleanup.
Preserve unrelated worktrees/stashes/resources; remove only verified task-owned
resources. Applied stashes `5b6851f` and `dd651ef` must not be reapplied;
preserve unrelated `3cc5df` / `9fecfe`, the #96 repair checkout and both isolated
P12 checkouts. The prepared P12 source is folded into this branch, not lost.

After #48, continue #42 and the director-introduction/pilot package, then agreed
guidance/accessibility and continuity/succession priorities. #22/#23/#24 remain
Workforce-owned. The semantic docstring validator's no-argument string/Path defect
remains separate; maintained explicit `src scripts` invocation passes.
