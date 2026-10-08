# Approachable convention verification follow-up

Date: 2026-10-08
Status: Scoped test repair; fresh exact-commit certification remains required.

Clean candidate `40bac23afe20d51e833ee858137c439061215e6c` passed all non-database
quality checks, including 13,588 units, 108 frontend cases, dependency audits,
typing, documentation validation and a fresh warning-fatal Sphinx build. At
44m19s, required database shard 19 found an old `Shared form studio` expectation
in the Applications HTML lifecycle journey. Twenty-one shards passed; shard 19
failed and seven other running shards were interrupted. The final shard had not
started. There is no certification success receipt or accepted combined coverage.

All 29 started containers were removed, independently checked against Docker's
container inventory. Wrapper and Python children exited. All 4,296 artifact files
and five wrapper files were copied and SHA-256 verified at
`.tools/certification-evidence/approachable-local-40bac23-failed` in the primary
repository. A verified Git bundle retains the exact failed source above its
protected `1fc8a21` prerequisite. No failed or interrupted evidence is overwritten.

The repair updates stale display expectations in the existing Applications HTML
journey, including positive and negative lifecycle controls. Status transitions,
row counts, field restrictions, authority, retry/version behavior, and side-effect
checks remain unchanged. A complete changed-string scan found six stale
expectations, all in this journey. Exact headings, links and forms now carry the
current labels; the active-state check also proves the edit form itself is absent.

The repaired HTML workflows and application studio pass all 14 integration cases
in 211.70 seconds against a fresh disposable PostgreSQL database. Ruff formatting,
lint and whitespace checks pass. The owned repair container, network and volume
were removed, with container and volume absence independently verified.

The unpublished candidate is amended as one coherent usability batch; its prior
source remains recoverable from the verified bundle. The new head requires a
complete clean-commit run and independent hosted acceptance. Earlier passing
shards cannot certify its new head.
