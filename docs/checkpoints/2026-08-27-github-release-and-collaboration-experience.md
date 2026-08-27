# GitHub release and collaboration experience

- Date: 2026-08-27
- Phase: Progressive adoption and management-experience recovery
- Outcome: Added a clear public repository landing experience, curated
  changelog-driven Releases, and a small bounded GitHub Issues execution queue
- Requirements: NFR-001, NFR-002, NFR-003, and NFR-011
- Decisions: Implements existing ADRs 0060, 0065, 0068, and 0070; no new ADR

## Protected-main baseline

Work began from clean synchronized `main` at exact protected-main squash commit
`b387748f42c0ac9edd70878f32c87c2d2cde1a14`. PR #20 had merged the
Workforce-only progressive-adoption profile. Pull-request run `33014664319`
passed the complete high-risk acceptance path and stable `PR gate`; subsequent
exact-main CodeQL run `33037058305` and Pages run `33037059040` also passed.

## Public repository outcome

The owner-approved Maru header was recovered from the named stash created for a
later branch and added as `.github/assets/maru-header.png`. README now presents
the product promise, an explicit pre-production and synthetic-data warning,
implemented evaluation slices, build/documentation badges, direct GitHub and
policy navigation, progressive Workforce-only adoption, and a concise grouped
documentation map.

The image is a repository README asset. This outcome does not silently mutate
GitHub's live social-preview setting; that remains a separately authorized and
reconciled post-merge operation.

## Curated release notes

`CHANGELOG.md` now owns audience-focused change summaries under **Unreleased**.
A dedicated release pull request must create exactly one non-empty dated
section whose padded CalVer and UTC date match the release PR number and GitHub
merge timestamp. Candidate and gold attempts for that release PR share the same
curated base-version section.

The Release workflow adds a cheap source preflight before complete
certification. It rejects a non-current `main`, project-version drift, missing,
duplicated, undated, invalid-date, empty, or merge-date-mismatched changelog
sections, and existing tag or release identities. The publication job repeats
the security-critical checks, leads the Release body with the curated notes and
candidate warning, appends exact pull-request/commit/image/changelog evidence,
and retains GitHub's generated categorized list as supplementary detail.
Draft, asset, digest, immutability, attestation, and irreversible recovery
boundaries from ADRs 0060 and 0065 remain unchanged.

## Issue intake and live execution queue

Bug and proposal Issue Forms now request preparation, observed versus expected
behavior, role/scope, impact, acceptance, non-goals, traceability, safety,
environment, and sanitized evidence as appropriate. The chooser links current
project state, and contribution/repository guidance explains that requirements
and ADRs remain authoritative, the roadmap sets direction, CURRENT is the
handoff, Discussions hold exploration, and Issues are bounded execution work.

Authenticated creation and readback confirmed four live issues:

- [#21: Publish the first curated immutable Maru release candidate](https://github.com/martonpornoi/maru/issues/21)
- [#22: Deliver the Workforce-only continuity and reversible-adoption package](https://github.com/martonpornoi/maru/issues/22)
- [#23: Complete the Workforce and Shift role-state accessibility matrix](https://github.com/martonpornoi/maru/issues/23)
- [#24: Define the next scheduling contract for attendance, handover, and actual time](https://github.com/martonpornoi/maru/issues/24)

All start in `triage` with `proposal` and only relevant scoped classification
labels. They do not promise priority, response time, implementation, a gold
release, or production approval. Historical todo and checkpoint documents were
not bulk-copied, and GitHub Projects remains disabled.

## Verification

Completed on the working branch:

- 64 focused release-metadata, workflow-contract, public-repository-material,
  and documentation-policy tests pass;
- focused Ruff formatting and lint pass for the changed Python release code and
  tests;
- documentation policy validates 348 Markdown files, four repository skills,
  and 207 unique requirement identifiers;
- the broad `scripts/check.ps1 -SkipPythonTests` gate passes package build and
  verification, Python and JavaScript dependency audits, whole-tree Ruff and
  strict mypy across 373 source files, PyDocLint, semantic docstrings across
  383 source files, warning-fatal Sphinx/AutoAPI, migration and Django checks,
  production-settings validation, OpenAPI generation, TypeScript checking, 29
  frontend tests, and the production frontend build;
- `git diff --check` passes;
- the 1,280 by 640 PNG header was visually inspected at original resolution;
  and
- authenticated GitHub readback confirms issues #21 through #24 and their
  intended labels.

Clean-tree exact-commit certification remains before pull-request review.
Hosted `PR gate` acceptance will remain authoritative for the eventual exact
pull-request head.

## Data, migration, and deployment notes

This outcome changes public documentation, repository forms, release
automation, tests, and live issue metadata. It adds no Django model, migration,
API, browser route, runtime database permission, personal-data processing,
application deployment, tag, package, GHCR image, or GitHub Release. Issue
bodies use product contracts and synthetic-data boundaries only.

## Known risks and incomplete work

- The Releases tab remains empty until issue #21's dedicated release pull
  request passes and an `rc.1` dispatch receives separate approval.
- The release workflow is locally contract-tested but still requires the full
  protected hosted acceptance selected for workflow changes.
- README badges and linked current-state guidance become public only after this
  branch merges; the header is not yet the live social preview.

## Recommended next actions

1. Complete local checks and protected pull-request delivery for this branch.
2. Execute issue #21 as a separate release pull request and immutable candidate
   publication, including the administrator immutability preflight.
3. Progress issues #22 through #24 in their documented order and preserve their
   requirement, privacy, recovery, and progressive-adoption boundaries.
