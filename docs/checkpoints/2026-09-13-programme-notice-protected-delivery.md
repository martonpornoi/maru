# Governed Programme notices: protected delivery

Date: 2026-09-13. This closes #104's bounded dormant communication outcome under
#48, not Programme activation, database acceptance or the integrated journey.

## Exact candidate and protected result

- PR: [#110](https://github.com/martonpornoi/maru/pull/110).
- Certified head: `a83fc731721e5fb0483ae4de30b2bec320bc45bc`.
- Exact base: `1f4ea840d25ed2571dbc78052398f1cd9c612f70`.
- Protected squash: `05a53ffbab6d9c233dfdf293172457ee2edfe536`.
- Merged at 19:01:28 UTC; #104 closed at 19:01:30 UTC.
- Head and squash trees both equal
  `05edcf357525bdb84a1e150d80f1bbb9054c8826`.

Immediately before merge, the ready PR targeted main, reported CLEAN and
MERGEABLE, had no review threads, and retained the exact certified head. Every
retained check, aggregate PR gate and CodeQL passed. The merge used
`--squash --match-head-commit` without policy or administrator bypass.
The clean separate main worktree was fetched and fast-forwarded; local main and
origin/main both equalled the protected result. The former repair worktree,
unrelated stashes, containers and user work were preserved.

## Verification and evidence preservation

Exact-head `scripts/certify.ps1` completed at 18:35:16 UTC in **1,016.693 seconds
(16m57s)**. All eight retained gates passed: locked dependencies, Python static
analysis, NumPy documentation, Sphinx, Django/OpenAPI contracts, Staff Console,
dependency security and database-free units. The unit suite passed **5,550**
tests in **34.23s** with two existing URLField warnings; its JUnit report has
zero failures, errors and skips. Strict mypy checked 577 files under `src`.

The schema-4 receipt explicitly records `postgresql_deferred`, zero database
instances, and null combined coverage/timing headroom. Its SHA-256 is
`03237997949ba94a4a432a3cb101978320c403ea2db00f36e27d8b7752d34ad0`.
Receipt, plan, reports and package artifacts were copied to ignored archive
`.tools/certification-evidence/issue104-a83fc73-deferred/`; the copied receipt
hash matches. The preceding #105 archive was verified before its working
`.local-ci` directory was replaced; no previous receipt was relabelled.

[Hosted PR acceptance](https://github.com/martonpornoi/maru/actions/runs/34775135075)
ran from 18:36:12 to 19:00:42 UTC, **24m30s**. Units passed **5,550** tests in
**58.25s**, with a **1m20s** job duration. Quality passed in **24m02s**, including
warning-fatal documentation and **64** frontend tests. The hosted unit result
was verified from its completed job log; this deferred workflow uploaded no
unit artifact. [CodeQL](https://github.com/martonpornoi/maru/actions/runs/34775133763)
passed all three language analyses and its aggregate result. No hosted rerun,
timeout increase, source repair after certification or new acceptance exception
was needed.

## Accepted scope and remaining gates

ADR 0102 now supplies dormant exact operator recipient selection, immutable
notice/evidence rules and guards, current-source previews, preparation,
independent approval/rejection, deliberate manual handoff and genuine-recipient
acknowledgement. Replays repeat current source/purpose/evidence checks. Shared
organizer and personal pages use those same boundaries; personal disclosure
excludes organizer rationale and other actors. Manual packages contain only the
recipient-only link and fixed explanatory copy, with no provider delivery claim.

The [surface checkpoint](2026-09-13-programme-notice-surfaces.md) records isolated
database-free browser evidence and its limits. Task-created browser tabs were
closed and the fixture server stopped. No new PostgreSQL suite, container or
schema-only run executed in this surface/delivery continuation. The earlier
[schema observation](2026-09-13-programme-notice-schema-and-preview.md) remains
forward metadata only; maintained workflow, rollback/race, raw-constraint,
runtime, historical reverse/reapply and logical recovery cases remain debt.

#104 is closed and its #48 decomposition item is checked. #48 stays open with
all integrated acceptance unchecked. Existing #108 now explicitly owns guided
owning-task selections instead of ordinary users finding UUIDs. #92 has an
unchecked notice-specific human/screen-reader/genuine-zoom checklist, and #102
records the maintained native notice verification scenarios. #97 logical
recovery and #109 integrated proof remain mandatory. The first attempt to edit
the large umbrella body exceeded Windows' argument length; a stdin-based edit
then succeeded and its checked #104 item/open umbrella state were read back.

Proceed on `codex/programme-onsite-continuity`, based on the protected squash,
with #107's signed/versioned now/next, print/export and degraded-operation
outcome. No profile, production route, runtime writer or provider is activated.
