# Current project state

Last updated: 2026-10-04
Phase: Progressive adoption and pre-production release evaluation.

Maru is a Django/PostgreSQL modular monolith under synthetic evaluation, not a
production-ready release or supported hosted service. This file is the concise
handoff; [ROADMAP](ROADMAP.md) owns sequencing, [checkpoints](../checkpoints/index.md)
preserve history, and the [production ledger](PRODUCTION_CONSOLIDATION.md) retains
the release baseline.

## Protected baseline and testing policy

[PR #206](https://github.com/martonpornoi/maru/pull/206) delivered #205 at protected
squash `1fa3bb8359fde77e5eebdfd70fde379c4f2d1ae3`; its tree equals certified
`722462e`. Local and hosted acceptance passed **18,570 Python cases and all 71
PostgreSQL shards**, with **91.73%** combined coverage; local frontend acceptance
passed **103 cases**. Local certification took **4h13m36s**, hosted acceptance
**4h27m48s**. Hosted native jobs finished in **6m21s–58m52s**, retaining at least
**61m08s** of the unchanged two-hour limit. Exact-head PR gate, CodeQL,
up-to-date mergeability and resolved conversations passed before match-head squash.
Clean local main was synchronized; #205 and its supporting #48 item are complete.
The temporary #205 check-in was deleted. See the
[delivery checkpoint](../checkpoints/2026-10-03-programme-exit-browser-protected-delivery.md).
No human acceptance, archive authority or production activation was claimed.

[PR #204](https://github.com/martonpornoi/maru/pull/204) delivered #203 at protected
squash `911002068dd5acb89ac4e4a8c46b60c1081c6097`; its tree equals certified
`df9e094`. Local and hosted acceptance passed **18,538 Python cases, 103 frontend
cases and all 71 PostgreSQL shards**, with **91.74% local / 91.73% hosted** coverage.
Hosted native jobs finished in **7m15s–57m29s**; the slowest retained **62m31s**
of timeout headroom. Exact-head PR gate, CodeQL and resolved conversations were
verified before match-head squash. Clean local main was synchronized; the temporary
#203 check-in was deleted. See the [delivery checkpoint](../checkpoints/2026-10-02-programme-local-assisted-protected-delivery.md).
No human acceptance or production activation was claimed.

[PR #202](https://github.com/martonpornoi/maru/pull/202) delivered the seven
local-only redirect fixes at protected squash `314d593dc98fde705e834ef6374d001d25051942`.
All 71 local/hosted PostgreSQL shards passed, with 18,432 Python cases and 91.74%
coverage. The fresh main CodeQL scan marked alerts 13–19 fixed, not dismissed;
zero open alerts remained. Clean local main was synchronized. Final exact-head
evidence is on PR #202; no manual Programme acceptance was claimed.

[PR #201](https://github.com/martonpornoi/maru/pull/201) previously delivered
the custody clock-fixture repair and exit delivery record as protected squash
`eff8286b2c7dcff00e51159d76d70d61e7cd4745`; its tree equals certified `906f9e0`.
Local and hosted affected-history acceptance passed 31 PostgreSQL shards,
13,306 units, 103 frontend cases and 91.61% combined coverage. #200 is closed.
This is the base for the separate redirect hardening below, not its certification.

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

The post-#205 continuation has a local Windows desktop facilitator and
[maintainer walkthrough](../operations/programme-maintainer-walkthrough.md).
Its short core creates a fictional call draft using browser-checked labels and
complete supplied values; a separate prepared session covers public/personal
output, print/offline observations, withdrawal and stop. It retains the original
finite fixture, generated accounts, independent authority and owned cleanup.
Noninteractive provisioning now disconnects inherited stdin to avoid a Windows
startup hang; the supervisor handles stop/EOF and broken-pipe disposal explicitly.
No production schema/profile/route or grant changes. See the
[continuation checkpoint](../checkpoints/2026-10-03-programme-maintainer-facilitator.md).

Draft PR #207's first head `f69d6a5` failed CodeQL for plaintext password
logging. The repair removes credential output, using an in-memory account
window with deliberate clipboard copying, Windows history/cloud exclusions,
30-second expiry and ownership-checked cleanup. It does not dismiss the
finding or weaken scanning. Applied repair feedback passes **104 focused cases**
and **13,529 complete units / 79.65s**, with three existing Django warnings.
Repository-wide Ruff/format, 714-document validation and whitespace checks pass.
Native Windows checks verify copying, all exclusion formats, actual clipboard
removal, window disposal and normal child shutdown through the new GUI stop path.
Original `f69d6a5` local certification passed **18,585 Python cases, 71 shards and
91.73% coverage / 4h14m44s**; all 5,045 archived files were hash-verified before
applying the repair. That receipt does not certify the revised candidate, which
still requires clean-head local certification and hosted acceptance. See the
[credential repair checkpoint](../checkpoints/2026-10-03-programme-credential-delivery.md).

New browser evidence includes a timely actual public download, successful offline
verification/recheck, a separately withdrawn pack advancing known state and refusal
of the earlier still-unexpired pack. Reasoned withdrawal, terminal stop receipt,
ordinary logout, call-draft creation and generated volunteer login also passed.
Native print preview and visual inspection of local HTML remain unperformed.
Earlier native terminal-facilitator normal stop confirmed
DISPOSED, COMPLETE and exit zero; no helper process or owned container remains.
A harmless final-helper process probe confirms stop/interrupt child cleanup;
PowerShell still reports Ctrl+C as an interrupted command. Use written `stop`.
Finish clean exact-head certification and hosted gates;
earlier receipts are not its evidence. The guide is not yet the protected final
handoff. Remaining archive, independent-person, accessibility and owner gates
under #92/#109 still precede #108 promotion and #48 closure.

#203 is delivered through PR #204; the earlier verification narrative below
preserves failed and superseded attempts, not current blockers. ADR 0115 permits explicit synthetic
loopback HTTP over the unchanged pinned native HTTPS fixture, without machine
trust, TLS bypass, production changes or impersonation. Finite leases, ordinary
login/logout, run-specific cookies, encrypted handoff and owned cleanup remain
mandatory. PostgreSQL acceptance remains required. Interrupted runs are not
certification; the final clean #203 bundle received fresh acceptance above.

The #92/#109 supporting repair bundle #205 is delivered through PR #206.
The following observations retain their original evidence boundaries.
Fresh assistant-operated public and volunteer continuity views passed the seven
required width checks with one H1/main and no page overflow. Public keyboard and
print-copy navigation worked. A volunteer snapshot downloaded, but subsequent
printing/logout reached an expired fixture after a multi-hour wall-clock gap;
these are unperformed checks, not passes or product failures. Normal disposal,
exit zero and absence of the exact owned containers/processes/listener were verified.
Temporary viewport overrides were reset. That first fixture is fully disposed.

The launcher now prepares an encrypted handoff of the fixture's independently
generated **public** continuity policy, restricted to its exact tenant/edition/run.
Closed-schema checks reject private-key fields and mismatched scope. No signing
secret, new authority or production setting is added. This repairs the missing
prerequisite for separately verifying an actual browser download; it is not a
completed offline rehearsal. Focused launcher tests pass **36 / 0.35s**, with Ruff
and formatting checks passing. Complete database-free feedback now passes
**13,477 / 75.69s**, with three existing Django warnings; documentation validation
and whitespace checks pass. A second published native handoff successfully supplied
the validated public policy. The new bundle subsequently received its own clean
exact-head certification and protected delivery above; #203's receipt was not reused. The
[browser follow-up checkpoint](../checkpoints/2026-10-02-programme-continuity-browser-follow-up.md)
preserves the expiry and temporary-directory failures separately from successful checks.

The [second browser checkpoint](../checkpoints/2026-10-02-programme-exit-form-browser-repair.md)
records seven-width operator/stop-preview checks, keyboard layer selection, a
reasoned publisher withdrawal and required-reason validation. Final stop was
**not confirmed**. An isolated real-browser probe then reproduced `Origin: null`
from the stop/archive HTML `no-referrer` policy. The scoped repair uses
`same-origin` on HTML only, retaining private archive download headers and every
CSRF/origin guard. Regression-first checks passed **68 / 1.28s**, Ruff and format.
The second fixture is disposed; its separately trusted but expired public download
failed closed, with no offline output. A third populated browser run then passed
separate publisher withdrawal, required-reason validation, keyboard stop submission,
retained terminal receipt, seven-width layout and ordinary logout from the repaired
page. Another controller could not read the original actor's receipt. All owned
resources were normally disposed; no fixture remains. Complete inexpensive units
pass **13,489 / 79.59s** with three existing warnings. Exact bundle certification
and protected delivery subsequently passed as recorded above; no live offline, native print or human pass is
inferred from the stop result.

The first exact `eb620d4` certification failed its unchanged local timing gate:
shard 34 reached **3,200.657s**, cancelling seven other active shards. Thirty-eight
shards and 13,489 units passed, but no certification receipt exists. All 46 owned
containers were removed; 4,419 artifacts and all three worker files were copied
and SHA-256 verified. The [timing repair checkpoint](../checkpoints/2026-10-02-programme-exit-certification-headroom.md)
records the stale migration-group estimate and scoped use of existing rollback
isolation for two single-connection downgrade-refusal variants. Complete cheap
units pass **13,489 / 91.21s**; Ruff, format, docs and whitespace checks pass.
The entire repaired shard 34 passed **78 cases / 26m46s** with the identical
selection, unchanged source and independently verified cleanup. This one-database
diagnostic is not eight-worker timing or certification. Fresh complete exact-head
certification subsequently passed independently at `722462e`. No timeout, group split, history selection,
coverage or production migration changed.

### Verified observations and repairs

- The [September 25 maintainer checkpoint](../checkpoints/2026-09-25-programme-local-assisted-rehearsal.md)
  records assisted workspace selection, Start planning, separate-account access
  request/approval and call draft/activation. The bridge's signed feedback-cookie
  repair fixed the misleading error after a committed workspace switch. The
  maintainer reported difficult discovery, dense forms and unclear success
  hierarchy; these remain UX findings, not unaided or two-person acceptance.
- The [September 27 assistant checkpoint](../checkpoints/2026-09-27-programme-assistant-browser-rehearsal.md)
  records fresh P02 proposal/PDF/collaboration/acknowledgement/submission and stale
  acknowledgement refusal; P03 review/recusal/moderation/decision; and P04
  conversion/delivery/hosting/private-then-shared availability/public copy.
  The narrow bridge PDF PUT/intent-header repair retains the real scanner and
  byte limits. Already-prepared examples do not count as fresh browser writes.
- P05 placement returned 403 because the fixture omitted separate hosting
  authority. An explicit bounded request and independent-account approval made
  the real editor work. Preparation now includes that existing recipe and checks
  all editor roster reads. Private preview/save advanced only the comparison
  draft v4 to v5; old accepted work remained unchanged and its coverage was stale.
- Fresh P06 staffing passed explicit requirement/work preview and creation, own
  volunteer claim, refused premature lock, separate organizer confirmation and
  coverage lock. P07 passed separate reviewer approval and planner publication of
  that exact approval, retaining both releases. Author approval returned 403.
- Audience-specific outputs and limited responsive observations remain separately
  recorded. After staffing changed the source, continuity HTML and its print copy
  withheld old geometry without cancelling retained work. This is not native
  printing, offline verification, actual zoom or screen-reader acceptance.
- Fresh P08 browser work used the explicitly approved three temporary notice
  grants, requested and approved by the two ordinary synthetic controllers. A
  rejected package stayed final and could not be recreated unchanged. A different
  work notice passed independent-account approval, explicitly simulated local
  link handoff and its exact volunteer's acknowledgement; private rationale and
  other actor identities were absent from the recipient page.
- A reasoned withdrawal advanced the pointer to v2. Its fresh notice withheld
  old geometry, inherited no approval/handoff/acknowledgement, then passed its own
  separate review/handoff/acknowledgement. The old notice became unavailable,
  another person was denied, and all three confirmed work intervals stayed intact.
  These are assistant-operated facts, not human or external-delivery evidence.
- Queue links sometimes left the old page visible; direct destinations worked.
  In-app 403 responses also retained the prior DOM. Chrome comparison returned
  `ERR_BLOCKED_BY_CLIENT`; no browser security preference was changed.

Complete inexpensive units pass **13,454 / 88.26s**, with three existing Django
URL-field warnings; repository-wide Ruff, documentation and whitespace checks pass.
Both focused native bridge/planner checks pass **2 / 617.04s**, including fresh
restricted-runtime planner preparation with the real independent host-roster read.
Their first invocation stopped at
collection for an omitted required run identity, before creating a fixture; the
corrected invocation used a fresh explicit identity. No exact-head receipt or
protected delivery is claimed yet for this candidate.

Certification of `1e61a5e` was deliberately interrupted after review found the
notice fixture trying to repeat the hosting grant now made during planning.
Fifteen shards passed; eight active shards were interrupted, not test failures
or timeouts. All 23 owned containers were removed and the incomplete evidence
was preserved; no success receipt exists. The fixture now requests eight new
notice-stage grants, retaining the earlier hosting assignment. A regression first
reproduced the duplicate and now passes; extra/duplicate handoff IDs remain refused.
Production duplicate-grant refusal and permissions are unchanged.
Fresh complete unit feedback passes **13,457 / 71.39s** with three existing
warnings, after correcting one remaining test's old nine-grant expectation.

The [October 1 recovery checkpoint](../checkpoints/2026-10-01-programme-rehearsal-verification-recovery.md)
records the later `0d2a3aa` certification interruption: 47 shards passed, five
closed abruptly and three more started without final results. There is no final
pool result or success receipt. All 4,495 surviving artifact files were preserved
and SHA-256 compared before another run could replace `.local-ci`.
The full joined rehearsal at that same clean head now passes **all eighteen
phases / 1,265.44s**, including the composed notice-grant repair, scope/field/object
isolation, archive, both logical restores and stop. Its process exited 0; owned
database/scanner resources and certificate directory are absent. This is automated
native evidence, not browser or human acceptance and not whole-commit certification.
A one-shot hidden worker retains logs and process completion independently of its
launching tool session; launcher-exit survival was observed, app-restart/reboot
survival was not. The certification command, policy and coverage gates are unchanged.
The final documentation follow-up passes **13,457 units / 78.30s**, with the same
three warnings, documentation validation, changed-rehearsal lint and whitespace.

Certification of documentation head `c9a440a` then failed its required dependency
audit: urllib3 2.7.0 has three newly reported CVEs. The eight started database
workers were cancelled through the maintained pool control and removed normally;
13,457 units passed, but there is no certification receipt. All 820 artifacts were
preserved and SHA-256 compared. The [narrow dependency repair](../checkpoints/2026-10-01-programme-verification-dependency-repair.md)
constrains urllib3 to `>=2.8.0,<3` and updates only its lock entry to 2.8.0.
It remains a development-tool transitive dependency, not a new runtime requirement.
Locked synchronization/check and the unchanged vulnerability audit now pass.
Complete fast units pass **13,457 / 74.45s**, with three existing warnings;
repository-wide Ruff, formatting and documentation validation also pass.
Fresh final-head certification and protected delivery remain required.

The subsequent `5179164` run passed the Python audit but failed the required
JavaScript audit on thirteen advisories in two development-only dependencies.
Its eight native shards were cancelled normally and removed; **13,457 units /
164.08s** passed, with no certification receipt. All 820 artifacts were preserved
and hash-compared. The [frontend-tool repair](../checkpoints/2026-10-01-programme-frontend-tool-audit-repair.md)
updates only Undici **7.29.0 -> 7.29.1** and brace-expansion **2.1.4 -> 2.1.7**
with bounded overrides. Both audits now report no known vulnerabilities; complete
fast units pass **13,457 / 74.24s** (three existing warnings and one non-fatal local
pytest-cache write warning). Complete non-database checks pass **326.96s**, including
103 frontend tests, fresh warning-fatal Sphinx and unchanged generated contracts/
assets. Fresh exhaustive exact-head certification remains required; no audit
threshold, runtime dependency or CI policy changes.

[PR #204](https://github.com/martonpornoi/maru/pull/204) opened after exact clean
`9b51c6e` certification passed all ten gates: **18,538 Python cases (13,457 units
and 5,081 native cases), 103 frontend cases, 71 exhaustive shards and 91.73%
coverage / 4h18m52s**. Every shard passed headroom/cleanup; all 5,043 evidence
files were preserved and hash-compared. Hosted CodeQL then flagged a substring
assertion in the HTML-mapping unit test, not a runtime URL authorization check.
The [exact-HTML follow-up](../checkpoints/2026-10-02-programme-codeql-html-expectation.md)
strengthens it to complete expected-response equality. No alert was dismissed,
query suppressed or security rule changed. The superseded hosted run was
cancelled; its partial results are not acceptance. The stronger test and session
checks pass **100 / 1.10s**, and complete inexpensive units pass **13,457 / 84.56s**
with three existing warnings. Fresh exact-head local/hosted acceptance remains
required. The earlier complete receipt certifies only `9b51c6e`.

The historical successful notice session used an
interactive terminal, ordinary logout and normal stop/exit 0; its exact owned
containers/certificate directory/listener are absent. An earlier non-interactive
launch stopped before browser connection (consistent with stdin EOF); final exit
metadata was not retained, but its resources were separately confirmed absent.
Its unused internal error tab could not be closed through the browser's URL policy
and was left untouched. Preserve unrelated resources. Archive and complete
disconnected/native-print browser cards remain unperformed; the October 2 stop
correction/result is recorded above. Neither session added archive authority or
production admission.

### Smallest next actions

1. #205 is delivered. Continue remaining admitted P10/P11 browser interactions
   from protected `1fa3bb8`, carrying this post-merge delivery record in the next
   coherent acceptance follow-up. Keep missing archive permission and
   unobserved print/offline controls separate from application defects.
2. #92 still needs representative independent-person, specialist screen-reader and
   operational-owner acceptance. The [session cards](../operations/programme-human-acceptance.md)
   and evidence map are not passes. A future cross-computer or convention pilot
   also needs approved browser-trusted HTTPS; local HTTP does not satisfy that.
3. #97 and #102 are delivered. Only after actual #92/#109 acceptance, implement
   and separately verify #108's final profile promotion; close #48 only when its
   decomposition and integrated criteria pass. Any move of existing activation
   gates to a later pilot requires an explicit documented scope decision.

Preserve unchanged #87/PR #90 native Cancel, actual 200% Chrome zoom, visible
keyboard focus and the user's disabled Windows Animation effects. Separate
accounts controlled by one person or an assistant are not independent people.
Real twenty-minute process expiry and deployment capacity remain unproved;
archive Python-tracked peak is not RSS. Production/PITR, safeguarding, training
and go/no-go remain separate. No production profile, routes or data are activated.

## Continuation boundaries

Previously merged Programme children must not be restarted; their history is in
checkpoints and Git. Keep `programme_operations@1` limited to Applications,
Programme, Scheduling, Venues and Workforce plus required foundations. No
Registration, Participation, payment, attendance, Logistics or general
Communications effects. Owning commands, independent approval and purpose-specific
authority remain mandatory. Notice acknowledgement is not provider delivery or
acceptance of replacement work; signed fallback remains historical read-only.

Unattended bundled delivery and protected merge are authorized, single-agent.
The approved temporary 30-minute check-in for #203 was deleted after its verified
protected merge on October 2. The approved temporary #205 check-in was deleted
after verified protected delivery and main synchronization on October 3.
No other schedule, policy bypass, production deployment or broad Docker cleanup.
Preserve unrelated worktrees/stashes/resources; remove only verified task-owned
resources. Applied stashes `5b6851f` and `dd651ef` must not be reapplied;
preserve unrelated `3cc5df` / `9fecfe`, the #96 repair checkout and both isolated
P12 checkouts. The prepared P12 source is folded into this branch, not lost.

After #48, continue #42 and the director-introduction/pilot package, then agreed
guidance/accessibility and continuity/succession priorities. #22/#23/#24 remain
Workforce-owned. The semantic docstring validator's no-argument string/Path defect
remains separate; maintained explicit `src scripts` invocation passes.
