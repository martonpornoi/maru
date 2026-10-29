# Offline Workforce rota integrity check

- Date: 2026-10-29
- Scope: #223, child of #22; HR-016, NFR-002, NFR-011 and NFR-013; ADR 0127.
- Starting main: `968607e93b92bc5dbb9acca52fd6e7cb6854c935` (protected PR #222).

## Outcome and boundary

A holder of an existing version-one Workforce rota ZIP can check its five fixed
members, closed manifest, lengths and SHA256 hashes with one local command. The
command bounds archive, directory, manifest and decompressed bytes, and refuses
ambiguous, unsupported, damaged or mismatched inputs. It never extracts content,
opens HTML, executes schemas, initializes Django/database/network, writes domain
records or prints copied personal data. The supplied manifest is not trusted
authentication; separate schema validation and current operational checks remain.

There is no new dependency, archive format, API, page, migration, runtime grant,
profile, authority, notification or audit event. Source rollback has no database
implication. On refusal keep the source unchanged under approved custody and
obtain a fresh authorized copy; there is no repair or partial-success mode.
Maintained demos/manual-test accounts, services, data and checklist are unchanged.

## Verification checkpoint

Focused feedback first passed 60 and then 64 cases across the existing producer
and new checker tests. Final whole-suite feedback passed **14,497 unique unit
cases**, including **59 new checker cases**, in **109.65 seconds**, with eleven
existing warnings and no errors, failures or skips. New coverage includes genuine
producer bytes, independent synthetic copies, each content hash, ambiguous JSON,
duplicate/path/special/DOS-directory/encryption/ZIP64/compression/CRC failures,
pre-entry metadata bounds and an actual compressible 16 MiB overflow refused
before member reads. Every refusal preserves the source.

Whole-source Ruff, strict mypy over 893 files, NumPy and semantic docstring checks,
and documentation policy pass. Actual `python -B -m` entrypoint smoke accepts a
matching synthetic ZIP and returns `content_mismatch` for changed content, with
unchanged input hashes and no extracted files or identifying output. A fresh
subprocess audit hook refuses socket access, file writes, subprocess creation and
Django/psycopg imports while the integrity check succeeds. Supplied schema and HTML
are bytes only; the deliberately non-semantic fixture demonstrates that matching
integrity does not validate either.

All earlier failures remain recorded separately: an incorrect `python -m`
docstring-tool invocation, a long line inside a new test's embedded script, and
eight failures in a restricted Windows full-unit process (file links/replacements
and loopback connections). The six implicated existing source/test files match
the starting main bytes. The complete unchanged unit suite then passed with
normal file/socket access and a fresh owned temporary directory. No application
assertion or existing test body was changed to address those restrictions.

This is precommit feedback, not complete certification or hosted acceptance.
Later exact-head ordinary Auto and hosted outcomes belong in the PR and ignored
evidence while source is pinned. No passing subsets from failed runs certify a
later commit; source, selection, native phases, coverage, headroom and exact
cleanup still require independent reconciliation.

#22's import, manual reconciliation, complete history/exit, stopped-operation,
restart, expansion, decommissioning and representative restore remain open.
Automated acceptance does not complete human/browser/accessibility, operational,
recovery-owner or production gates.
