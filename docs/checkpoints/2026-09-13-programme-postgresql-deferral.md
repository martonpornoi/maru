# Temporary Programme PostgreSQL deferral

Date: 2026-09-13. Scope: issue #100 candidate and umbrella #48 development.

## Preserved feature evidence

Before this policy change, feature-only head
`ff36db6896a0ff0d073e9737086d676f5a8d1e30` completed all ten local gates
against base `f999fb510b69901798959e16c120bf0fd15b839d` in 3h36m16s.
There were 9,254 passing Python cases (4,986 units and 4,268 PostgreSQL
cases), 64 frontend cases and 90.65% combined branch-aware coverage. All 42
database jobs passed and removed their containers; the slowest took 49m17s,
with an 83m56s conservative hosted projection. Independent JUnit matching
reconciles 337 groups without failures, errors, skips or duplicate cases.

Complete receipt, reports, coverage, logs and independent verifier are preserved
locally in `.tools/certification-evidence/issue100-ff36db6-complete/`. The first
failed pnpm non-interactive dependency-install attempt remains separately
archived; its eight started jobs were cancelled and removed. A clean exact-head
retry used the pinned pnpm version and CI mode. Neither attempt certifies later
policy changes, and no hosted acceptance is claimed here.

## Explicitly authorized temporary policy

The maintainer requested that PostgreSQL execution stop during Programme feature
development and that the current feature and policy be included in the same PR.
[ADR 0100](../architecture/decisions/0100-temporary-programme-postgresql-deferral.md)
temporarily supersedes routine PostgreSQL execution in ADR 0098, not its retained
test inventory, timings, coverage threshold or future restoration requirements.

The tracked policy selects an explicit deferred path while retaining original
risk/history classification. Code PRs require every non-database gate; deletion
review, dependency review, CodeQL and the protected PR gate are not bypassed.
Nightly/manual full selection starts no PostgreSQL jobs. Reusable full acceptance
refuses to run while deferred, including release callers. Default local
certification runs non-database checks only, emits a distinct deferred receipt,
and never reports database coverage or timing headroom as passed.

Maintain database cases as features change. Record their unexecuted coverage as
verification debt, without substituting SQLite or deleting historical cases.
Restore the tracked required mode through review under #48 before Programme
activation, integrated acceptance, a director pilot or release; then run exact
exhaustive local and hosted PostgreSQL acceptance, combined coverage and timing
headroom, and repair all failures. Human acceptance #92 and recovery #97 remain
separate gates. No production profile, route or data is activated.

## Policy verification before candidate commit

- 105 focused policy/classifier/workflow tests passed in 0.89s.
- All 5,015 unit tests passed in 32.02s, with two existing Django deprecation
  warnings. An initial Windows temporary-directory setup failure was repaired
  using a task-owned directory, not accepted as passing evidence.
- Repository Ruff/formatting, documentation links and semantic Python docstrings
  passed; the new policy module's NumPy docstrings passed after correcting its
  declared exception contract.
- Actual CLI classification preserves required full history but selects deferred
  execution. The full-acceptance guard exits unsuccessfully before database
  startup, as intended. Unit contracts fence Programme profile activation.

The subsequent clean-head non-database receipt and hosted results belong to the
PR delivery record. They must remain distinct from the older full feature-head
evidence above. No new PostgreSQL execution is authorized during this phase.
