# Checkpoint: Programme frontend-tool audit repair

- Date: 2026-10-01
- Phase: Protected #203 delivery preparation; acceptance remains pending.
- Related requirements: NFR-001/002/003/011/013.
- Related ADRs: 0063/0064, 0090, 0098, 0115.

## Failure and scope

After the Python audit repair, clean candidate
`5179164131a15d8202dfa8528330031e6ac72dc8` passed that audit but failed the required
`pnpm audit --audit-level high`. The complete audit reports thirteen advisories:
four high, six moderate and three low, all in two development-only transitive
dependencies. This is another bounded #203 delivery prerequisite, not a change
to Programme authority, production routing or acceptance policy.

Undici 7.29.0 is used by jsdom, including Vitest's jsdom integration. Its upstream
[7.29.1 release](https://github.com/nodejs/undici/releases/tag/v7.29.1) fixes the ten
reported advisories, including lost TLS-validation callbacks and WebSocket
protocol/error handling. The supported Node floor remains `>=20.18.1`; the local
Node is 24.11.1. No application fetch implementation or transport setting changes.

brace-expansion 2.1.4 is used by minimatch beneath OpenAPI TypeScript generation.
The upstream fixes address [comma-parser stack exhaustion](https://github.com/juliangruber/brace-expansion/security/advisories/GHSA-6j4f-fj2g-mc7p),
[nested expansion stack exhaustion](https://github.com/juliangruber/brace-expansion/security/advisories/GHSA-qhr7-859c-m2p7)
and [quadratic rewrite work](https://github.com/juliangruber/brace-expansion/security/advisories/GHSA-q2hr-2g5m-vwhr).
The final fix is present in 2.1.7. These fixes bound unreasonable parser input;
the ordinary generated API contract must still reproduce unchanged.

## Bounded repair and recovery

Update the existing 2.x brace-expansion override to 2.1.7 and add an Undici 7.x
security floor at 7.29.1. Both selectors affect only older versions in the same
major. Pinned pnpm **11.9.0** regenerates the lock; only these two package versions,
integrities, references and matching overrides change. Direct dependencies,
React, the test framework, bundler, TypeScript, Node, package manager and other
transitive versions remain unchanged. No advisory is ignored or threshold lowered.

The failed candidate's database work was cancelled through the maintained
`.local-ci/cancel-pool` control, not killed or counted as passing. All eight started
shards report interrupted failure and owned container removal; zero completed
successfully. Its units passed **13,457 / 164.08s**, with three existing warnings.
The worker exited 1. No complete certification receipt exists.

Actual worker/pool processes and owned containers were absent before the repair.
All **820** surviving artifact files were copied and individually SHA-256 compared
under `.tools/certification-evidence/programme-local-5179164-js-audit-failed/local-ci`;
the sibling inventory and worker metadata preserve the failure. Earlier evidence
remains untouched. The complete audit is also retained in
`.tools/programme-203-js-audit-20261001.json`.

## Verification and remaining delivery

Complete fast units pass **13,457 / 74.24s**. The three existing Django URL warnings
remain; a fourth warning records inability to write the shared local pytest cache.
No test failed or was skipped, and unrelated cache ownership/permissions were not
changed. Ordinary certification uses its own fresh repository-contained environment.

Both current-tree dependency audits report **no known vulnerabilities**. Complete
`scripts/check.ps1 -SkipPythonTests` feedback passes in **326.96s (5m27s)** with
pinned pnpm 11.9.0 and `CI=true`: frozen installation, package verification,
repository-wide static and docstring checks, documentation validation, fresh
warning-fatal Sphinx, Django/settings/migration checks, generated API/output
parity, frontend typecheck, **103 frontend tests / 24.07s**, and production build.
Generated TypeScript and distributed browser assets remain unchanged. This
pre-check starts no PostgreSQL pool and does not replace clean exact-head
certification or GitHub's independent protected gate.

The joined eighteen-phase native rehearsal remains attributed to `0d2a3aa`.
No new human/browser evidence, protected delivery, activation or deployment is
claimed by these dependency repairs. #92/#109/#108/#48 remain open.
