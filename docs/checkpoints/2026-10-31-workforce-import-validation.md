# Offline Workforce import-proposal validation — 31 October 2026

The maintainer approved one bounded autonomous outcome: versioned Workforce
input and offline validation with fictional examples, tests, documentation and
protected delivery. Issue #227 belongs to #22, which remains open. HR-017 and
accepted ADR 0129 own the contract. This checkpoint records implementation and
focused feedback; exact-commit certification and hosted delivery remain pending.

## Delivered source contract

`maru.workforce-import` version 1 declares `workforce_only@1` and one file-local
organizer/edition/time-zone scope. Closed typed proposal arrays describe
Departments, Positions, people, Assignments, Shifts and commitments. The pure
validator checks required fields, strict token types, Unicode, duplicates,
typed references, bounded acyclic ancestry, actual offset-bearing dates, IANA
zone agreement, positive UTC intervals, Position consistency and capacity.
Input is bounded to 1 MiB, depth 16 and explicit per-array ceilings. Reports
contain at most 64 fixed issues with known-field/index pointers and an honest
truncation flag; counts appear only on success. Values and paths stay out.

The standard-library CLI opens only a regular file with read-only bounded
reading, refuses Windows network/device namespaces, emits JSON, and returns
distinct valid, invalid and unavailable exit codes. Code-owned JSON Schema and
fictional valid/invalid files support correction without a running application.
Schema validation alone does not prove reference or time-zone consistency.

## Authority and recovery

No account matching, Django initialization, database or network use, domain
write, grant, approval, profile expansion, migration, retained audit or notification
is introduced. File scope is a declaration, never live authorization. Eligibility,
Availability, independent decisions, actual coverage and production readiness
are not evaluated. Correction edits the local source and reruns validation;
there is no saved staging state, partial application or database rollback.
The current UI and ongoing/future demo fixtures are unaffected. Real manual-test
accounts, records, passwords and acceptance remain untouched.

The future applying importer, partner adapters, complete exit/history,
reconciliation, operational cutover and human acceptance remain separate. The
prior #225 milestone was independently protected-delivered through PR #226 as
`b70f63f8035b287aeff2e8fab995940441745339`; #35 remains open and its temporary
heartbeat is deleted. Its pinned source and sealed evidence are preserved.

## Focused evidence and next gate

Fictional tests cover each required row/root/scope field and reference edge,
malformed JSON/encoding, duplicate members and keys, closed fields, labels,
ancestry/cycles, DST transitions, interval extremes, declared capacity, resource
ceilings, minimized errors, exact issue truncation and source correction. The
command also passes in a fresh interpreter with application/database imports,
network/process access and file writes blocked. Its exported structural schema
and both documented example outcomes agree with their intended use. A POSIX
named-pipe test is platform-skipped on Windows and remains required on Linux.

Complete inexpensive unit/static/documentation feedback precedes one fresh clean
head's normal Auto certification. Hosted acceptance, all current CodeQL analyses,
review disposition, protected exact-head squash and clean designated-main
fast-forward synchronization must then be independently verified. No focused
result or local receipt substitutes for those gates. Close #227 only after
verified delivery; #22 and human/operational acceptance remain open.

### Final iteration feedback

The final focused suite passed 168 cases, with complete line/branch coverage of
both new modules; the POSIX named-pipe test was Windows-skipped. Complete unit
feedback passed 14,808 cases with eleven existing warnings before the final
three structural-schema newline regressions were added. Those three failed
against dollar-anchor patterns and now pass with an unambiguous cross-engine
end assertion. A separate regression reproduced the missing explicit numeric
token ceiling; the decoder now limits integer tokens to 19 digits independently
of Python configuration, including when its general integer limit is disabled.
All final new cases pass together. Complete exact-head certification must
repeat the full suite before delivery.

The initial whole-unit attempt passed 14,798 cases but encountered eight Windows
access denials in existing file-replacement, offline-copy and loopback-listener
fixtures. Fresh execution with their normal OS permissions passed; no tests or
guards were weakened. Initial and corrected feedback are retained separately.
Whole-source formatting/lint, strict types, both docstring checks, documentation
policy and a warning-fatal fresh Sphinx HTML build passed during iteration.
