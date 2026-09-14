# PR quality timeout and contributor-documentation execution parity

Date: 2026-09-14. Scope: #113 as an actual protected-delivery blocker for
#108's call-composer PR #116 within #48. No unrelated cleanup or feature work.
Original candidate: `814393a2f9bd4fc3173e324f242afbb9d13648e8`.
Base: `ae97565ff03005a730ef8d492e2a1f72b04318e7`.

## Confirmed failure, not a PostgreSQL regression

The original candidate passed all eight retained local gates in 969.557 seconds,
completed 04:35:12 UTC. Its final 6,274 units passed in 38.43 seconds; JUnit has
zero failures/errors/skips. The schema-4 receipt, plan, JUnit and both package
artifacts are hash-verified in the ignored `issue108-814393a-deferred` archive.
Receipt SHA-256: `1635b5e94618a7d70a9c0ef65604d2a0e10491c8b3cb34153b23e20c996e5e78`.
PostgreSQL execution is false, databases zero, combined coverage/headroom null.

Hosted [run 34806667334](https://github.com/martonpornoi/maru/actions/runs/34806667334)
failed its aggregate PR gate. Quality job `103859813778` ran from 04:36:34 to
05:06:50 UTC (30m16s including cancellation/cleanup). GitHub's annotation explicitly
reports exceeding the maximum execution time of 30m0s. The documentation step
occupied 04:37:41 to 05:06:47 (29m06s); its source-highlighting output was at 92%
when cancelled. Sphinx started at 04:37:56; module highlighting began 04:59:36.
This is not an assertion failure or database test timeout.

Hosted Python units passed (1m34s whole job), and all three CodeQL analyses passed.
After the timeout, documentation upload, Django/generated contracts, frontend and
dependency audit did not run in that hosted job. Earlier local success does not
certify a repaired head or replace those hosted gates.

## Smallest execution repair

The routine PR path alone invoked Sphinx serially. Full CI, Pages and the local
check already request `-j auto`. Align the routine PR invocation with that existing
platform-supported CPU parallelism while retaining `-W --keep-going --fresh-env`,
the same whole documentation input/output and doctree paths, NumPy and semantic
docstring checks, required artifact upload and fatal failure propagation.

No warning suppression, source/history omission, stale build cache, increased
timeout, concurrency-policy change, profile change or database execution is added.
The unchanged PR gate still depends on quality. This is execution parity under
existing NFR-001/002/003 and protected-delivery contracts, not an ADR reversal.
Parallel scheduling varies by platform and runner; hosted measurements must
establish the actual improvement. No guaranteed future margin is claimed.

The existing local/full documentation contract test now also covers routine PRs.
A focused structural regression checks the exact three documentation commands,
unchanged 30-minute cap, no continue-on-error, complete output artifact and fatal
missing-output policy. Existing workflow/gate/allowlist contracts remain active.

## Associated call-form correction

Four isolated database-free observations on the frozen original head confirmed
that malformed/nonpositive creation edition versions return the bound error form
with HTTP 200, without any writer. This small follow-up was recorded in #108 and
the PR description; it did not bypass scope or permit writes. Since a new candidate
is required for the CI blocker, fix the validation handler to return 400 in this
same repair. Five maintained regressions cover missing, blank, zero, noncanonical
and invalid versions, retained input/retry evidence and no writer invocation.

The first focused repair run exposed only a test assumption that Django renders
a value attribute for an empty hidden field (130 passed, two failed). The test
now accepts that standard omission without replacing input. All 132 focused
CI/composer cases pass in 2.17s; repository Ruff and formatting pass. No failed
observation or original receipt is a repair success receipt.

Fresh full-unit preflight passes 6,281 tests in 39.03s, with the same two existing
Django URLField warnings. Documentation validation passes 498 Markdown files,
four repository skills and 215 requirement identifiers.

## Pending exact delivery

Clean exact-head certification and independent hosted PR gate/CodeQL remain
required before merge. Measure the successful replacement
quality/documentation stages and record them in the protected delivery checkpoint.
#113 remains open until its documented runtime acceptance is actually met.
#108/#48 stay open for remaining Department, proposal/review/conversion,
connection/setup and acceptance outcomes. Native evidence remains deferred to
#102 and human checks to #92; #109/#97 also precede Programme promotion.
