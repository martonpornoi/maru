# Release workspace: first canonical formatting repair

Date: 2026-09-15. Partial #108/#48 delivery; no acceptance exception.

The first clean candidate, `576f19c6f1a865a4061a3c260fb01e91c8e76f9e`,
ran `scripts/certify.ps1` with `CI=true` and pinned pnpm 11.9.0 under ADR 0100.
Change classification recorded integration `deferred` and required integration
`full`. Packaging produced valid wheel/source artifacts with 205 packaged assets;
locked dependency/vulnerability checks passed. Repository-wide formatting then
failed on `tests/integration/test_scheduling_release_queries.py`.

Two assertions split by the test-style correction still had redundant multi-line
parentheses. Formatting them onto ordinary assertion lines changes neither input,
expected result, fixture world nor test count. No source behavior, threshold,
policy or native selection was changed. The complete formatter check then passed:
1,231 files already formatted. The failed run returned exit 1 and left no
`.local-ci/certification.json`; it cannot certify delivery. PostgreSQL was neither
collected nor run.

Commit the exact formatting/documentation repair and rerun the entire canonical
development gate on that clean head. No split-run waiver or prior receipt reuse.
The implementation and bounded preflight/browser evidence remain in the
[implementation checkpoint](2026-09-15-programme-guided-release-workspace.md).
Native debt is recorded on [#102](https://github.com/martonpornoi/maru/issues/102#issuecomment-5674113819),
and human acceptance on [#92](https://github.com/martonpornoi/maru/issues/92#issuecomment-5674113986).
