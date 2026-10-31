# ADR 0129: Validate bounded Workforce import proposals offline

- Status: Accepted
- Date: 2026-10-31
- Requirements: HR-017, NFR-002, NFR-004, NFR-005, NFR-013
- Related: ADRs 0078, 0080 and 0127; issue #227, child of #22

## Context

The maintainer approved one autonomous milestone: a versioned Workforce import
format and offline validator, using fictional examples and automated evidence.
The existing rota export and integrity checker preserve an operating snapshot.
They do not identify people for import, reconstruct complete history, or confer
authority to write records. A convention needs a way to correct proposed input
before a separately governed importer is designed.

## Decision

Workforce owns `maru.workforce-import` version 1, declared for the exact
`workforce_only@1` profile. The file contains `format`, integer `version`, literal
`profile`, a `scope`, and the six required arrays `departments`, `positions`,
`people`, `assignments`, `shifts` and `commitments`. Empty arrays are permitted.
Every object is closed and every documented field is required; explicit null is
permitted only for a root Department's parent key. Unknown versions or fields
are refused. A file contains proposals, with no approval or live-status fields.

Scope contains file-local `organization_key`, `edition_key` and `time_zone`.
Keys use one lowercase ASCII letter followed by at most 63 lowercase letters,
digits, underscores or hyphens. Record keys are unique within each typed array.
Keys never resolve accounts or database records, and equal display labels never
identify a person. Labels are trimmed, nonempty NFC Unicode strings of at most
200 characters, excluding control characters and surrogate code points.

Departments contain `key`, `name`, nullable `parent_key`. Positions contain
`key`, `department_key`, `title`. People contain `key`, `label`; contact data,
account identifiers, private reasons and Availability are excluded. Assignments
contain `key`, `person_key`, `position_key`. Shifts contain `key`, `position_key`,
`starts_at`, `ends_at`, `capacity`. Commitments contain `key`, `assignment_key`,
`shift_key`. All relationships are proposals local to this one file.

Validate typed references, unique person/Position proposal pairs and unique
Assignment/Shift proposal pairs. Department ancestry must be acyclic and at
most 16 records deep. Shift instants use full ISO seconds with `Z` or an explicit
minute offset, have positive duration, and each offset must agree with the
declared IANA zone at that instant. Capacity is an integer from 1 to 1,024.
A commitment's Assignment and Shift must name the same Position, and proposed
commitment counts cannot exceed that Shift's declared capacity. These checks do
not evaluate actual eligibility, rest, Availability, independence or live state.

The input is uncompressed UTF-8 JSON of at most 1 MiB, with maximum JSON nesting
16. Duplicate members, non-finite values and floating number tokens are refused;
integer tokens are limited to 19 digits excluding their sign, independently of
Python's configurable decoder limit. Token spelling is normative in addition
to the structural JSON Schema.
Array ceilings are 128 Departments, 512 Positions, 2,048 people, 4,096
Assignments, 1,024 Shifts and 4,096 commitments. Both byte and row ceilings apply.
Return at most 64 issues in deterministic order with an explicit truncation flag.

`python -m maru.workforce.import_validation FILE` reads one regular local file
and emits a minimized JSON report to standard output. Error locations use only
known section/field names and zero-based row numbers, with fixed codes and
explanations. Rejected keys, values, labels, source paths, parser exceptions and
input snippets never enter reports. Counts are emitted only for a valid file.
`--schema` emits the code-owned JSON Schema without reading an input file or
fetching any referenced resource. Exit codes are 0 for valid/schema output,
1 for invalid content and 2 for argument or file-access failures.

Use nonblocking read-only opening where supported, then verify the descriptor
is a regular file and read at most the byte limit plus one. Reject Windows
network/device namespaces before opening. No claim is made that an arbitrary
mounted filesystem has local storage or that every OS interruption is recoverable.

## Authority, privacy and recovery

The command uses the standard library, initializes no Django or database
connection, makes no network request, and writes only its report to stdout.
It performs no domain mutation, account creation, capability grant, profile
expansion, retained audit event, notification or migration. Holding a file and
receiving a valid report establish no current application permission.

The report always explains the limited assurance. A later importer must define
trusted scope, identity mapping, preview/confirmation, current authorization,
freshness, independent decisions, replay, transactions, audit and recovery before
applying anything. Existing owner commands and profile meanings remain intact.
No supplied schema, script, expression, URL or HTML is executed. Input remains
personal data under its holder's custody even when reports omit its values.

Correction means editing the source file and validating it again. There is no
saved staging state, token, partial application or external effect to undo.
Removing the command requires no database rollback. Existing rota packages are
not accepted as import proposals. Partner-specific integration, complete
reconciliation/history, restore, human and operational acceptance remain open
under #22; representative accessibility and #42's password boundary stay separate.

## Evidence

Use fictional files and database-free tests for closed fields, Unicode, duplicate
members/keys, every reference edge, ancestry/cycles, DST/offsets, interval order,
capacity and proposal consistency, all resource ceilings, malformed input,
stable minimized output, regular-file refusal and correction. Exercise a fresh
interpreter with application/network/write access blocked. Verify exported schema
and examples, complete normal certification and independent protected delivery.
The management UI and its ongoing/future demo journeys are unchanged.
