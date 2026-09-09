# Programme staffing requirement persistence checkpoint

Date: 2026-09-09\
Issue: [#88](https://github.com/martonpornoi/maru/issues/88), child of #48\
State: Verified local continuation, not a completed issue, PR or protected merge

## Scope and continuity

The user selected Astra High and authorized resuming the existing Programme
queue. Work remains single-agent. Branch `codex/programme-staffing` retains the
verified main baseline `cdb06d41a6d5795078a8ae19ee5e4a0ebbabd466` and the earlier
local input/coverage checkpoint `acae8851003ccd32436bbc0a747e377a7a038e29`.
No completed #85 certification was rerun. #87 remains a mandatory activation gate.

Programme now owns stable occurrence staffing requirements and immutable
revisions under HR-015/ADR 0093. Explicit create/revise/retire commands validate
typed inputs, current item/occurrence/edition/requirement versions, purpose-owned
Position references, work dates and bounded history. Retirement retains the
previous work terms and cannot revive a retired need. No demand or commitment
is created or changed by those commands.

Independent current and historical readers release complete, bounded,
field-ceilinged projections only after current authorization and audit. Current
reads exclude history rationale and actor columns. Fixed-ceiling history pages
remain stable across later changes and cannot disclose private candidates or
Workforce personnel. Public cross-owner references are identifier-only and
provide no authorization. The existing canonical Workforce edition lock scope
precedes Programme-owned rows.

Programme migrations `0010`–`0012` and authorization `0028` add exact scope,
lifecycle, version, term and reciprocal evidence protection, metadata pins and
populated reverse fences. Both new relations remain runtime SELECT-only.
Neither executable profile is changed, and no route, worker or runtime writer
is activated. The [module contract](../modules/programme.md) and
[recovery guide](../operations/programme-staffing-migration-and-recovery.md)
describe the exact boundary.

## Verification and corrections

- First focused run: 14 passing cases before a truncate test failed because
  the fixture's existing test-reset escape was still enabled. The test now
  disables that escape transaction-locally; no production guard was weakened.
  The corrected input/command run passed 122 cases in 38.38s.
- Expanded owner/recovery run: 26 PostgreSQL cases passed in 70.81s, including
  actual unused reverse/reapply, existing-owner preservation, populated fence,
  read history, disabled-trigger detection and current-schema restoration.
- Latest focused run: 36 PostgreSQL cases plus eight unit contract cases passed
  in 90.49s. Additional cases exercise forged raw append terms, exact foreign
  owner scope, read reauthorization/audit failure and reserved retirement room.
- Broad fast run initially found nine failures: additive capability/catalog
  expectations, runtime provisioning inventory and a genuine CI graph-selection
  defect. A new owner leaf had hidden consumers attached to an older model
  migration. Model-level changes now traverse all of that owner's migration
  nodes, while exact migration changes remain precise. A synthetic graph
  regression retains both cases; the existing real-graph regression is unchanged.
- After these corrections, all 4,078 then-current unit tests passed in 24.49s.
  Three subsequently added bound tests passed within the eight-case focused
  contract run. Two pre-existing Django URLField deprecation warnings remain
  visible in the broad unit invocation; they are not new application failures.
- Migration drift reports no changes. Six changed command/input/query/reference
  modules pass strict types and semantic NumPy docstring checks. The documentation
  validator passed 428 Markdown files before this checkpoint was added.
- Installed Programme relation, column, constraint, index and trigger/function
  fingerprints match. Only the intended receipt-operation constraint changed
  among existing schema fingerprints. Authorization guard metadata also matches
  the new capability function. The post-test database is flushed and has no
  active authority cutover marker: this is not a provisioned-runtime acceptance
  or activation claim.

New CI history memberships identify the two actual reverse/fence tests explicitly.
Initial file/group timing weights conservatively reuse existing comparable
weights; they are estimates, not hosted calibration. No PostgreSQL history,
timeout, coverage threshold or protected merge check was removed or weakened.

## Next boundary

Finish exact requirement/candidate/placement-to-demand binding, explicit
create/link/reconcile and successor recovery, minimized Scheduling coverage,
the personal claim/confirmation/lock journey, remaining cross-owner races,
native forms/browser acceptance and complete exact-head protected delivery.
Do not close #88 or treat this checkpoint as a completed staffing workflow.
Release, on-site continuity, guided setup and integrated Programme-only
acceptance remain subsequent #48 outcomes.

At this checkpoint no focused test process is still running. The owned ephemeral
container `maru-issue88-focused-20260909`, label `maru.task=programme-staffing-88`,
remains available on loopback port 56888 for reuse. No watcher or scheduled
reminder was created, and unrelated worktrees, stashes and Docker resources
were left untouched. There is no production personal data in this work.
