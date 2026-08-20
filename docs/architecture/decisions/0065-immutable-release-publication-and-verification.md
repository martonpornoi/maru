# ADR 0065: Immutable release publication and verification

- Status: Accepted
- Date: 2026-08-20
- Requirements: NFR-001, NFR-002, NFR-003, NFR-011
- Refines: ADR 0060 decisions 6 and 7

## Context

ADR 0060 made a Maru release one exact `main` commit, one immutable GHCR image,
and one inspectable GitHub evidence bundle. The repository already rejected tag,
release, and image collisions and created the GitHub Release only after complete
acceptance and image publication. It did not prove that GitHub release
immutability was enabled or verify the server-side release and automatic release
attestation after publication.

Repository release immutability was enabled on 2026-08-20. An authenticated
administrator readback of `GET /repos/martonpornoi/maru/immutable-releases`
returned `enabled: true` and `enforced_by_owner: false`. GitHub applies this
setting only to future releases. At the same observation boundary, Maru had no
release, tag, package deployment, or environment deployment. The `candidate`
and `gold` environments each allowed only the exact `main` branch, disallowed
administrator bypass, had no required reviewer, and contained no secret or
variable.

GitHub recommends assembling an immutable release as a draft, attaching every
asset, and publishing only when complete. A published immutable release locks
its assets and associated tag and receives a GitHub release attestation. The
repository workflow therefore needs a visible pre-publication evidence boundary
and machine-verifiable post-publication checks.

The immutable-release settings endpoint requires repository-administration read
access. A workflow `GITHUB_TOKEN` is a short-lived GitHub App installation token
with repository content, package, identity-token, and attestation permissions;
the workflow permission vocabulary does not provide repository-administration
read access. Adding a long-lived administrator token solely to inspect this
setting would enlarge the release trust boundary and contradict the otherwise
empty `candidate` and `gold` environments.

## Decision

1. Require the releasing maintainer to read the immutable-release administrator
   endpoint immediately before dispatch. The manual Release workflow records an
   explicit `release_immutability_verified` confirmation. This is accountable
   maintainer evidence, not a claim that the workflow token independently holds
   administrator authority.
2. Preserve the exact-current-`main`, merged-release-PR, version, collision,
   environment, complete-certification, GHCR, SBOM, and provenance boundaries
   from ADR 0060. Do not add an administrator token, environment secret, or
   environment variable for release-policy inspection.
3. Create the GitHub Release explicitly as a draft with the complete intended
   asset set. Before publication, read the draft through GitHub's API and require
   the exact tag, target commit, candidate/gold classification, draft state,
   asset names, non-empty uploaded state, and local-to-remote SHA-256 equality.
4. Publish only the verified draft. After publication, retry boundedly for
   GitHub's asynchronous evidence, then require the release to report immutable,
   non-draft state with the same exact commit and assets. Verify GitHub's release
   attestation, verify every local asset against that attestation, require the
   image tag to resolve to the certified OCI digest, and verify image provenance
   issued by Maru's exact Release workflow. Retain the API responses and
   verification results in the workflow evidence artifact even when a later
   verification step fails.
5. Keep `candidate` and `gold` restricted to exact `main` with administrator
   bypass disabled and no required reviewer while Maru has one maintainer. Add an
   independent gold reviewer only after a second trusted maintainer exists; a
   self-review requirement is not independent control.
6. Treat the first candidate as a separately authorized public-release
   rehearsal. It requires a dedicated release pull request, the derived CalVer,
   complete hosted acceptance, and an intentional `rc.1` publication. Enabling
   immutability and implementing verification do not themselves authorize a
   release, tag, package, or deployment.
7. Never delete or overwrite a failed published release, tag, image, asset, or
   attestation to reuse an identity. A failure after image push or draft/tag
   creation consumes that candidate identity; use a new candidate number. A fix
   after gold requires a new release pull request and CalVer.

## Consequences

- A release cannot be published until its complete local evidence agrees with
  GitHub's draft representation and intended exact target commit.
- Consumers receive locked release assets and tags plus GitHub's automatic
  release attestation, while the OCI image retains its independent build and
  provenance evidence.
- The workflow fails visibly if release immutability was disabled despite the
  maintainer confirmation. Because the server exposes this setting only to an
  administrator, avoiding a persistent administrator credential requires the
  pre-dispatch readback to remain an explicit maintainer operation.
- A verification failure after publication cannot roll back an immutable
  release. The red workflow, retained evidence, and new-identity recovery rule
  are the correct failure state.
- One-maintainer environments remain usable without pretending that self-
  approval supplies separation of duties.

## Alternatives considered

### Store an administrator token in the release environments

Rejected because the token would add long-lived repository-administration
authority to a workflow that otherwise needs only content, package, identity-
token, and attestation permissions. The manual administrator readback plus
post-publication server verification keeps the smaller trust boundary.

### Publish directly and inspect the release afterward

Rejected because immutability would lock an incomplete or incorrect asset set.
The explicit draft boundary makes asset and commit verification precede the
irreversible publication transition.

### Require a gold reviewer immediately

Rejected while one maintainer exists because self-review is not independent and
an unavailable reviewer would deadlock release recovery. ADR 0060's second-
maintainer trigger remains the correct boundary.

### Publish a synthetic candidate while implementing the policy

Rejected because even `rc.1` creates a real public tag, release, GHCR image, and
attestations. That externally visible rehearsal requires a dedicated release
pull request and explicit publication decision.

## Requirements affected

- NFR-001 gains exact draft, immutable-release, asset, tag, image, and
  attestation verification contracts.
- NFR-002 requires the release runbook to preserve the administrator preflight,
  irreversible failure behavior, and consumer verification commands.
- NFR-003 requires a checkpoint that distinguishes the live setting, repository
  candidate, and still-unperformed candidate release.
- NFR-011 gains the immutable publication and post-publication reconciliation
  boundary.
