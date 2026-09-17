# Programme independent-approval audit compatibility repair (#108)

Owner-command integration review after PR #156 found a dormant fail-closed mismatch:
the canonical role owner records an independent approver as
`authorization.role.assign.approve`, while the newly installed decision guard
looked for `authorization.role.assign`. No command or route was activated, and
no usable Programme grant workflow had been claimed. The maintained native
positive would exercise this at #102, but had explicitly not been run.

This necessary prerequisite stays within #108's existing accountable-setup item,
ADR 0106 and AUD-001; it adds no product scope or authority exception.
Published migrations 0032–0034 remain unchanged. Migration 0035 replaces only the
decision function's audit-operation predicate, retaining all other source, scope,
output, expiry, identity, immutability and permission conditions. Under exclusive
locks, its upgrade preflight refuses retained approvals missing the canonical
approver audit. It neither fabricates history nor treats the author's audit as
independent approval. Reverse is allowed only with no retained request or decision.

The existing source-pinned additive-readiness mechanism composes this migration
with the original guard contract. Its reviewed normalized source digest is
`11820f6d59b46fe9eeb59ae22e9b14a2ae14bd8f34abd10a534874dc5d24d54e`.
Both exact table fingerprints and runtime SELECT-only/function restrictions are
unchanged. No profile, public command, route, API or workflow is enabled.

Two new database-free regressions call the real owner audit formatter to compare
its output with the native consumer and verify every other function contract is
unchanged. Focused schema feedback passed **25 cases in 0.33s**. Complete units
passed **9,323 in 66.35s**, with the three existing Django URL-field warnings.
Ruff, strict mypy (700 source files), NumPy and semantic documentation (721 files)
passed. The new retained repair/reverse native case is inventoried as historical;
all native tests remain **uncollected and unexecuted** under ADR 0100/#102.

The maintainer-approved empty-schema observation on the same pinned PostgreSQL
17.11 Alpine image completed in **191.313 seconds**. It used the existing
ten-minute deadline, bounded memory/CPU/tmpfs and loopback-only connection. Forward
migration, every native metadata flag, unchanged relation shapes and composed
readiness passed. This proves no populated upgrade/reverse, workflow, concurrency,
runtime-role or native suite acceptance. The exact labelled repair container and
its temporary database were removed; no user container or persistent volume was
touched. Local observation logs remain.

Fresh exact-commit certification and protected delivery remain pending at this
checkpoint. Then resume actual independent-approval commands and genuine-person
continuation; the guided fixture and #102/#97/#92/#109 gates are still required.
Approval of schema-only checks did not advance PostgreSQL suite execution.
