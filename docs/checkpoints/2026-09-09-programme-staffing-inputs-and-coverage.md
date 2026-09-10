# Programme staffing inputs and minimized coverage foundation

Date: 2026-09-09. In-progress child: #88 under #48.
Branch: `codex/programme-staffing`; protected base:
`cdb06d41a6d5795078a8ae19ee5e4a0ebbabd466`.

## Contract and local implementation

ADR 0093 and expanded HR-015 pin explicit requirement and timetable source
revisions, preserve published/accepted Shift terms, distinguish unknown coverage
from zero and retain locked underfill as underfill. The native issue is linked
from #48. #87's deferred browser checks still block activation.

Programme input classes validate immutable explicit work terms, UTC-minute
intervals and exact source references. Workforce's pure coverage reducer
separates pending claims, current confirmation, stale suitability, underfill
and retained terminal work. The dormant `workforce.programme-coverage@1` reader
checks real independent field policy, consistent scoped owner reads,
post-snapshot authorization and mandatory audit. Current profile manifests
remain unchanged. No requirement schema or staffing writer exists yet.

## Verification actually performed

- 151 focused unit tests pass for input semantics, coverage and source admission.
- The fast complete unit run passed 4,039 cases and exposed two inventory
  expectations for the new adapter/test file. Both were repaired; their 30-case
  focused suites pass. This is not a new complete certification claim.
- Two real PostgreSQL source tests pass in 12.09 seconds using the initialized
  isolated database. They cover claim/independent confirmation/withdrawal,
  exact digest changes, retained commitment immutability, excluded private
  SELECT columns, actual current-profile denial, incomplete/foreign scope and
  overflow. Initial schema setup plus the first run took 151.58 seconds; that
  run exposed an invalid test invocation of availability withdrawal. The test
  now calls the separate real owner withdrawal command.
- These source tests reuse the existing synthetic full-convention Shift
  fixture and temporarily admit only the dormant adapter. Real scope, identity,
  capability, field and audit checks remain. This is not a provisioned
  Programme-only/no-Participation rehearsal.
- Focused Ruff, strict types and semantic NumPy docstring checks pass. The
  documentation validator passes all 427 Markdown files and four repository
  skills after these additions. Warning-fatal Sphinx and protected certification
  of the completed issue are still required.
- The new diagnostic timing entry conservatively reuses the existing Shift
  test-file weight of 120.285 seconds. It is an estimate, not hosted calibration;
  no CI risk selection, timeout, test or coverage gate is weakened.

## Remaining work

The disposable synthetic PostgreSQL container is
`maru-issue88-focused-20260909`, labeled `maru.task=programme-staffing-88`, on
loopback port 56888. It contains only this task's ephemeral data and can be
reused for focused feedback; no test process is still running at this checkpoint.
Do not stop or prune unrelated containers. The protected old pytest cache was
left untouched; the successful rerun disabled pytest's optional cache provider.

Persist Programme requirement revisions and reciprocal exact source bindings;
implement explicit create/link/reconcile/successor commands, protected reads and
forms; integrate current coverage and host/Shift consequences into Scheduling;
prove raw-DML constraints, canonical locking, race rollback, additive migration
recovery and dormant runtime containment. Then complete browser evidence and
exact-head protected delivery. Issue #88 remains open; no PR or staffing merge
is claimed. Atomic release, personal published composition, continuity, guided
activation and integrated acceptance remain later #48 outcomes.
