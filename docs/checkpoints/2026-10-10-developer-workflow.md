# Developer workflow and disposable local preview

Date: 2026-10-10
Requirements: NFR-001, NFR-002, NFR-003, NFR-011; existing educational demo boundary.
Decision context: ADR 0079; no architecture or delivery-policy reversal.

## Outcome

`scripts/try_maru.py` checks prerequisites, creates its own labelled PostgreSQL
container with a loopback-only random port, migrates and seeds fictional data,
starts normal local Django, and removes only its owned resources on exit.
An unattended browser session expires after 60 minutes by default (configurable
from 1 to 240 minutes). A forced process kill can still prevent cleanup.
`--check` allocates nothing; `--smoke` verifies startup then exits. Timings expose
migration and seed costs. The launcher rejects remote Docker contexts, discards
inherited application/database settings, and never adopts an existing database.

The README and local guide make this the first exploration path while retaining
manual persistent setup. The agent workflow guide makes one outcome, selected
context, early browser feedback, focused checks and one final certification
explicit. CURRENT now records the delivered PR #210 baseline instead of stale
pending-merge instructions; historical evidence remains in its owning checkpoints.

## Verification

- Locked Python 3.12 environment; 13,841 database-free tests passed in 85.89s
  before the final timeout/input regressions. The final focused launcher,
  documentation-policy and CI-classification batch passed 88 tests, including
  all 17 launcher cases. No CI classification or required gate changed.
- Repository-wide Ruff lint/format, strict typing for the launcher, and both
  Python documentation checks passed.
  The documentation validator passed all 722 Markdown files and four skills;
  the full Sphinx HTML build passed with warnings treated as errors.
- The first real disposable smoke passed in 208.0s: migrations 182.5s, checks
  1.9s and seed 17.8s. HTTP login-form readiness passed and its owned database
  was removed. A second start for browser testing took 217.0s. These are local
  observations, not a promised startup budget or full certification.
- In the Codex in-app browser at 1280 x 720, the public synthetic administrator
  signed in through the normal form, found both fictional organizers, opened
  Maru Community Events, MaruCon and its three dated editions, then signed out.
  Reopening Organizations required sign-in. Submitting an incorrect password
  with Enter displayed the normal recoverable error. No page overflow was
  observed on the inspected series page. No product form was changed.
- The terminal tool's forced interruption stopped the browser server but left
  its database, demonstrating the documented hard-kill limit. The exact ID
  and unique ownership label were checked before removing that container and
  its anonymous volume. A final real timed-expiry run verifies unattended cleanup.

This is local implementation evidence only. Full clean exact-commit certification,
independent hosted acceptance, and protected PR delivery remain outstanding.
No PR was created or merged for this batch.

## Limits

This uses the existing local educational seed, including its public fixture
credentials, not a restricted database login or exact authority-provenance setup.
Invitation delivery remains fail-closed without its own configuration. No new
product permissions, migrations, external adapters or profile activations occur.
Linux/macOS execution, a full browser role/accessibility matrix, full exact-commit
certification and
independent hosted acceptance are not implied by the startup smoke. Other
worktrees and fixtures are out of scope. A forced host/terminal shutdown can leave
an owned container; inspect its printed ID and label before exact cleanup.

## Maintainer follow-up: incremental demo coverage

The maintainer requested ongoing and future fictional editions with items for
all available UI functions, then explicitly deferred bulk implementation in favor
of incremental coverage alongside higher-priority work. AGENTS and the demo module
now retain that direction for every commit. No seed or running demo changed.
Documentation/reference and focused documentation-policy checks cover this update;
it does not add browser or feature acceptance evidence. Full certification of the
combined workflow candidate remains required.
