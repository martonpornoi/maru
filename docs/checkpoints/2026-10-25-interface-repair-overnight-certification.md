# PR #222: overnight automated certification scope

Date: 2026-10-25

## Authorized outcome

After reviewing draft PR #222, the maintainer authorized a complete overnight
automated certification, investigation of failures, and in-scope repairs. The
PR stays draft. There is no authorization to merge, activate a profile, deploy,
accept governance invitations, enter another person's password, or alter the
running manual-test environment and its retained records.

The prior development feedback is retained in the
[preparation checkpoint](2026-10-25-interface-repair-automated-preparation.md).
This follow-up changes the verification schedule only; requirements, ADRs,
domain behavior, fixtures, assertions and acceptance thresholds are unchanged.
The from-empty manual walkthrough remains the representative demo for these
repairs. No additional maintained-demo data or completed human journey is claimed.

## Execution and evidence boundary

Use the unchanged `scripts/certify.ps1` command in ordinary Auto mode against
freshly resolved protected main. Auto includes all current-schema acceptance
and the required risk-selected history. Keep the normal eight-worker limit,
coverage target, timing headroom and all security/documentation gates.

Pin the clean head, source tree and base before launching. A one-shot detached
wrapper records original console output, process identity, exit status and
before/after source hashes in fresh ignored storage. Only the repository's own
exact-head certification receipt can establish success. Preserve original
failed or interrupted evidence before another attempt; passing subsets never
certify a repaired head. Never overlap certification runs.

A periodic follow-up may inspect progress quietly and handle actionable
failures. While a run is active, do not edit its sources or start another run.
Repair only concrete failures within this PR's accepted scope, run focused
feedback, update owning documentation, commit normally and freshly certify the
new clean candidate. Do not weaken tests, native security, authorization,
coverage, timeouts, worker limits or branch protection.

Run outcomes belong in PR #222 and preserved ignored evidence while the source
is pinned. On success verify original test inventories/results, coverage,
timing headroom, source identity and owned-resource cleanup; keep independent
hosted merge acceptance and human/browser acceptance separate. Record a precise
blocker if progress requires new product authority or maintainer action.
Stop the temporary follow-up after completion or a user-dependent blocker.
