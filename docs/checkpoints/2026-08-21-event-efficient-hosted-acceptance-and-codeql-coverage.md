# Event-efficient hosted acceptance and CodeQL coverage

Date: 2026-08-21
Status: Locally verified repository candidate; hosted merge-candidate
acceptance pending
Requirements: NFR-001, NFR-002, NFR-003, NFR-011
Decision: ADR 0066

## Outcome

The pull-request workflow now treats **Ready for review** as the transition from
cheap draft preflight to authoritative selected acceptance. Drafts keep an
explicitly non-green `PR gate`, returning a pull request to draft cancels
obsolete work, and the squash push to `main` no longer repeats acceptance for an
identical Git tree. No test, documentation, contract, frontend, security, or
coverage category was removed from full acceptance.

Repository safety now precedes every expensive path. Rename classification
preserves the deleted source and destination, and every destructive plan takes
the full path after maintainer review. Source, tests, repository automation,
governance records, and critical root policy/deployment files are protected.
Destructive approval is accepted only on the exact repository-owner
`destructive-change-reviewed` label event; every other pull-request event or
actor is unapproved. An issues-only, no-checkout `pull_request_target` workflow clears
stale label display state on synchronize, reopen, ready-for-review, and
conversion-to-draft events without executing contribution code or relying on a
token-generated `unlabeled` run. A maintainer reviews the current scope and
reapplies the label to create fresh approval. Unit tests are database-free; the
sole receipt/storage database test moved to integration, so full local and
hosted certification use eight PostgreSQL services rather than nine.

Targeted integration selection is now bounded by accepted timing evidence. A
missing timing map, any selected file without a timing, or a selected estimate
above 1,800 seconds routes to full acceptance. That 30-minute ceiling leaves a
15-minute setup and runtime-variance margin within the targeted job's 45-minute
timeout.

The Workforce query generic keeps its Python 3.12 semantics but no longer uses
the trailing type-parameter comma rejected by the current CodeQL parser. A
tokenizer-based repository contract prevents that spelling from silently
removing another file from analysis.

The reviewed `main` ruleset desired state now binds `PR gate` to GitHub Actions
integration ID `15368`, and the repository contract asserts the exact pair.
This candidate does not mutate or prove the live ruleset; a separately
authorized update and readback remain pending.

## Measured evidence

Pull request 8 supplied four successful lifecycle runs:

| Event | Run | Wall time | Aggregate runner-minutes |
| --- | ---: | ---: | ---: |
| Draft opened | `32412170009` | 58.75 minutes | 377.68 |
| Draft synchronized | `32418016366` | 59.42 minutes | 363.75 |
| Ready for review | `32423046566` | 59.38 minutes | 335.83 |
| Squash push to `main` | `32427570856` | 48.43 minutes | 359.40 |

The four runs consumed 1,436.66 aggregate runner-minutes. The synchronized and
ready runs were associated with the same branch head. For the ready run,
`actions/checkout` correctly tested synthetic merge commit `9899c1f` from
`refs/pull/8/merge`; that merge candidate, the branch head, and the final squash
commit all resolved to Git tree `0375e8552d7da54706b99e1644102aa9c07b7bf2`.
The post-merge run therefore repeated accepted content. The corrected normal draft-to-
ready lifecycle plus removal of the duplicate `main` run eliminates
approximately 1,100.83 full-acceptance runner-minutes, or 76.6 percent of the
measured total. The replacement draft preflights are intentionally small but
were not present as separately timed jobs in the historical runs.

Managed CodeQL run `32427570301` succeeded overall but reported that
`src/maru/workforce/queries.py` could not be analyzed at its generic header.
Python 3.12 compilation and syntax-tree comparison confirm that removing the
trailing comma is semantics-preserving. A fresh managed CodeQL run remains the
authority for restored server-side analysis coverage.

Accepted main run `32427570856` also refreshed the tracked integration timing
inventory. Seven deterministic whole-file shards project near 2,505 weighted
seconds and one indivisible shard near 2,760 seconds; newly moved files retain
the documented median fallback until accepted timings include them.

## Repository changes

- pull-request event, concurrency, draft, safety, and stable-gate behavior;
- database-free unit and eight-database full/local certification boundaries;
- lossless rename and fail-closed destructive classification;
- exact-event destructive approval and issues-only stale-label cleanup without
  checking out or executing pull-request code;
- targeted-to-full failover for missing or greater-than-1,800-second timing
  evidence;
- early release-input and exact-PR validation plus non-persistent checkout
  credentials;
- removal of dormant merge-queue and duplicate default-branch triggers;
- actual Linux uv cache-path alignment and accepted timing refresh;
- CodeQL-compatible Python syntax plus a repository regression contract; and
- GitHub Actions provenance binding for the desired required `PR gate`.

## Verification

- Actionlint, immutable-Action allowlist validation, workflow YAML contracts,
  PowerShell parsing, `uv lock --check`, and whitespace validation pass.
- Forty-nine focused classifier, workflow, release, shard, database-isolation,
  media, and CodeQL-compatibility unit contracts pass.
- All 1,909 unit tests pass in 6.16 seconds with PostgreSQL deliberately
  unreachable. The moved receipt/storage integration test passes against real
  PostgreSQL in 49.60 seconds.
- Ruff formatting and ALL-rule lint pass over 646 files; strict mypy passes over
  356 source files.
- Strict PyDocLint and semantic docstring validation pass over 365 production
  and tooling files. Documentation validation covers 276 Markdown files and 203
  unique requirement identifiers.
- A fresh warning-fatal parallel Sphinx/AutoAPI HTML build succeeds, including
  the Workforce query reference. Python 3.12 byte-compilation of that module
  also succeeds.

These results verify the local repository candidate. They do not replace the
protected hosted `PR gate` or managed CodeQL analysis for the current pull-
request revision.

## Risks and next actions

- Push the current merge candidate through hosted selected/full acceptance
  before merge.
- Confirm the next managed CodeQL Python analysis no longer reports the
  Workforce file as unprocessed.
- Reconcile ruleset `21093924` only with separate authorization, then read back
  `PR gate` with GitHub Actions integration ID `15368` and every existing
  no-bypass and CodeQL protection intact.
- Keep label events conservative; the repository owner reapplies
  `destructive-change-reviewed` only after reviewing the current destructive
  scope. The cleanup workflow is UI
  hygiene and acceptance must continue to depend only on the exact fresh label
  event. A future separately required repository-safety context could reduce
  full-gate label reruns only after live ruleset reconciliation.
- Do not infer deployment, restore/PITR, accessibility, release-recovery, or
  production readiness from repository acceptance.
