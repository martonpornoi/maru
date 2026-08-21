# ADR 0066: Event-efficient fail-closed hosted acceptance

- Status: Accepted
- Date: 2026-08-21
- Requirements: NFR-001, NFR-002, NFR-003, NFR-011
- Refines: ADR 0060 decision 3, ADR 0061 decisions 4 and 5, and ADR 0063
  decisions 1 and 2
- Supersedes: ADR 0061's nine-PostgreSQL-service count; ADR 0063 decision 1's
  merge-group coverage, decision 3's exact-head wording, and decision 4's
  nine-container count

## Context

Pull request 8 supplied the first complete public-runner measurement after the
repository hardening milestone. Draft open, draft synchronize, ready-for-review,
and squash-push events each invoked complete acceptance. The four successful
runs used 1,436.66 aggregate runner-minutes. The ready event was associated with
the same head as the preceding draft run. GitHub checked out synthetic merge
commit `9899c1f` for that ready event; its tree, the pull-request head tree, and
the final squash-commit tree were identical. The post-merge run therefore
retested identical content for another 359.40 runner-minutes.

The job categories were not the source of that duplication. Static analysis,
warning-fatal documentation, generated contracts and frontend acceptance,
dependency security, unit coverage, every PostgreSQL integration file, and
combined coverage remain distinct necessary evidence. The separate relevant,
unit, and targeted jobs are intentionally skipped when reusable full acceptance
supersedes them.

The audit also found four fail-closed gaps. Repository safety did not precede
expensive fan-out. Git rename parsing discarded the source path, so a protected
file could be renamed out of a protected prefix without deletion review.
Approved destructive changes did not necessarily invoke full coverage. Finally,
one PostgreSQL-backed receipt test was misplaced among otherwise non-database
unit tests, causing every unit run to start an unnecessary database service.

The final timing and trust-boundary review found three more gaps. Common module
changes could select more than the targeted lane's 45-minute timeout, an old
destructive-review label could survive a new head, and the required check name
was not bound to its expected GitHub Actions integration in desired state.

GitHub treats a skipped required job as a successful result. Draft and label
optimization therefore cannot safely skip the stable `PR gate`. CodeQL also
successfully completed its overall Python analysis while reporting that one
Workforce query module was omitted because its parser rejected a valid trailing
comma in a Python 3.12 PEP 695 type-parameter header.

## Decision

1. Draft pull requests run only change classification and the cheap locked-input
   and Actions-policy preflight. Their stable `PR gate` fails explicitly with a
   draft-not-certified explanation. `ready_for_review` is the authoritative
   transition into selected acceptance. Ready `synchronize`, ready `reopened`,
   and non-draft `opened` events continue to run it. `converted_to_draft`
   cancels an obsolete in-progress run and replaces any prior green gate with
   an explicit non-green draft result.
2. Keep `labeled` and `unlabeled` pull-request events. GitHub cannot filter them
   by label name at the workflow trigger, and a skipped required gate could
   weaken enforcement. These rare events may rerun acceptance so adding or
   removing `destructive-change-reviewed` is reflected safely. Acceptance sees
   that approval only on the exact repository-owner `labeled` event whose label
   is `destructive-change-reviewed`; every other pull-request event or actor
   supplies an empty approval set. A separate `pull_request_target` workflow removes stale
   label display state on synchronize, reopen, ready-for-review, and
   conversion-to-draft events. It has only `issues: write`, checks out no
   contribution, and executes no pull-request code. Its GitHub-token mutation
   is UI cleanup, not a relied-upon `unlabeled` retrigger. A maintainer must
   inspect the current scope and reapply the label to create a fresh approval
   event.
3. Remove the pull-request workflow's `push` trigger for `main`. The strict
   up-to-date `PR gate`, pull-request-only squash merge, and empty bypass list
   establish the merge boundary. Retain GitHub-managed CodeQL on default-branch
   pushes, manual full acceptance, and release recertification. A future Pages
   or deployment workflow owns its own smallest main-only path.
4. Make repository safety a prerequisite of every selected expensive path.
   Preserve both sides of a rename as source deletion plus destination change.
   Every protected or mass deletion requires the review label and full
   acceptance. Source, tests, repository automation, governance records, and
   critical root policy/deployment files are protected deletion surfaces.
5. Keep the unit job but make `tests/unit` database-free. Move its single
   receipt/storage database test into integration and use an unreachable test
   URL so accidental unit database access fails. Full and local certification
   now start eight isolated PostgreSQL services, one for each measured
   integration shard, instead of nine.
6. Refresh file weights from accepted main run `32427570856`. Preserve
   deterministic whole-file scheduling and the median fallback for the newly
   moved integration file in full sharding. A targeted plan fails closed to
   full acceptance when the accepted timing map is missing, any selected file
   lacks an accepted timing, or the selected estimate exceeds 1,800 seconds.
   The 30-minute execution ceiling preserves 15 minutes for setup and runtime
   variance inside the targeted lane's 45-minute timeout. Use uv's actual Linux
   cache path, remove the dormant `merge_group` trigger until a workflow emits
   the required `PR gate`, and reject invalid release dispatch inputs or a
   mismatched release PR before full certification starts.
7. Set `persist-credentials: false` for every checkout because no CI or release
   job performs an authenticated Git write. GitHub CLI operations continue to
   receive the explicitly scoped workflow token where needed.
8. Remove the Workforce header's trailing type-parameter comma without changing
   its generic bound or runtime behavior. Until the active CodeQL parser accepts
   that valid CPython form, a tokenizer-based repository contract rejects the
   incompatible spelling so a future formatter or edit cannot silently remove
   a Python file from security analysis.
9. Bind the normalized desired-state `PR gate` to GitHub Actions integration ID
   `15368` as well as its context name. A status from another integration with
   the same display name must not satisfy Maru's merge boundary. This repository
   change does not mutate the active ruleset; reconciliation and readback remain
   a separately authorized external operation.

## Consequences

- A normal draft-to-ready pull request performs one authoritative selected run,
  not a complete run for every draft event plus another on readiness. The
  identical-tree squash push no longer repeats source acceptance.
- Drafts deliberately show a red `PR gate`; this is workflow state, not a claim
  that the draft's cheap preflight failed. Marking the pull request ready starts
  the gate that can become mergeable.
- An unapproved destructive change fails before any PostgreSQL service starts.
  Applying the review label does not bypass evidence; it permits the mandatory
  full path to run. Under the sole-maintainer policy, only the exact fresh owner
  label event conveys approval; all other actors and lifecycle events are
  unapproved, independently of whether stale UI cleanup has completed.
- Successful full acceptance retains all test categories and eight independent
  PostgreSQL integration databases. The standalone selected-path unit job uses
  no database, so an ordinary Python pull request starts at most one targeted
  PostgreSQL service.
- The refreshed accepted timings project seven shards near 2,505 weighted
  seconds and one indivisible shard near 2,760 seconds. Runtime variation and
  the longest whole file still bound wall-clock latency. Targeted selection is
  bounded by accepted evidence; missing or stale file coverage cannot silently
  create an unbounded targeted run.
- Label changes remain potentially expensive because the required stable gate
  reruns conservatively. The issues-only, no-checkout `pull_request_target`
  cleanup is intentionally limited to removing stale display state; acceptance
  does not depend on its token-generated event, and it must never execute
  contribution code.
- Managed CodeQL remains the only CodeQL workflow. The compatibility contract
  can be removed when Maru verifies that the active GitHub parser accepts
  trailing commas in PEP 695 headers without losing file coverage. Default setup
  still omits fork pull requests, and native CodeQL merge protection does not
  apply to Dependabot pull requests; `PR gate` plus default-branch and weekly
  scans remain the documented boundary for them.
- The checked-in GitHub Actions integration binding is desired state until a
  fresh authorized ruleset update and readback confirms it on the server.

## Alternatives considered

### Skip `PR gate` while a pull request is a draft

Rejected because GitHub counts skipped required jobs as successful. An explicit
non-green draft result makes the readiness boundary unambiguous and closes the
stale-success window.

### Keep complete draft acceptance and remove `ready_for_review`

Rejected because it spends the most work before the author requests review and
cannot cancel acceptance when a ready pull request returns to draft. Readiness
is the natural point for independently recorded merge acceptance.

### Keep the `main` push run as defense in depth

Rejected for the current repository because the accepted merge candidate, pull-
request head, and measured squash commit had the same tree, branch rules require
an up-to-date gate, and no bypass actor exists. Managed CodeQL and release
certification retain their distinct default-branch and publication purposes.

### Enable every job currently shown as skipped

Rejected because the full reusable workflow already contains the equivalent
quality, unit, and integration evidence. Enabling both paths would duplicate
tests and database services without increasing coverage.

### Keep PostgreSQL attached to the unit job

Rejected after moving the only database-backed test to its correct integration
layer. A database-free unit boundary is faster, cheaper, and more diagnostic.

## Requirements affected

- NFR-001 retains every evidence category while making event selection,
  destructive routing, unit isolation, and CodeQL file coverage executable.
- NFR-002 requires contributor, testing, governance, release, and local
  certification documentation to describe the draft/ready and eight-database
  topology accurately.
- NFR-003 requires the measured runs, local verification, remaining hosted
  acceptance, and deferred label optimization to remain resumable.
- NFR-011 gains fail-closed rename handling, safety-before-fan-out ordering,
  non-persistent checkout credentials, GitHub Actions status provenance, and an
  exact protected acceptance event boundary.
