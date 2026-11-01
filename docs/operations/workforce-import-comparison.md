# Compare two Workforce proposal files

**Audience:** A person reviewing corrected Workforce proposal input\
**Outcome:** Locate added, removed and changed rows without printing their values\
**Status:** Offline comparison under HR-019 and ADR 0131; no live reconciliation

Use this after [validating proposal files](workforce-import-validation.md).
The command validates both files itself, then compares their file-local rows.
It needs the installed Python environment, but no account, server or database.
It makes no network request and applies nothing to Maru.

## Try the fictional revisions

From the repository root:

```powershell
.venv/Scripts/python.exe -B -m maru.workforce.import_comparison docs/examples/workforce-import-v1.json docs/examples/workforce-import-v1-revised.json
```

Use `.venv/bin/python` on other platforms. The revised fictional file changes
the Department name, person label and Shift capacity. The report says `compared`
and identifies three changed rows with fields `name`, `label` and `capacity`.
It never prints the old or new values. Both input files remain unchanged.

Compare the original file with itself to see zero changes. A successful command
returns exit code 0 whether changes exist or not: read `changes` and `counts`.

## Interpret a complete result

Each change contains `section`, `action`, `before_row`, `after_row` and `fields`.
Rows are zero-based: 0 means the first row in that input file. Added rows have
null `before_row`; removed rows have null `after_row`. Their field lists are
empty because the whole row was added or removed. Changed rows name only the
known fields whose exact validated values differ.

Sections appear in Department, Position, people, Assignment, Shift and commitment
order. Each section visits original rows for removals/changes, followed by revised
rows for additions. Field names use the format's declared order. Counts give
added, removed and changed totals for all six sections, including zero totals.
Use the row numbers to inspect your locally held files; the tool supplies no
labels, keys or values and does not decide whether a change should be accepted.

Both files must be valid version-one proposals with exactly equal declared
organization key, edition key and time-zone spelling. These are file-local
aliases, not verified organizer or account identities. Equal labels do not
identify people. Changing a key produces removal plus addition; matching by
labels or guessed identity is deliberately absent. Updates to references are
reported independently. A report is not a script of live database operations.

Formatting, JSON member order and array row order do not count as field changes.
Other validated field values compare literally. For example `Z` and `+00:00`
count as different spellings even when they describe the same instant. There
is no date, zone or identity normalization beyond the existing validator.

`hashes.before_sha256` and `hashes.after_sha256` identify the complete original
bytes that were read, including whitespace. They are not signatures, approval,
authenticity, freshness or semantic hashes. Two differently formatted files can
have different hashes and zero changes. Reports omit values, but hashes can aid
correlation: protect the report and its input files according to their contents.

## Failures and limits

| Exit | Result | Next action |
| --- | --- | --- |
| 0 | `compared`, with a complete bounded report | Review the indicated rows locally |
| 1 | `invalid`, from either input or incompatible scope | Correct a copy and compare again |
| 2 | `unavailable`, for arguments, files or more than 128 changes | Fix the invocation or review in a separately chosen process |

Every failed result has empty `changes`, `counts` and `hashes`. There is no
partial comparison. More than 128 changes returns `too_many_changes`; splitting
input into files is not proof that a whole proposal has been compared or validated.
Each input retains the validator's 1 MiB byte limit and every closed-format,
token, row, reference, ancestry, zone and capacity rule.

Input issues include `side` (`before` or `after`), a fixed `code`, a known-field
`location` and a fixed `message`. Combined output caps issues at 64 in that order;
`issues_truncated: true` means more errors were omitted. Correct structural
errors first and rerun. `incompatible_scope` and `too_many_changes` use side
`comparison`. Argument errors and unavailable-file reports omit supplied paths,
values and operating-system/parser detail. `--help` reads no input and exits 0.

The command uses the existing bounded read-only regular-file boundary, with
nonblocking opening where supported and Windows network/device refusal. It
checks the opened descriptors; mounted storage can still be remote. No input,
staging token, report file or retained audit is saved by the command. `-B` also
prevents interpreter bytecode writes; explicit shell redirection is your choice
to save a report. Preserve source copies before editing. A later comparison is
a new result bound to its own original bytes.

## Remaining boundaries

A result establishes no current identity, authority, eligibility, Availability,
independent approval, coverage or live readiness. Rota ZIPs remain a separate
operating-copy format. Live imports, partner mapping, complete reconciliation,
history/exit, recovery, human acceptance and production adoption remain open
under #22. The command has no migration or database rollback; removal leaves
Maru data unchanged. Current UI and ongoing/future fictional demos are unaffected.
