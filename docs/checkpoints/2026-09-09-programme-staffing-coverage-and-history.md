# Programme staffing coverage and retained binding history

- Date: 2026-09-09
- Branch: `codex/programme-staffing`
- Active child: [#88](https://github.com/martonpornoi/maru/issues/88), parent #48.
- Previous local checkpoint: binding kernel `90d3841`.
- State: local implementation checkpoint, not full certification, PR or delivery.

## Implemented boundary

Workforce now provides complete item-scoped current binding metadata without
actor/rationale columns, and separate fixed-ceiling binding history under both
Programme history-field and Workforce work-field authority. Canonical scope,
bounded consecutive history pages, final authorization and mandatory audit
prevent partial or unauthorized disclosure.

The composable Workforce coverage reader retains current minimized counts and
returns only a work-term fingerprint, not instructions or personnel. The existing
standalone repeatable-read coverage reader retains its original no-briefing SELECT.
Scheduling composes one item's requirements with an explicit private alternative,
current binding and complete coverage under canonical locks. The same pure source
comparison is reused by binding commands and coverage; complete owner snapshots
are not reloaded separately for every row.

Ordinary opening/locking can preserve current coverage. Changed work terms,
requirement revision/retirement or selected-source movement yield stale null
counts without changing work. Copying another alternative does not rebind it.
Missing Workforce authority is withheld; incomplete dependencies make the whole
layer unavailable. Claims remain distinct from confirmations and explicit locked
underfill remains underfill. Restricted rationale never enters coverage rows.

HR-015, ADR 0093, owner documentation and recovery guidance describe these read
purposes. The native Programme staffing page contract is defined before its UI
implementation. No profile, route or runtime writer is activated.

## Verification performed

- Combined focused run: **32 PostgreSQL tests passed in 122.62s**, covering
  exact source selection, current binding/history, fixed ceilings and paging,
  independent field authority, foreign scope, overflow, postload revocation,
  audit rollback, real claims/independent confirmation/underfilled locking,
  alternative independence, movement, changed work and requirement retirement.
- Full fast suite: **4,202 unit tests passed in 20.82s**, with the same two
  pre-existing Django URLField warnings. The initial inventory failure was fixed
  by registering the new Scheduling integration test file, not removing a test.
- Focused Ruff and strict Mypy passed for the four affected production files;
  semantic Python docstrings passed for those files. Documentation validation
  passed before this final checkpoint/page-contract addition.
- One initial lifecycle test used an incorrect underfill parameter; corrected
  to the existing explicit `allow_understaffed` command contract before the
  successful combined run. No production lifecycle behavior was changed.

These tests use the owned disposable PostgreSQL fixture and isolated future-policy
substitutes. They are not Programme-only profile activation, browser acceptance,
provisioned runtime or production readiness evidence. New timing entries are
conservative scheduling weights, not a measured hosted performance claim.

## Remaining work

Implement and rehearse the native requirement, history, binding preview/apply
and recovery controls. Complete the remaining issue-level concurrency/personal
isolation acceptance, exact-head certification and protected PR delivery. Keep
#48 open and #87 mandatory before activation; release, on-site continuity and
guided Programme-only integration remain subsequent work. Preserve unrelated
worktrees, stashes and containers; no schedule or general cleanup is authorized.
