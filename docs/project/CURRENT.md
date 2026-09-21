# Current project state

Last updated: 2026-09-21
Phase: Progressive adoption and pre-production release evaluation.

Maru is a Django/PostgreSQL modular monolith under synthetic evaluation, not a
production-ready release or supported hosted service. This file is the current
handoff; [ROADMAP](ROADMAP.md) owns sequencing and
[checkpoints](../checkpoints/index.md) preserve historical evidence.
The [production ledger](PRODUCTION_CONSOLIDATION.md) retains the release baseline.

## Protected baseline and testing policy

[PR #195](https://github.com/martonpornoi/maru/pull/195) restored required
PostgreSQL acceptance and delivered archive-purpose authority. Its protected
squash is `b056aa253a39df2648752daf35ac5a158a9950d7` (2026-09-20), with the
same tree as certified head `c018d99d71baa230c1bf2edd942c034740e995c7`.
Origin/main was refreshed and still equals that squash. #102 is closed and its
#48 checklist entry is corrected. Earlier PostgreSQL deferral is historical,
not current permission or instructions.

All 53 local/hosted shards passed: 4,592 native cases, 11,806 units, 103 frontend
cases, 91.53% local and 91.54% hosted combined coverage. Complete local acceptance
took 3h47m58s; hosted acceptance took 4h21m02s, with jobs from 6m50s to 57m03s.
Exact-head PR gate and all three CodeQL analyses passed. Preserve the
[protected evidence](../checkpoints/2026-09-20-postgresql-restoration-protected-delivery.md)
and `.tools/certification-evidence/programme-postgresql-c018d99-full` / hosted
artifacts. They do not certify later changes.

Follow [local certification](../development/local-certification.md):
focused feedback while developing, complete inexpensive units, then clean
exact-commit required acceptance with `CI=true`, pinned pnpm 11.9.0, unchanged
coverage and measured timing headroom. Preserve old artifacts before the runner
replaces `.local-ci/`. Keep at most eight native databases concurrently; the
planner's 128-shard cap changes neither concurrency nor per-shard time budgets.
Require exact-head protected checks, resolved conversations and match-head squash;
verify equal trees and fast-forward clean main after merge. No bypass or deferral.

## Local Programme exit bundle

Branch `codex/programme-exit-bundle` builds on PR #195. Its implementation and
latest verification changes are local, not fully certified, pushed or merged.
No production profile, routes, deployment or data have been activated.

Implemented in this coherent bundle:

- #189: eight-owner restricted exit archive, complete lineage and original clean
  files; separate source permissions; requester-bound asynchronous custody,
  bounded generation/retrieval, expiry/cancellation and dormant shared-shell UI.
- #190: complete seven-owner minimized stop preview; exact original intent;
  independent active-release withdrawal authority; atomic archived transition,
  immutable receipt/native audit/event, terminal owner fences and historical UI.
  Shared authority and retained commitments are not silently revoked or completed.
- #196/#197: genuine Identity invitation writer cutover and exact Authorization
  Maru-operator lineage fixes discovered by actual native startup.
- #175/P06: Workforce 0029's exact Programme assignment evidence without
  Participation; existing accountable starter and genuine-person decision remain.
- #198: bounded actual operator-output latency through fresh native policy
  observations, without policy caching, wider fields or a longer HTTP deadline.
- #97: unchanged native contract readiness after logical restore, including
  exact enum-cast/trigger rendering under ADRs 0113/0114 and partial-backup refusal.

The isolated migration overlay is 0019, with 88 explicit candidate writable
relations, thirteen invoker validators and one existing narrow definer helper.
Production ACLs and existing profiles remain unchanged. Events 0016 implements
the reciprocal native stop/receipt proof; unused reverse/forward succeeds and
used evidence fences downgrade. Source/metadata pins are maintained in their
owning code; never rebaseline a weakened live schema.

Events 0017 now extends the retained native-evidence fence over the whole joined
exit generation, before Events/Venues/Workforce successors can partially reverse.
Its no-op forward/reverse-only fence is source-pinned; existing applied migrations
are unchanged. The archive's independent native downgrade refusal is still tested.
Events 0018 now carries the other retained owner preflights across that join too:
authority (including revoked grants), setup, approval, starter, notices, archive and
domain history cannot lose newer guards before an older refusal. Its forward is a
no-op; focused native recovery and the complete populated continuation now pass.

Durable evidence and contracts:

- [Archive owners](../checkpoints/2026-09-20-programme-exit-owner-composition.md),
  [custody/workflow](../checkpoints/2026-09-20-programme-exit-custody-workflow.md),
  [native startup](../checkpoints/2026-09-20-programme-native-root-and-archive.md).
- [Latency correction](../checkpoints/2026-09-20-programme-policy-latency.md),
  [bounded populated journey](../checkpoints/2026-09-20-programme-bounded-native-journey.md),
  [pinned logical recovery](../checkpoints/2026-09-20-programme-pinned-logical-recovery.md).
- [Stop native closure](../checkpoints/2026-09-21-programme-accountable-stop-runtime.md),
  [HTTP/races/stopped recovery](../checkpoints/2026-09-21-programme-stop-http-races-recovery.md),
  [stop page contract](../product/page-contracts/programme-stop-use.md).
- [Integrated rehearsal and twelve checkpoints](../operations/programme-integrated-rehearsal.md),
  [archive runbook](../operations/programme-exit-archive.md),
  [Programme Operations contract](../product/page-contracts/programme-operations-adoption-setup.md).

## Latest executed evidence and limits

- Full certification at `e3635ab95574ec56ab5d9744f50755698e079458` stopped after
  approximately 2h21m on two stale native scope-error expectations in shard 55.
  The new stop guard correctly rejected the malformed parent pair before the older
  item guard. Fifty-four shards passed (3,446 native cases); all 62 started databases
  were removed and no timing headroom was exhausted. The test-only correction adds
  a coordinated move into another valid scope to prove the original immutable-item
  guard too, with SQLSTATE and complete unchanged-row assertions. All 20 native
  database-integrity cases pass in 180.66s; fast unit run41 passes all 13,222 cases
  in 92.10s with the three existing warnings. See the
  [scope-guard repair](../checkpoints/2026-09-21-programme-scope-guard-expectation-repair.md).
  The 17 incomplete groups are receiving focused diagnostics before fresh complete
  exact-head certification; no partial-run success or push is claimed.
- Full certification at `8f3f825f180438953630c2fb39eacbf2f12a9eca` stopped after
  46m35s on one stale stop-schema test expectation in shard 33. The current native
  guard correctly rejected a malformed receipt; the test still expected migration
  0015's earlier unconditional refusal. Thirty-two shards passed (1,620 native
  cases), all 13,222 units passed in 176.41s, and all 40 started containers were
  removed. No timing headroom was exhausted. Evidence is preserved in
  `.tools/certification-evidence/programme-exit-8f3f825-stop-expectation-failed`.
  Test-only repair checks the current exact-intent refusal and separately executes
  the historical 0015 refusal through real reverse/reapply, preserving zero-written-
  rows assertions. The repair passes **44 native cases / 291.56s** and complete
  fast run40 (**13,222 units / 72.21s**). See the
  [schema-expectation repair](../checkpoints/2026-09-21-programme-stop-schema-expectation-repair.md).
  No application/rehearsal source or applied migration changed. Fresh exact-head
  full certification remains required; no success receipt or push exists.
- Recovery correction `ad6192993ff6d9eab6c6117f9081dd2a47713833` passes 65 focused
  fence/overlay units, complete fast run39 (**13,222 / 72.68s**, three existing
  Django warnings), and **66 native regressions / 1,008.83s**, with no native skips.
  Both original notice failures and fourteen retained authority families pass
  unchanged-recorder assertions. Neighboring historical regressions pass **18 cases
  / 1,218.03s**, and populated run26 passes **1,058.92s**, all sixteen phases and no
  skips. See the [current verification](../checkpoints/2026-09-21-programme-retained-recovery-verification.md).
  Ruff/format, typing, NumPy/semantic documentation,
  maintained Markdown/skills and fresh warning-fatal Sphinx pass.
- Full `b2e88af` certification failed retained-notice-authority recovery, not timing;
  fifteen native shards and all units passed, and all 23 started containers were
  removed. The additive correction preserves original owner fences and applied
  migrations. Keep the [failed evidence](../checkpoints/2026-09-21-programme-retained-authority-certification-failure.md),
  earlier [native-fence repair](../checkpoints/2026-09-21-programme-exit-recovery-fence.md)
  and [static preflight record](../checkpoints/2026-09-21-programme-exit-certification-preflight.md).
  No failed or partial attempt is a success receipt; final exact-head certification
  remains required.
- Populated run24 at `8e3c02c` passed **1,039.27s**: all sixteen phases, including
  49 actual-purpose scope/denial responses across seven routes, archive, active
  restore, stop and populated stopped-state restore. Every phase checks 97 excluded
  tables. Exact timings, source revision and limits are in the
  [executed checkpoint](../checkpoints/2026-09-21-programme-populated-isolation-execution.md).
  Run25 at `ad61929` failed safely before proposal setup in 12.11s because its command
  omitted the documented signature-refresh opt-in. Passing run26 uses that option; no
  scanner freshness exception or source change was made.
- Separate [real exit-route isolation](../checkpoints/2026-09-21-programme-exit-real-scope-isolation.md)
  passed 258.82s; [HTTPS, three real database races and stopped restore](../checkpoints/2026-09-21-programme-stop-http-races-recovery.md)
  passed 279.78s. Preserve their exact source revisions and the separately pinned
  #97 worktree/evidence. HTTP is not visible-browser acceptance, and table snapshots
  alone do not prove every denied field or transient effect.
- The 40 MiB archive test measured about 50.1 MiB tracked Python peak, not process
  RSS or maximum capacity. Connection-loss rollback is tested. Real twenty-minute
  process expiry and deployment workload measurement remain unproved.

The in-app browser rejected the fresh isolated fixture's temporary HTTPS
certificate with `ERR_CERT_AUTHORITY_INVALID` before login. Credentials were
handed off encrypted, then cleared; the owned fixture reports disposed. No
browser-security bypass or machine trust change was made. The concrete browser
follow-up is recorded in [#92](https://github.com/martonpornoi/maru/issues/92#issuecomment-5754450210).
Exact-certificate-pinned HTTP evidence is not visible-browser acceptance.

## Next actions and remaining closure gates

The [human session cards](../operations/programme-human-acceptance.md) now provide
a concise facilitator/participant handoff and evidence form. They were prepared
separately while `b2e88af` was frozen and folded into the coherent bundle after that
certification failed. They record no human pass. Documentation validation and a
fresh warning-fatal Sphinx build pass; final exact-head certification/protected
delivery remain outstanding.
The browser certificate prerequisite and genuine independent people remain required.

1. Freeze and certify the implemented exit/recovery bundle against exact main;
   repair concrete gate failures without weakening coverage or native checks.
2. Complete remaining archive/stop acceptance and full P12 scope/object/field
   isolation. Excluded-table snapshots do not prove every denied request or
   transient created-and-deleted effect. Preserve all independent owner checks.
3. Freeze the coherent bundle, run required exact-head local/hosted acceptance,
   deliver through a protected PR and update only actually completed issues.
4. Complete #109's joined P01–P12 evidence and #92's genuine representative-person,
   screen-reader and materially changed browser journeys. Manual observations
   need actual participants; assistant-operated personas are not human acceptance.
5. Only then implement and separately verify #108's final profile promotion.
   Close #48 after its entire decomposition and integrated checklist are supported.

#189/#190/#196/#197/#198/#175/#97 remain delivery/acceptance work; #108/#109/#92/#48
remain open. Do not infer parent completion from component tests or merges.
Preserve valid unchanged #87/PR #90 native Cancel, actual 200% Chrome zoom and
visible focus evidence, and the user's disabled Windows Animation effects.
The earlier one-off split-run exception is not standing certification policy.

## Continuation boundaries

Delivered dormant Programme children #57/#59/#61/#63/#66/#64/#71/#77/#79/#81/#85/
#88/#91/#94/#96/#99/#100/#104/#105/#107 and #108's delivered setup/reference/file/
role/starter/navigation/rehearsal increments must not be restarted. Their detailed
preparation history lives in dated checkpoints and Git history, not current policy.

Keep `programme_operations@1` limited to Applications, Programme, Scheduling,
Venues and Workforce plus required foundations. No Registration, Participation,
payment, attendance, Logistics or general Communications side effects. Owner
commands and independent approvals remain authoritative; navigation is not access.
#104 notices separate preparation/review/handoff/acknowledgement. #107 fallback
remains historical read-only material with independent trust, scope and expiry.

Unattended implementation, bundled PRs and protected merges are authorized with
one agent. No new schedules, policy bypass, production deployment or general
Docker cleanup. Preserve unrelated worktrees/stashes/resources; dispose only
verified task-owned resources. Applied stashes `5b6851f` and `dd651ef` must not
be reapplied. Preserve unrelated `3cc5df` / `9fecfe` and the #96 repair worktree.

After #48, continue #42 and the director introduction/pilot package, then the
agreed guidance/accessibility and continuity/succession priorities. #22/#23/#24
remain separately Workforce-owned. Track the semantic docstring validator's
no-argument string/Path defect there; maintained explicit `src scripts` passes.
Provider/runtime provisioning, restore/PITR, supervision/load, privacy,
safeguarding, training and production go/no-go remain separate gates.
