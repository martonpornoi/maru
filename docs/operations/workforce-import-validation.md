# Check a Workforce proposal file

**Audience:** A person preparing fictional or properly held Workforce input\
**Outcome:** Find format and internal-consistency errors before any future import\
**Status:** Offline validation under HR-017 and ADR 0129; no live importer

The command checks a local file. A valid result means its structure and proposed
relationships are consistent. It does not identify accounts, check current
permissions or eligibility, approve Assignments, reserve coverage, or change Maru.
No account, running server or database is needed. The application environment
must already be installed; running the command itself makes no network request.

## Try the fictional example

From the repository root, using its installed Python environment:

```powershell
.venv/Scripts/python.exe -B -m maru.workforce.import_validation docs/examples/workforce-import-v1.json
```

On another platform use `.venv/bin/python` instead. Python 3.12 or later is
required. Time-zone checks use the system IANA database or the installed `tzdata`
package (included by Django on Windows). If a named zone is unavailable, validation
refuses it; no database is downloaded during validation.

The result has `status: "valid"`, one record in each section, no issues and an
explanation of the limited assurance. All names and proposals in the
[valid example](../examples/workforce-import-v1.json) are fictional.

To see a correctable failure:

```powershell
.venv/Scripts/python.exe -B -m maru.workforce.import_validation docs/examples/workforce-import-v1-invalid.json
```

This [invalid example](../examples/workforce-import-v1-invalid.json) refers to a
Department that is absent. Its issue is `unknown_reference` at
`/positions/0/department_key`. Change that reference to the key of a Department
you add to the file, then run validation again. Editing a source file is the
entire correction workflow: there is no staging token or partially applied data.
Use a copy when correcting a file you need to preserve.

## Version-one contract

Use one uncompressed UTF-8 JSON object without a byte-order mark. Every field
below is required. Objects reject unknown fields. Arrays can be empty; an empty
valid proposal establishes no staffing or adoption readiness.

The root contains `format: "maru.workforce-import"`, integer `version: 1`,
`profile: "workforce_only@1"`, `scope` and all six arrays. The profile is a file
declaration, not evidence that a live edition adopted it. Scope contains
`organization_key`, `edition_key` and an available IANA `time_zone`, such as
`Europe/Budapest` or `UTC`. Scope keys and record keys are local to this file;
they never resolve database records or confer cross-organizer authority.

| Section | Required row fields | Maximum rows |
| --- | --- | --- |
| `departments` | `key`, `name`, `parent_key` | 128 |
| `positions` | `key`, `department_key`, `title` | 512 |
| `people` | `key`, `label` | 2,048 |
| `assignments` | `key`, `person_key`, `position_key` | 4,096 |
| `shifts` | `key`, `position_key`, `starts_at`, `ends_at`, `capacity` | 1,024 |
| `commitments` | `key`, `assignment_key`, `shift_key` | 4,096 |

Keys begin with a lowercase ASCII letter, followed by at most 63 lowercase
letters, digits, underscores or hyphens. Keys must be unique within each typed
array; equal keys in different arrays do not collide. Equal display labels do
not identify people. Labels (`name`, `title`, `label`) are nonempty, trimmed NFC
Unicode text of at most 200 characters, excluding C0/C1 controls and surrogate
code points. No contact data, account IDs, private reasons, Availability,
approval status or live-record version belongs in this format.

Only a root Department's `parent_key` can be null. Every other reference must
name the proper type of record in this same file. Department ancestry must be
acyclic and at most 16 records deep. A person/Position Assignment pair and an
Assignment/Shift commitment pair may each occur once.

Shift instants use full ISO seconds, for example `2027-07-10T09:00:00+02:00`,
with `Z` or an explicit minute offset. Fractions, offset-free values and invalid
dates are refused. Each offset must agree with the declared IANA zone at that
instant. End must follow start in UTC, including across daylight-saving changes.
Past dates are permitted: the command makes no current-time or freshness claim.
Capacity is an integer from 1 to 1,024. Every commitment's Assignment and Shift
must name the same Position; counts must fit the declared Shift capacity. These
checks do not evaluate real eligibility, rest, Availability or live coverage.

Both byte and row limits apply. The file may contain at most 1,048,576 bytes and
16 nested JSON containers. Duplicate JSON members, floating-point tokens
(including `1.0`), non-finite numbers and integer tokens exceeding 19 digits
(excluding their sign) are refused independently of Python's decoder settings.
Unknown formats, versions, profiles and fields fail closed.

## Read the report

| Exit code | Meaning |
| --- | --- |
| 0 | Valid proposal, or schema/help output |
| 1 | Invalid file content; correct the source and validate again |
| 2 | Invalid arguments or unavailable/nonregular file |

The JSON report contains `status`, `counts` (only for valid input), `issues`,
`issues_truncated` and `assurance`. Each issue has a fixed `code`, known-field
`location` and fixed `message`. Rows are zero-based: row `0` is the first row.
At most 64 issues are returned. `issues_truncated: true` means further issues
were omitted. Correct structural errors first, because relationship checks run
only after all fields have valid shapes. A later run may reveal more errors.

Common codes are `missing_field`, `unknown_field`, `invalid_field`,
`duplicate_key`, `unknown_reference`, `department_cycle`, `department_depth`,
`duplicate_assignment`, `duplicate_commitment`, `position_mismatch`,
`capacity_exceeded`, `invalid_interval`, `time_zone_mismatch` and
`invalid_time_zone`. Decoder failures report a fixed root issue instead of
echoing parser text. `input_too_large`, `too_many_records` and `too_deep` explain
resource limits. `unavailable_file` deliberately omits the path and OS error.

Reports never include supplied labels, arbitrary keys, rejected values, input
snippets or source paths. Input still contains personal data when real people
are described: its holder remains responsible for custody, sharing, retention
and disposal. The command stores no input or audit event. Python's `-B` option
also prevents interpreter bytecode-cache writes. Ordinary shell redirection is
the holder's explicit choice to save output.

## Obtain the structural schema

```powershell
.venv/Scripts/python.exe -B -m maru.workforce.import_validation --schema
```

This emits the code-owned JSON Schema 2020-12 (`urn:maru:workforce-import:1`).
It describes closed objects, field shapes and row ceilings. NFC normalization,
integer token spelling, byte/depth limits, references, duplicates between rows,
ancestry and zone/consistency rules additionally require this normative validator.
A general schema pass alone is insufficient. Supplied schemas, URLs, HTML and
expressions are never fetched or executed.

Read-only regular-file opening checks the actual descriptor and reads at most
the byte limit plus one. Nonblocking opening is used where the OS supports it;
Windows network/device namespaces are refused before opening. Mounted storage
may be remote: no general local-storage or interruption-recovery claim is made.

## Remaining adoption boundaries

This is separate from the [rota ZIP and integrity check](workforce-rota-package.md).
A rota copy is not accepted as an import proposal. Applying data later needs its
own trusted scope, identity mapping, current permission checks, preview and
confirmation, independent decisions, replay rules, transaction, audit and recovery
contract. No live importer, partner integration, complete history/exit,
backup/restore or production cutover is delivered here. Removing this offline
command requires no database rollback. The ongoing/future UI demos are unchanged;
the two fictional files above exercise this new command without touching them.
