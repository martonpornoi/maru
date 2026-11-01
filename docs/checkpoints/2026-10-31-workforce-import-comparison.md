# Offline Workforce proposal comparison — 31 October 2026

The maintainer authorized successive bounded tasks, one PR at a time, with
independent work on a separate branch while earlier remote checks run. Issue
#229 is a native child of #22. HR-019 and ADR 0131 define this standalone offline
outcome; #22 remains open. This checkpoint records implementation and focused
feedback, not final exact-head certification, hosted delivery or production use.

## Behavior and ownership

`import_comparison.compare_import_bytes` validates both complete immutable byte
inputs with the unchanged HR-017 validator. Exactly equal declared scope is
required; aliases establish no live identity. Typed array keys match rows,
format/member/row order is ignored and other validated values compare literally.
Even equivalent `Z`/`+00:00` spellings count as field changes. Renames are removal
plus addition, never inferred identity matches.

Successful output contains all six section counts, original-byte SHA256 hashes
and at most 128 changes. Known sections, actions, zero-based before/after rows
and known changed field names identify differences without printing values,
labels, aliases, paths or parser text. Traversal is section order, original rows
for removal/change, then revised additions, with fields in declared format order.
Hashes include original whitespace and prove only byte identity. All failures,
including the change ceiling, return empty counts/hashes/changes. Combined input
issues cap at 64 with side and honest truncation.

The standard-library CLI reuses Workforce's existing read-only bounded regular
file reader and minimized argument parser. There is no Django/database/network,
account, grant, approval, audit, staging state, source/domain write, migration or
profile expansion. No rollback is needed. Inputs remain under their holder's
custody; correction edits a preserved copy and compares again. Existing UI and
ongoing/future demos are unchanged. Original manual-test records, credentials
and genuine human invitation acceptance remain untouched.

## Focused evidence and remaining gates

Focused comparison plus unchanged validator/CLI suites passed 209 cases, with
the existing conditional real POSIX pipe case skipped on Windows. Cases cover
all sections and actions, deterministic field/row positions, reordered files,
key renames, literal UTC changes, both-input errors, scope refusal, hostile JSON,
byte/hash binding, complete 128/129-change boundaries, regular-file/argument
failure, source preservation and a fresh interpreter denying application imports,
network/process access and file writes. Lint, strict module types and both
docstring checks pass. The first new test parameter's auto-generated megabyte
name exceeded Windows' environment ceiling during setup/teardown; stable short
IDs fixed the harness representation without changing tested bytes or assertions.
An incorrect `python -m pydoclint` invocation was corrected to the normal owning
executable; no production or test rule was weakened. Originals remain retained.

Earlier PR delivery must be checked before publication, and this branch updated
normally to actual main before final clean-head certification. Full ordinary
Auto, complete independent local readback, current selected hosted acceptance,
all CodeQL provenance, review disposition, exact-head protected squash and clean
designated-main fast-forward verification remain required. Close only #229 after
verified delivery; broader #22 adoption, live application, identity mapping,
complete reconciliation/history/exit, recovery, human and production gates stay
open. No focused result certifies a later changed commit.

## Completed inexpensive feedback — 1 November 2026

The final documented-example regression brings the focused suite to 210 passes
and the existing Windows POSIX skip, with 100 percent line/branch coverage of
the comparison module. Full units pass 14,853 cases, one expected platform skip
and eleven existing warnings. Whole-source lint/types (900 files), both
docstring checks, documentation policy and warning-fatal fresh Sphinx pass.
Six fixture setup errors in the first coverage run came from access denial in
the pre-existing global pytest temporary directory. Fresh task-owned paths let
the unchanged cases execute successfully; no input assertion or product guard
changed. Originals and both helper runs remain retained. This is development
feedback on the editable branch, not final exact-head or hosted acceptance.

## Earlier delivery incorporated — 1 November 2026

PR #230 delivered the separate HR-018/ADR 0130 contract as protected squash
`82a351478773ab60ce6f195db4e9996e8832ba9f`, with certified tree/sole-parent and
clean main equality verified. This branch normally merges that main revision;
four own-document overlaps retain both requirements, both ADRs and truthful
current status. No comparison implementation or test changes are needed.
Merged documentation policy passes 794 Markdown files, four skills and the
223 identifiers covered by its three-letter scan. A new clean commit's ordinary
Auto and hosted evidence remain required; earlier feedback is not reused as
exact-head certification. #24 is closed only for its contract, while #22 and
the genuine human/accessibility/operational gates stay open.
