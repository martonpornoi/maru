# ADR 0131: Compare Workforce proposal revisions without exposing values

- Status: Accepted
- Date: 2026-10-31
- Requirements: HR-019, HR-017, NFR-002, NFR-004, NFR-005, NFR-013
- Related: ADRs 0127 and 0129; issue #229, child of continuity umbrella #22

## Context

The maintainer authorized successive bounded work that can proceed without
human participation. The offline proposal validator provides one useful input
boundary under #22. Reviewing a corrected file also needs a way to locate
changes without printing personal values. This is a file comparison, not live
reconciliation or an application preview.

## Decision

Workforce owns `import_comparison.compare_import_bytes` and the standard-library
command `python -m maru.workforce.import_comparison BEFORE AFTER`. Validate both
immutable byte inputs through the unchanged HR-017 validator before decoding or
comparing them. Each input retains its existing byte, row, token, Unicode,
reference, capacity and time-zone limits. Unsupported formats, versions or
profiles remain invalid. Require exact equality of the validated scope object,
including its zone spelling; aliases do not establish live identity or authority.

Compare each of the six typed arrays by its file-local `key`. Ignore JSON object
member order, formatting and array row order for change detection. A retained
key's other fields use exact validated values: even `Z` versus `+00:00` is a
field change. Do not canonicalize instants, infer identity from labels or guess
renames. A changed key is a removal plus addition. Equal keys in different typed
arrays remain unrelated. Changing a referenced key may also change referencing
fields; report those real changes rather than inventing a single live operation.

A successful immutable report contains section counts and at most 128 changes
across all arrays. Each change contains only a known section, `added`, `removed`
or `changed`, zero-based before/after row positions, and known changed field
names. An absent row is null. Added/removed rows have an empty field list.
Traversal follows the established section order: Departments, Positions, people,
Assignments, Shifts, commitments. Within each section, visit original rows in
their input order for removals/changes, then revised rows for additions. Changed
fields follow HR-017's declared order excluding `key`. Output is deterministic
for the same two byte inputs; reordering a file can change report row positions.

Bind success to SHA256 hashes of both complete original byte inputs. This is
byte identity only, not semantic equivalence, a signature, authenticity, current
permission, review or freshness. Cosmetic changes may produce different hashes
with zero field changes. Rows, aliases, labels, supplied values, file paths,
parser text and snippets never enter reports. Hashes can still help correlate
files: custody and sharing remain the holder's responsibility.

Invalid inputs produce at most 64 existing minimized issues in before/after
order with an explicit combined truncation marker. Scope mismatch is one fixed
comparison issue. Unavailable files/arguments and more than 128 changes return
fixed failures. Every failure has empty counts, hashes and changes; a prefix is
never presented as a complete comparison. Exit codes are 0 for complete
comparison (changed or unchanged), 1 for invalid input/scope and 2 for unavailable
files, arguments or change limit. Help exits zero.

Reuse the existing owning module's read-only, bounded, descriptor-checked regular
file reader and minimized argument parser. Read at most 1 MiB plus one byte per
file, with nonblocking opening where supported and the same Windows network and
device guards. Compare exactly those read bytes; do not reopen paths for hashes.
No general mounted-storage locality or OS interruption-recovery guarantee is made.

## Authority, recovery and consequences

The command starts no Django, database or network connection, creates no account,
grant, approval, retained audit or staging state, and changes no source file or
domain record. There is no migration, profile expansion, live API or route.
Removing the tool needs no database rollback. Correcting input means editing a
preserved copy and comparing again. Human decisions, operational reconciliation,
identity mapping, applying imports, complete history/exit and restore remain
separately governed work. Existing UI and maintained fictional demos are unchanged.

Alternatives rejected: raw textual diffs expose values and mistake formatting for
domain changes; label-based matching guesses identities; partial results conceal
missing differences; canonical time matching adds semantics the input contract
does not promise. A future live comparison requires its own trusted identity,
scope, permission, version, privacy, audit, transaction and recovery contract.

## Verification

Exercise all typed sections, deterministic ordering and row positions, literal
time changes, key renames, scope refusal, both-input errors, hostile JSON and
the exact report limits. Check original-byte hashes, regular-file failures,
minimized arguments, no side files and a fresh interpreter with application,
network, process and file-write access blocked. Complete ordinary exact-head
local certification and independent protected hosted delivery separately.
