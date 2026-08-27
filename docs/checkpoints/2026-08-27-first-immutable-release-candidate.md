# First immutable release candidate

- Date: 2026-08-27
- Status: Prepared through dedicated release pull request #26; publication is
  performed only after protected merge and the live immutable-release preflight
- Release: `Maru 2026.08.26 release candidate 1`
- Tag: `v2026.08.26-rc.1`
- Python version: `2026.8.26`
- Requirements: NFR-001, NFR-002, NFR-003, and NFR-011
- Decisions: ADR 0060, ADR 0065, and ADR 0067; no new ADR

## Outcome

This dedicated release change turns Maru's curated **Unreleased** notes into
the dated `2026.08.26` release section and aligns the Python project and lock
metadata with the CalVer derived from pull request #26. It prepares Maru's
first public pre-production candidate for evaluation with synthetic data.

The release is not a gold or production-readiness claim. It does not provision
an application deployment, database, secrets, mail, payments, object storage,
workers, telemetry, backups, governance, or production personal-data approval.

## Intended public evidence

The manual Release workflow must run from the exact protected-main squash
commit produced by pull request #26. It will:

- re-run complete source certification;
- build and publish the non-root GHCR application image once;
- attach contributor documentation, OpenAPI, dependency locks, licenses,
  release manifest, checksums, SBOM, and provenance;
- create and verify one complete draft GitHub Release before publication;
- publish the candidate only after that draft matches the intended tag, commit,
  prerelease state, asset names, uploaded state, and SHA-256 digests; and
- verify immutable release and asset attestations, exact tag targeting, the OCI
  digest binding, and image provenance after publication.

The exact protected-main merge commit is intentionally resolved by GitHub at
merge and retained in the release manifest and workflow evidence; this source
checkpoint does not predict a commit that does not yet exist.

## Curated scope

The dated changelog describes the public repository landing experience,
Workforce-only adoption, the governed Structure-through-Shifts journey,
warning-fatal contributor documentation, release and collaboration controls,
and the established security evidence boundary. GitHub's generated categorized
pull-request list supplements those maintained notes rather than replacing
them.

## Data, migration, and recovery

This release preparation changes version and documentation metadata only. It
adds no Django model, migration, API, browser behavior, database permission,
personal-data processing, or runtime deployment mutation.

Once published, the candidate, tag, image, assets, and attestations are
immutable. A failure after any identity-bearing artifact is created consumes
`rc.1`; recovery must inspect retained evidence, correct source through a new
protected pull request when needed, and use `rc.2` or a new CalVer. Nothing may
be deleted or overwritten merely to reuse the identity.

## Acceptance and publication boundary

Before merge, the exact final pull-request head must pass clean-tree local
certification and GitHub's authoritative hosted `PR gate`. Immediately before
dispatch, an authenticated administrator read must confirm release
immutability is still enabled. Publication then requires the explicit
candidate `rc.1` workflow dispatch authorized for this release task.

Post-publication closure must record the public release URL, exact tag and
commit, workflow run, assets and checksums, release and asset attestations,
GHCR image digest, SBOM, provenance, and any remaining external gates without
misrepresenting the candidate as production approval.

## Preparation verification

- `uv lock --check` resolves the locked 108-package graph with project version
  `2026.8.26`.
- A local metadata preflight for pull request #26, a 2026-08-27 merge,
  candidate number 1, and a valid 40-character source commit accepts the dated
  changelog and derives `v2026.08.26-rc.1`.
- Forty-seven focused release-metadata, release-evidence, workflow-contract,
  and public-material tests pass.
- Documentation policy validates 349 Markdown files, four repository skills,
  and 207 unique requirement identifiers.
- `git diff --check` passes for the preparation diff.

Complete clean-tree local certification and authoritative hosted acceptance
remain required for the exact final pull-request head before merge. The pull-
request description carries that exact-commit evidence once it exists.
