# Programme staffing source and impact checkpoint

Date: 2026-09-09
Scope: local continuation of [#88](https://github.com/martonpornoi/maru/issues/88),
under HR-015 and ADR 0093; not a delivered child or activation.

## Implemented boundary

- Programme independently resolves one exact current requirement revision and
  Scheduling candidate/occurrence/placement/service-day selection. The edition
  mutex keeps the owner projections coherent; authority is checked independently
  and Programme is checked again before release. The source/work digest grants
  no authority and must be recomputed by a later writer under canonical locks.
- Copying another alternative preserves the selected source. Moving the selected
  candidate, revising its day or retiring the requirement invalidates it without
  creating or cancelling Workforce work.
- A separate dormant `workforce.programme-staffing@1` adapter reads one exact
  demand's explicit work terms and aggregate retained/claimed/confirmed counts.
  Its independent field checks, canonical lock scope and mandatory audit precede
  disclosure. It loads no personnel labels, private decision reasons or calendars.
  Work briefings belong to this explicit comparison purpose, not the separate
  minimized planning-coverage projection. Both executable profiles omit it.
- Closed impact rules distinguish create, link, reconcile and successor. Linking
  requires identical uncommitted draft terms. Removed history alone prevents
  reconciliation; Position changes require a successor. Explicit cancellation
  affects active claims/confirmations while retaining all history, and terminal
  predecessors are not cancelled again. No decision is transferred or reconfirmed.

These inputs do not establish a persisted binding, execute recovery, or prove a
Programme-only departmental journey. The real Workforce read tests reuse the
existing full-convention synthetic Shift fixture, including its explicit
Participation setup; that is not an exclusion-profile acceptance claim.

## Verification actually performed

- Complete fast suite: **4,173 unit tests passed in 21.58s**, with two pre-existing
  Django URLField default-scheme deprecation warnings.
- Focused PostgreSQL regression: **43 passed, two deselected in 102.35s**. This
  covers the current requirement command/guard/read cases, real source selection
  and Workforce lifecycle/impact reads. The two unchanged requirement migration
  round-trip cases were omitted here, not removed from certification; their
  earlier result remains in the persistence checkpoint.
- Three new source files passed strict Mypy and semantic NumPy-docstring checks.
  Focused Ruff checks passed. The complete unit suite also checks adapter registry
  inventory and dormant-profile admission.
- New integration files have conservative scheduling estimates copied from
  existing related files, not claimed fresh-database timing calibration.

The PostgreSQL checks reused the task-owned synthetic database for feedback.
They do not replace fresh/exhaustive exact-head certification, provisioned-runtime
acceptance, browser evidence, hosted checks or production approval.

## Remaining work

Persist exact Workforce binding and immutable revisions; preview and apply under
canonical locks through existing Shift commands; test stale sources, retained
commitment races, idempotency and atomic rollback; add reciprocal database guards,
runtime containment and migration/recovery proof. Complete the bounded UI and
Scheduling coverage composition, browser acceptance, full certification and
protected delivery before closing #88. #87 remains a mandatory pre-activation
child and #48 remains open. No new schedule or broad Docker cleanup is authorized.
