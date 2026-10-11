# Testing lanes for the developer workflow

- Date: 2026-10-10
- Requirements: NFR-001, NFR-002, NFR-003, NFR-011
- Decision: implement ADR 0090 risk selection for the reviewed standalone preview
  launcher; no reversal of historical acceptance or protected delivery policy.

The maintainer authorized this follow-up on the developer-workflow branch before
its PR. Inspection found nightly exact-revision deduplication, manual dispatch and
independent exhaustive release acceptance already present. Those workflows are
retained rather than duplicated. The concrete refinement excludes only the
standalone preview launcher from the blanket scripts/history trigger. Unknown
scripts, policy machinery, shared security and destructive changes remain full;
mixed diffs retain their strongest required scope. Every current-schema case and
the 90-percent coverage threshold remain mandatory.

Regression cases cover added/modified preview code, unknown and similar paths,
mixed security/workflow/dependency changes, schema changes, deletion and renames.
Applied after baseline certification finished successfully. All 178 focused
classifier, historical-selection/nightly and preview tests passed (17.88 seconds);
changed Python lint and formatting passed. Documentation validation passed
(723 Markdown files, four skills, 218 requirement identifiers). Isolated mypy
probes of the script encounter its existing dual package/direct CLI import;
they are not passing evidence. The repository type gate is `mypy src` and
remains required in complete certification. The baseline a4bb1e8 run passed all
ten gates and 77 database batches with measured headroom and 91.59% branch
coverage in 16,067.494 seconds. Its exact-head receipt and artifacts are preserved.
They cannot certify this policy change; new full certification and hosted review
remain pending.

No product data or permission boundary changes. No migration or data rollback is
needed; reverting classification restores the previous exhaustive preview lane.
Ongoing/future demo coverage is unaffected. Database cloning and migration-reset
optimization are not part of this patch, and no shortened runtime is claimed.
