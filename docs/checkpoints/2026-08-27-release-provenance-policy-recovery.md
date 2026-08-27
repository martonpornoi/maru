# Release provenance policy recovery

Date: 2026-08-27

## Outcome

Maru's first immutable candidate did not publish. Release workflow
[`33082089911`](https://github.com/martonpornoi/maru/actions/runs/33082089911)
certified exact protected-main commit
`e3cd11ec0256a9685341fd5f5848fdcf3b0480ed`, then failed while GitHub prepared
the publication job. The runner rejected two nested Actions used by the pinned
`actions/attest-build-provenance` composite action because they were absent from
the repository's exact selected-Actions policy.

The failure happened during Action download before checkout and before any
publication step ran. Authenticated readback found no
`v2026.08.26-rc.1` Git tag, no GitHub Release, and no `maru` container package.
The run retained contributor-documentation and test/coverage artifacts but no
release-evidence bundle. The log proves the job never reached registry login,
image resolution, image build, provenance, draft, tag, asset, publication, or
verification steps. No identity-bearing artifact was deleted or overwritten.

Issue [#21](https://github.com/martonpornoi/maru/issues/21) was auto-closed by
the merged preparation pull request and was reopened because the public release
outcome remains incomplete.

## Exact failure evidence

- Release preparation PR
  [#26](https://github.com/martonpornoi/maru/pull/26) merged as exact squash
  commit `e3cd11ec0256a9685341fd5f5848fdcf3b0480ed` at
  `2026-08-27T14:23:08Z`.
- Local certification passed for exact PR head
  `c56245c7f27135dd08e32fd6bf6225dbd9d65329`: 2,060 unit tests, 2,357
  PostgreSQL integration tests across eight isolated databases, 29 frontend
  tests, complete package/static/documentation/security gates, and the 90%
  combined branch-coverage minimum.
- Protected PR run
  [`33074385861`](https://github.com/martonpornoi/maru/actions/runs/33074385861)
  passed all 19 jobs for that exact head, and managed CodeQL passed all three
  language analyses.
- Release run `33082089911` passed request and source validation, locked inputs,
  static analysis, dependency security, contributor documentation,
  Django/contracts/frontend, unit coverage, all eight PostgreSQL shards,
  combined coverage, and the full CI gate for exact merge `e3cd11e`.
- Publication job `98575370865` failed during Action preparation. GitHub named
  these missing exact patterns:
  - `actions/attest-build-provenance/predicate@864457a58d4733d7f1574bd8821fa24e02cf7538`;
  - `actions/attest@daf44fb950173508f38bd2406030372c1d1162b1`.

## Audited repair

Authenticated retrieval of `action.yml` from pinned parent
`actions/attest-build-provenance@977bb373ede98d70efdf65b84cb5f73e068dcc2a`
confirmed that the parent invokes exactly those two nested revisions, labelled
upstream as `predicate@2.0.0` and `actions/attest` v3.0.0.

The repository desired state therefore adds only those two SHAs to
`.github/actions-allowlist.json` and records the parent-to-children audit in
`.github/actions-transitive-references.json`. Both `github_owned_allowed` and
`verified_allowed` remain `false`. A repository contract test fixes the exact
parent and ordered nested pair so later parent upgrades must deliberately
refresh the audit.

The pre-change live selected-Actions read contains the exact prior 16 patterns
and both broad trust flags disabled. The desired repaired set contains 18 exact
patterns. This checkpoint does not claim the live mutation: ADR 0064 requires
separate owner authorization, exact append-only reconciliation, and complete
post-change readback before the repaired release can run.

Focused repository verification passes on the repair branch:

- the allowlist validator accepts exactly 18 direct and audited transitive
  immutable references;
- 65 workflow, release-metadata, documentation-policy, and public-repository
  tests pass;
- focused Ruff lint and formatting pass;
- documentation validation accepts 350 Markdown files, four repository skills,
  and 207 unique requirement identifiers;
- `uv lock --check` resolves the locked 108-package graph; and
- simulated PR #27 candidate metadata derives `2026.08.27`, `2026.8.27`,
  `v2026.08.27-rc.1`, and `2026.08.27-rc.1`.

## Replacement release identity and recovery

Repair PR [#27](https://github.com/martonpornoi/maru/pull/27) is the new
dedicated release pull request. Its derived candidate identity is:

- display version `2026.08.27`;
- Python version `2026.8.27`;
- tag `v2026.08.27-rc.1`;
- image tag `2026.08.27-rc.1`.

The former PR #26 can no longer be the release source after a repair advances
`main`, because the release workflow requires its release PR to be the exact
current-main merge commit. The replacement remains a pre-production,
synthetic-data evaluation candidate. It is not a gold release, production
deployment, hosted-service promise, or approval for production personal data.

## Acceptance boundary

Before merge, PR #27 still requires clean-tree exact-commit local certification
and protected hosted acceptance. Before dispatch, the live selected-Actions
policy must be separately authorized and read back as the exact 18-entry desired
set, the repository immutability API must again report enabled immediately
before dispatch, and the new tag, Release, and image identities must be unused.
Publication is complete only after the workflow verifies the immutable Release,
assets, checksums, tag target, image digest, SBOM, provenance, and attestations.
