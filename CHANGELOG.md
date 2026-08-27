# Changelog

This file records externally meaningful Maru changes for evaluators, operators,
and contributors. Add new work under **Unreleased** in one of the established
categories. A dedicated release pull request moves those entries into a dated
`YYYY.MM.PR` section; the release workflow then places that exact curated
section at the top of the corresponding entry on GitHub Releases.

Detailed engineering evidence remains in the append-only
[checkpoint ledger](docs/checkpoints/README.md). Checkpoints are not a substitute
for these audience-focused notes, and generated pull-request lists supplement
rather than replace the curated summary.

## [Unreleased]

### Added

- Added a purpose-built Maru header and clearer repository landing experience
  with direct routes to the product tour, documentation, roadmap, Releases,
  Issues, Discussions, contribution guidance, and security reporting.
- Added the first complete Workforce-only adoption profile. A convention can
  set up and evaluate Structure, Positions, Assignments, Availability, and
  Shifts without creating Registration, payment, attendance, or unrelated
  Participation records ([PR #20](https://github.com/martonpornoi/maru/pull/20),
  ADR 0080, NFR-013).
- Added the governed Workforce journey from organization structure and Position
  management through independently approved Assignments, person-owned
  Availability, Shift claims, confirmation, locked coverage, and completion
  ([PR #16](https://github.com/martonpornoi/maru/pull/16) through
  [PR #18](https://github.com/martonpornoi/maru/pull/18)).
- Added public, warning-fatal Sphinx contributor documentation and a generated
  Python API reference published from protected `main` through GitHub Pages.

### Changed

- Release publication now requires a unique dated changelog section matching
  the derived CalVer. GitHub Release pages lead with that curated content and
  exact source/image evidence while retaining GitHub's generated pull-request
  list as supplementary detail.
- Public repository guidance now distinguishes accepted product truth from
  execution tracking: requirements and ADRs define behavior and decisions,
  while GitHub Issues hold bounded defects and proposals.

### Security

- Protected collaboration, immutable release publication, exact Action pinning,
  dependency review, CodeQL, secret scanning, provenance, SBOM, and release
  asset verification are established as repository-controlled gates.

### Known limitations

- Maru has not yet published a candidate or gold release. The current repository
  remains pre-production, is not a supported hosted service, and is not approved
  for production personal data.
- Provider certification, representative recovery, deployment, accessibility,
  policy, and owner acceptance gates remain before production use.
