# Checkpoint: Exact Programme HTML mapping expectation

- Date: 2026-10-02 (local time; hosted finding on October 1 UTC).
- Phase: Progressive adoption and protected local-rehearsal delivery.
- Issues: #203 / PR #204, supporting #48/#92/#109/#108 without closing them.
- Requirements: NFR-001/002/003; ADR 0115 is unchanged.

## Successful previous candidate, not this follow-up

Clean `9b51c6e8d8395a3047247c45c58cbd79445ee49b`, based on protected
`314d593dc98fde705e834ef6374d001d25051942`, passed ordinary exact-commit
certification at 2026-10-01T21:39:21Z in **15,531.819s (4h18m52s)**:

- All ten gates, both dependency audits and 103 frontend tests passed.
- 13,457 unit and 5,081 PostgreSQL cases: **18,538 Python cases**, with zero
  failures, errors or skips in all 72 XML reports.
- **91.73%** combined branch-aware coverage, unchanged 90% minimum.
- All 71 unique exhaustive-history shards passed cleanup and timing headroom;
  at most eight databases ran concurrently. Exact Docker inventory confirmed
  all 71 owned containers absent.
- Slowest shard 34 took **3,172.671s (52m53s)**. The unchanged 1.5x-plus-ten-minute
  projection was **5,359.007s (89m19s)**, below the 90-minute headroom ceiling.
  This is a modest measured margin, not a guarantee of hosted duration.
- All **5,043 artifact files** were copied and individually SHA-256 compared,
  plus three worker lifecycle/log files, at
  `.tools/certification-evidence/programme-local-9b51c6e-success`.

PR #204 opened at that exact head. Initial hosted classification, repository
safety, locked inputs, static analysis, documentation, contracts/frontend,
dependency security and unit coverage passed. Managed CodeQL execution passed
but its alert protection reported a new high-severity finding. The incomplete
hosted PostgreSQL run is not acceptance; it was cancelled once this follow-up
became necessary. Its aggregate gates fail because required jobs were cancelled,
not because a PostgreSQL assertion or timeout was observed. No complete hosted
acceptance or time-limit failure is claimed.

## Finding and bounded repair

[Alert 22](https://github.com/martonpornoi/maru/security/code-scanning/22), Python
analysis `1877599083` at `refs/pull/204/head`, reported
`py/incomplete-url-substring-sanitization` on a pytest assertion that the literal
fictional `https://other.invalid/` anchor remains in synthetic response HTML.
That assertion does not authorize a URL, select an upstream or return a redirect.
The real fixed-origin and parsed local-path restrictions are separate.

Replace three partial assertions about the output with one complete expected-HTML
equality check. This is stronger evidence: the owned anchor must be mapped
exactly and the unrelated anchor must remain exactly intact, with no extra or
missing bytes. Keep the foreign-redirect rejection, opaque-download preservation,
Host/Origin/framing, pinned TLS, lease, cookie and session tests unchanged.

No finding was dismissed and no query, security threshold, coverage requirement,
runtime transport, production surface, permission, migration or fixture authority
changed. No source suppression was added. A fresh hosted scan, not an assumption
about the query, must establish the result for the revised commit.

## Focused verification and preserved failure

The unchanged two gateway/session unit files passed **100 cases / 1.08s** during
triage. The stronger assertion passes the same **100 cases / 1.10s**, with Ruff
lint and formatting also passing. JUnit reports are retained separately.

The first focused invocation could not use the existing shared Windows pytest
temporary directory: **19 passed, 81 setup errors** with `WinError 5`. Its XML
is retained at `.tools/pr204-codeql-test-assertion-review.xml`. A fresh, explicitly
task-owned repository temporary directory solved that environment problem
without changing shared permissions, deleting unrelated data or changing source.
Two preceding unavailable/sandboxed executable launches ran no tests.

Complete inexpensive units pass **13,457 / 84.56s**, with three existing Django
URL-field warnings. Documentation validation passes **706 Markdown files**, four
repository skills and 215 requirement identifiers; whitespace checks pass.
Fresh ordinary exact-commit certification remains required
for this follow-up. The successful previous receipt cannot certify changed source.
Keep the old evidence intact,
require the revised exact-head PR gate and CodeQL before match-head squash, and
retain all independent-human, specialist-accessibility and activation boundaries.
