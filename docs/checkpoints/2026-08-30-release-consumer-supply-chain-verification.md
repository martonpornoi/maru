# Checkpoint: Reproducible release-consumer supply-chain verification

- Date: 2026-08-30
- Phase: Progressive adoption and pre-production release evaluation
- Related requirements: NFR-002, NFR-003, NFR-011, NFR-012
- Related ADRs: [ADR 0060](../architecture/decisions/0060-protected-collaboration-and-release-evidence.md), [ADR 0065](../architecture/decisions/0065-immutable-release-publication-and-verification.md)
- Related issues: [#40](https://github.com/martonpornoi/maru/issues/40), parent evaluation [#29](https://github.com/martonpornoi/maru/issues/29)

## Outcome

One maintained, parameterized consumer path now verifies the complete public
supply-chain relationship for an immutable Maru release. The
[release process](../operations/release-process.md#consumer-verification) calls
`scripts/verify_release_consumer.py` with independently obtained repository,
tag, source commit, mutable image tag, and immutable image digest inputs. The
tag-derived CalVer independently supplies the expected release pull request,
channel, candidate number, version, image tag, title, and prerelease state.

The verifier requires GitHub CLI 2.96.0 or later, an already authenticated
GitHub CLI session, Git, and Docker Buildx `imagetools`. It creates one new
local directory, downloads every attached asset, and fails on unsafe names,
links or reparse points, nested entries, missing or extra files, duplicate JSON
keys, scalar type substitution, byte drift, or any relationship mismatch. It
does not execute or extract downloaded content and performs no remote mutation.
Relative destinations become absolute before commands run, all networked
GitHub CLI operations are pinned to `github.com`, and the final local and
mutable-image identities are rechecked immediately before success.

The exact candidate invocation passed on 2026-08-30 for:

- repository `martonpornoi/maru`;
- tag `v2026.08.27-rc.1`;
- source `be0b21db9ba2d2a956bd192a1d66c537d702c4c4`;
- image `ghcr.io/martonpornoi/maru:2026.08.27-rc.1`; and
- OCI index digest
  `sha256:a44de03a4fe7bd5b3a5aaf73dd83b565b727a98bf895bf80416981e869eeb445`.

The result verified all eight attached assets and all seven checksum payloads,
reconciled the manifest with the actual merged, `main`-based release PR #27 and
its exact merge commit and instant, resolved the public tag and mutable image
tag independently, inspected an SPDX 2.3 document with 179 uniquely identified
packages and
Syft `v1.51.0` plus BuildKit `v0.32.2` generators, and accepted exactly one
digest-bound SLSA v1 provenance result. The verified certificate binds
`martonpornoi/maru/.github/workflows/release.yml`, `refs/heads/main`, the exact
source digest, and a GitHub-hosted runner; self-hosted runners are denied by the
verification command.

## Decisions and trust boundaries

- Expected source and image identities are explicit inputs. The downloaded
  manifest confirms them but cannot define them for the evaluator.
- The host-pinned actual release PR must be merged to `main`; its merge commit
  must equal the expected source, its URL must bind the expected repository and
  number, and its UTC merge instant must equal the manifest instant and establish
  the tag's CalVer year and month.
- The Release API must report exact immutable, non-draft, prerelease state and
  the exact eight-asset contract. GitHub's Release attestation and every
  individual asset attestation must also pass.
- `SHA256SUMS` is itself matched to GitHub's immutable digest and individually
  attested before its exact seven-payload inventory is trusted. Its accepted
  grammar permits only lowercase hashes and one safe basename below the
  literal `release-assets/` producer prefix.
- A second Release API read after asset verification must reproduce the first
  digest inventory. Local hashes must equal that inventory as well as the
  checksum file, and both the local inventory and mutable image identity are
  checked again immediately before success.
- Anonymous inspection covers the public Release page, public Git tag, and
  public GHCR image. Release/API, asset-attestation, and provenance verification
  use a preauthenticated GitHub CLI session. The helper never calls token
  display, token extraction, login, or token persistence commands and never
  logs or persists command output or the environment.
- OCI tag resolution and digest-bound inspection are separate. The SPDX and
  provenance checks use only `image-name@sha256:digest`, never the mutable tag.
- Provenance uses the exact repository, signer workflow, main ref, source
  digest, SLSA v1 predicate, and `--deny-self-hosted-runners`; returned
  certificate and subject fields are checked again before success is reported.
- Failure retains only the selected local evidence directory. Recovery is to
  inspect without executing its contents, correct the local prerequisite, and
  rerun into another nonexistent directory. The immutable Release, tag, assets,
  image, and attestations are never repaired in place.

## Historical evidence clarification

The append-only
[first candidate evaluation checkpoint](2026-08-29-first-release-candidate-synthetic-operator-evaluation.md)
transcribed the `SHA256SUMS` asset digest with 62 hexadecimal characters as
`c21b098b75ec173294192c206c976acdbfcb245b20c333e0b4e76b6687126b`.
That prose does not match the immutable asset record. The verified 64-character
digest, including the omitted `cb`, is
`c21b098b75ec173294192c206c976acdbfcbcb245b20c333e0b4e76b6687126b`.
The historical checkpoint remains unchanged; this checkpoint supersedes only
that transcription.

## Changed areas

- `scripts/verify_release_consumer.py` owns the standalone consumer verifier.
- `scripts/verify_release_evidence.py` now compares JSON scalar types exactly,
  so numeric `0` or `1` cannot impersonate release-state booleans.
- `docs/operations/release-process.md` owns the supported invocation,
  prerequisites, trust explanation, and failure recovery.
- Focused unit and documentation-policy coverage protects the executable and
  maintained command contract.

No Django module, model, migration, API, browser route, permission, runtime
role, release workflow, publication identity, or new ADR is introduced.

## Verification

- The executable consumer path passed against the immutable candidate with
  8 assets, 7 checksum payloads, 179 SPDX packages, 2 generator declarations,
  and 1 exact provenance result.
- Its first live attempt reached the digest-bound SBOM and failed safely because
  Windows selected CP1252 for UTF-8 Docker JSON. The explicit UTF-8 runner fix
  then passed in a fresh directory; the partial first directory remained local,
  demonstrating the documented no-reuse recovery.
- All 99 focused release-consumer and producer release-evidence cases pass.
  Whole-tree Ruff, full PyDocLint, the semantic docstring validator across 387
  source files, strict mypy for the new verifier, documentation policy across
  358 Markdown files and 207 requirement identifiers, and a fresh warning-fatal
  Sphinx/AutoAPI build also pass. Exact-commit certification and protected
  hosted acceptance remain pull-request evidence rather than claims embedded
  in the executable output.

## Data, migration, and deployment notes

The verifier reads public or authenticated supply-chain metadata and writes
only downloaded public release assets to the evaluator's new local directory.
It does not explicitly read, display, copy, or persist the existing GitHub CLI
credential, and it does not use personal data, databases, running containers,
a Django runtime, or deployment authority. It does not rebuild, run, retag,
reissue, or promote the candidate.

## Known risks and incomplete work

- The candidate remains pre-production. This verification is not a gold
  release, supported hosting, deployment, recovery, accessibility, privacy,
  owner acceptance, or production-readiness result.
- The verifier intentionally fails if a future accepted release changes the
  manifest or exact asset contract. Such a publication change requires a
  reviewed verifier/runbook update rather than permissive schema guessing.
- An evaluator remains responsible for obtaining expected source and image
  identities through an independent trusted channel and for protecting their
  local authenticated session.
- Candidate findings #41 and #42 still leave profile-aware Participation
  evidence and the end-to-end Workforce-only tutorial incomplete.

## Recommended next actions

1. Merge issue #40 only after exact local certification and protected hosted
   acceptance pass for the focused pull-request head.
2. Resolve [issue #41](https://github.com/martonpornoi/maru/issues/41) as the
   next candidate-evaluation finding, then issue #42 in its own protected pull
   request.
3. Keep gold publication, production deployment, recovery, accessibility, and
   human go/no-go decisions separate from this bounded integrity proof.
