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

The isolated migration overlay is 0018, with 88 explicit candidate writable
relations, thirteen invoker validators and one existing narrow definer helper.
Production ACLs and existing profiles remain unchanged. Events 0016 implements
the reciprocal native stop/receipt proof; unused reverse/forward succeeds and
used evidence fences downgrade. Source/metadata pins are maintained in their
owning code; never rebaseline a weakened live schema.

Events 0017 now extends the retained native-evidence fence over the whole joined
exit generation, before Events/Venues/Workforce successors can partially reverse.
Its no-op forward/reverse-only fence is source-pinned; existing applied migrations
are unchanged. The archive's independent native downgrade refusal is still tested.

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

- Full attempt at `9de5c826035e7b3cbc489c73b8a4dfb30e434d7a` passed all 13,171
  certification units, but failed two archive migration
  recovery assertions. Six native shards passed before fail-fast cancellation;
  all fourteen started containers were removed. Failed evidence is preserved in
  `.tools/certification-evidence/programme-exit-9de5c82-migration-failed`.
  Follow-up reproduced a real partial-successor reversal defect in 53.99s.
  The new Events 0017 fence and full-current test recovery pass **31 native cases
  in 199.61s**, plus 35 focused units. See the
  [recovery-fence checkpoint](../checkpoints/2026-09-21-programme-exit-recovery-fence.md).
  A fresh complete exact-head certification remains required.
- The separately prepared populated P12 increment is now consolidated in the exit
  bundle. Seven actual-purpose HTTP probes cover proposal, decision, private item,
  planner, starter, room and Department output routes against real foreign/sibling/
  mixed scopes and an unrelated confirmed volunteer. The first extended native run
  failed the planner positive control after 850.29s. Explicit independent content
  and Venue-selection approvals now occur in P05; later release preparation no
  longer duplicates content approval. Seventy focused units pass. Corrected native
  run24 at `8e3c02c2fb95cda9c252f188d48c436b6109ca82` passes in **1,039.27s
  (17m19s)**, including the 49-response scope/purpose matrix (45.891s), all populated
  phases, archive, active restore, stop and stopped-state restore. See the
  [executed evidence](../checkpoints/2026-09-21-programme-populated-isolation-execution.md)
  and the
  [preparation and failed-attempt record](../checkpoints/2026-09-21-programme-populated-isolation-preparation.md).

- First exact-bundle certification at `2a41f96` failed formatting. Its supported
  cancellation removed all eight started native databases; failed artifacts are
  preserved. Formatting, lint and explicit NumPy documentation are repaired; full
  typing, semantic docs, fresh warning-fatal Sphinx, frontend and generated-contract
  preflights now pass. See the
  [preflight checkpoint](../checkpoints/2026-09-21-programme-exit-certification-preflight.md).
  A new clean exact-head full certification is still required.
- Exit-route isolation run4 passes in **258.82s** against real existing foreign
  and sibling foundations, mixed scopes and other authenticated people. Thirty-two
  protocol/observer units pass. Organization-scoped stop-preview authority is
  preserved; archive-purpose and requester restrictions remain independent. See
  the [exact evidence and limits](../checkpoints/2026-09-21-programme-exit-real-scope-isolation.md).
  This is a bounded P12 increment, not the entire Programme isolation matrix.
- Complete consolidated fast run38 at `8e3c02c`: **13,190 passed / 72.62s**, three
  existing Django URL-field warnings. Focused private-process/HTTP tests:
  72 passed / 0.78s. Ruff/format, typing (793 source files), NumPy and semantic
  documentation (814 source files) pass. Maintained Markdown/skill validation passes.
- Real stop/native owner matrices: 224 passed / 552.81s. Command/tampering/
  immutable receipt/used downgrade: 24 passed / 91.51s. Original-actor receipt
  denial: two focused cases / 11.18s. Forms/HTML: 29; candidate startup/ACL: 111.
- Populated restricted-runtime run21: **967.73s**, including P01–P10, archive,
  active-state logical recovery, partial-backup refusal and actual stop
  (22.734s). Missing withdrawal authority, stale confirmation, rollback, one
  committed withdrawal, exact retry and unchanged artifact bytes are proved.
  Every phase preserves the baseline of 97 excluded-owner tables.
- Separate real HTTPS/three two-connection races/stopped-state restore:
  **279.78s**. Actual PostgreSQL blocking is observed in both stop/draft orders
  and the same-key race. Restored original receipt retry succeeds; reopening
  fails. This blank-owner fixture does not prove populated artifact recovery.
- Extended populated run23 passes in **994.23s (16m34s)**, including actual stop
  (22.797s), active-state recovery (39.000s), and stopped-state logical recovery
  with populated immutable artifacts (18.453s). Archive generation took 15.563s
  for 157,233 bytes. Run22 refused a missing explicit run identity before execution;
  that attempt remains a failure, not inherited acceptance.
- The pinned #97 run19 at `dea7674068d6322bfae74b6f4e45b6e56d695c37` passed
  in 939.44s, including actual clone readiness/revocation and partial-backup
  refusal. Preserve its separate managed worktree and evidence.
- The 40 MiB archive custody test measured about 50.1 MiB tracked Python peak,
  not process RSS or maximum capacity. Actual generation connection loss rolls
  back partial bytes. Real twenty-minute process expiry and intended deployment
  workload measurement are not established by mocked-clock checks.

The in-app browser rejected the fresh isolated fixture's temporary HTTPS
certificate with `ERR_CERT_AUTHORITY_INVALID` before login. Credentials were
handed off encrypted, then cleared; the owned fixture reports disposed. No
browser-security bypass or machine trust change was made. The concrete browser
follow-up is recorded in [#92](https://github.com/martonpornoi/maru/issues/92#issuecomment-5754450210).
Exact-certificate-pinned HTTP evidence is not visible-browser acceptance.

## Next actions and remaining closure gates

The [human session cards](../operations/programme-human-acceptance.md) now provide
a concise facilitator/participant handoff and evidence form. This documentation
increment was prepared separately from the frozen exit-bundle certification at
`b2e88af`; it records no human pass. Documentation validation and a fresh warning-fatal
Sphinx build pass; exact-head certification/protected delivery remain outstanding.
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
