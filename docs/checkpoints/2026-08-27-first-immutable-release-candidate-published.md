# First immutable release candidate published

Date: 2026-08-27

## Outcome

[Maru 2026.08.27 release candidate 1](https://github.com/martonpornoi/maru/releases/tag/v2026.08.27-rc.1)
is the project's first visible GitHub Release. GitHub reports it as an immutable
prerelease published at `2026-08-27T19:53:09Z`.

The Release intentionally leads with the curated `2026.08.27` changelog
section and exact source/image evidence. GitHub's generated release notes then
show categorized pull-request titles, including release PR
[#27](https://github.com/martonpornoi/maru/pull/27). This closes the repository
experience gap tracked by
[#21](https://github.com/martonpornoi/maru/issues/21).

This is a pre-production, synthetic-data evaluation candidate. It is not a
gold release, production deployment, supported hosted service, production
personal-data approval, or completion of external operational gates.

## Recovery boundary

The first release attempt from PR #26 failed while GitHub prepared the
publication job because the selected-Actions policy omitted two exact nested
dependencies of the pinned provenance composite Action. That run failed before
checkout and before creating an image, package, draft, tag, Release, or
release-evidence artifact. Nothing identity-bearing was deleted or reused.

PR #27 added only the two authenticated upstream nested SHAs to the checked-in
policy and recorded their parent relationship. Both broad trust flags stayed
disabled. With explicit owner authorization, the live policy was reconciled
from the exact protected-main 16-entry pre-state to the reviewed 18-entry
target. Immediate readback proved exact parity with
`github_owned_allowed=false` and `verified_allowed=false`.

The detailed failed-attempt evidence remains in the
[release provenance policy recovery checkpoint](2026-08-27-release-provenance-policy-recovery.md).

## Exact source and certification

Release PR #27 used:

- display version `2026.08.27`;
- Python version `2026.8.27`;
- tag `v2026.08.27-rc.1`;
- image tag `2026.08.27-rc.1`; and
- exact certified PR head
  `7873c52dd2f368bcc751a897952e078935a2b420`.

Clean-tree local certification passed that exact head with locked dependencies,
package and legal verification, Ruff, mypy, PyDocLint, warning-fatal
Sphinx/AutoAPI, dependency audits, 29 frontend tests, 2,061 unit tests, 2,357
isolated-PostgreSQL integration tests across eight shards, and the required 90%
combined branch-coverage minimum.

Protected pull-request run
[`33096490372`](https://github.com/martonpornoi/maru/actions/runs/33096490372)
passed all 22 jobs, including the exact Actions-policy gate, all eight
PostgreSQL shards, combined coverage, the full high-risk gate, and stable
`PR gate`. Managed CodeQL passed Actions, JavaScript/TypeScript, and Python for
the same head. PR #27 then squash-merged at `2026-08-27T18:27:23Z` as exact
commit `be0b21db9ba2d2a956bd192a1d66c537d702c4c4`.

Immediately before dispatch, authenticated live readback proved:

- the selected-Actions policy exactly matched the checked-in 18-entry set;
- immutable Releases were enabled through the administrator API;
- Dependabot, code-scanning, and secret-scanning each had zero open alerts;
- remote `main` still equalled exact release commit `be0b21d`; and
- the candidate tag, GitHub Release, container package, and image tag were
  unused.

## Publication evidence

Release run
[`33103766556`](https://github.com/martonpornoi/maru/actions/runs/33103766556)
ran from exact `main` commit `be0b21d` and passed all 19 jobs. It repeated the
complete exact-source certification matrix before entering publication.

Independent post-publication readback proved:

- GitHub reports the Release as immutable, non-draft, and prerelease;
- `gh release verify v2026.08.27-rc.1` succeeds;
- tag `v2026.08.27-rc.1` resolves exactly to `be0b21d`;
- the Release contains exactly eight uploaded assets: `LICENSE`, contributor
  documentation, `openapi.yaml`, `pnpm-lock.yaml`, `release-manifest.json`,
  `SHA256SUMS`, `THIRD_PARTY_NOTICES.md`, and `uv.lock`;
- all eight downloaded assets pass individual GitHub Release-attestation
  verification;
- all seven payload hashes match `SHA256SUMS`, whose own SHA-256 digest matches
  GitHub's immutable asset record;
- `release-manifest.json` exactly records PR #27, commit `be0b21d`, candidate
  identity, and image digest
  `sha256:a44de03a4fe7bd5b3a5aaf73dd83b565b727a98bf895bf80416981e869eeb445`;
- GHCR resolves `ghcr.io/martonpornoi/maru:2026.08.27-rc.1` to that same
  immutable OCI index digest; and
- SLSA v1 provenance verification succeeds with the signer constrained to
  `.github/workflows/release.yml`, source ref `refs/heads/main`, and exact
  source digest `be0b21d`.

The workflow retains a release-evidence artifact plus the complete unit,
integration, documentation, combined-coverage, and Docker build records. Issue
#21 contains the public verification summary and is closed as completed.

The post-publication repository handoff passes 19 focused documentation and
public-material regressions, documentation policy across 351 Markdown files,
four repository skills, and 207 unique requirement identifiers, and the
complete warning-fatal Sphinx/AutoAPI build.

## Recovery and limitations

The tag, Release, assets, and image are immutable identities. Do not delete,
overwrite, or reuse them to repair a future defect. Candidate defects require
a new candidate identity and, when source changes, a new dedicated release pull
request from then-current protected `main`.

No production claim follows from this release. Gold publication, provider
certification, representative restore and stopped-operation rehearsal,
deployment, accessibility, privacy, safeguarding, performance, training, and
owner acceptance remain explicit gates.
