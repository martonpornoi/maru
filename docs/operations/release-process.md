# GitHub release process

## What a Maru release means

A GitHub Release is one certified source commit plus an immutable GHCR
application image and its evidence. It does not provision a database, secrets,
SMTP, payments, object storage, workers, telemetry, backups, or production
governance. Passing the workflow means the repository-controlled quality gates
passed; the external gates in the deployment runbook remain separate.

Repository release immutability is enabled and applies to future published
releases. Once published, release assets and the associated tag cannot be
modified or deleted in place, and GitHub produces a release attestation for the
tag, commit, and attached assets. A draft remains a staging boundary until it is
published.

Maru is not currently published to PyPI. Its primary consumer runs a Django
service, so an OCI image is more useful than a wheel. Source archives generated
by GitHub remain available, while the attached docs, OpenAPI schema, locks,
manifest, checksums, SBOM, and provenance make a release inspectable.

## Version identity

Stable CalVer uses ``YYYY.MM.PR`` where the calendar comes from the merge time
of a dedicated release pull request. Git tag and release title use the padded
display form, while `pyproject.toml` uses PEP 440's unpadded numeric form.

| Purpose | Example for PR 2 merged in August 2026 |
| --- | --- |
| Python project | `2026.8.2` |
| Candidate | `v2026.08.2-rc.1` |
| Gold | `v2026.08.2` |
| Ephemeral PR build | `pr-2.dev.3.g68867ea` |

Branch names never enter a stable release. Before gold, increment `rc.N` for a
new candidate. After gold, merge a new fix pull request and use its new CalVer;
never replace a tag, release, image, checksum, SBOM, or attestation.

## Candidate and gold procedure

1. Open a dedicated release pull request from current `main`. Update
   `pyproject.toml` to the derived PEP 440 version and curate release notes,
   migration/recovery plan, operator limits, and checkpoint.
2. Let `PR gate` pass, resolve conversations, and squash-merge. Do not merge
   another pull request before starting this release: the release workflow
   requires the release PR merge commit to be the exact current `main` commit.
3. Immediately before dispatch, use an authenticated administrator session to
   read the live release policy:

   ```powershell
   gh api repos/martonpornoi/maru/immutable-releases `
     -H "X-GitHub-Api-Version: 2026-03-10"
   ```

   Continue only when the response contains `"enabled": true`. The endpoint
   requires administrator read access, which the deliberately narrow workflow
   token does not receive. Do not create a persistent administrator token for
   this check.
4. Run **Release** from `main` with the merged PR number. Select `candidate` and
   a positive candidate number for rehearsal, or `gold` for intentional public
   support. Set **release_immutability_verified** only after step 3. The
   workflow-dispatch record preserves this maintainer confirmation. GitHub
   environment approval may pause publication.
5. The workflow rejects invalid branch, immutability, and channel inputs and
   requires the release PR to be merged into `main` at the exact workflow commit
   before rerunning full acceptance. It then rejects identity collisions, builds
   and pushes the image once, and records its digest and attestations. It creates a
   draft release with the complete asset set, verifies its exact commit, tag,
   asset names, uploaded state, and SHA-256 digests, and only then publishes it.
6. After publication, the workflow requires GitHub to report the release as
   immutable, verifies the release and every attached asset against GitHub's
   release attestation, confirms the tag still targets the certified commit,
   confirms the image tag resolves to the certified digest, and verifies the
   image provenance attestation.
7. Verify the release page, assets and checksums, OCI digest, SBOM/provenance,
   collected private API assets, synthetic deployment, migrations, readiness,
   rollback/forward-fix procedure, and required human governance gates.

If publication fails after the image, draft, tag, or immutable release was
created, do not overwrite or delete it merely to reuse the identity. The
workflow uploads the available draft, published-release, release-attestation,
asset-attestation, image-attestation, manifest, and checksum evidence even when
a later verification fails. Inspect that evidence, correct the cause in a new
pull request if source must change, and use a new candidate sequence or CalVer.
Gold publication requires an explicit recovery decision.

## Consumer verification

For a published tag, verify GitHub's immutable-release attestation and a
downloaded asset with:

```powershell
gh release verify v2026.08.2-rc.1 --repo martonpornoi/maru
gh release verify-asset v2026.08.2-rc.1 .\downloaded-asset `
  --repo martonpornoi/maru
```

Verify the OCI image provenance by immutable digest rather than by tag alone:

```powershell
gh attestation verify `
  oci://ghcr.io/martonpornoi/maru@sha256:<digest> `
  --repo martonpornoi/maru
```
