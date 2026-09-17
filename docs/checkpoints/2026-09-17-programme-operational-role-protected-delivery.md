# Scoped Programme operational-role contracts: protected delivery

[PR #155](https://github.com/martonpornoi/maru/pull/155) delivered ADR 0106,
27 immutable optional role definitions, registered-but-unadopted owner catalog
entries and closed original-intent/terminal-action normalization and digests.
It adds no assignment, schema, runtime right, route or profile activation.

- Certified head: `b8cb5de1ec359dc40138ddf52439b208462e613f`.
- Base: `7441d35243321bd5adbe4b015db01a7c93c07aa9`.
- Normal match-head squash: `86c287fef80080ad69eb4f1cd3023f7b2fcdea7c`, merged
  2026-09-16 22:53:39 UTC (2026-09-17 locally).
- Equal certified/squash tree: `5783f29929b5c118124c92ebf83d9fa27e4806ca`.
- Clean local main, origin/main and the protected squash matched exactly;
  unrelated worktrees, branches and containers were preserved.

Fresh exact-commit local certification passed all eight retained gates in
**322.414 seconds (5m22s)**, including **9,298 database-free units in 55.36s**
and **103 frontend tests**. Packaging, locked dependencies/security, Ruff, strict
types, NumPy/semantic docs, fresh warning-fatal Sphinx, static Django/migration/
OpenAPI/generated contracts and frontend types/build all passed. The schema-v4
receipt is `postgresql_deferred`, with zero database instances and null combined
coverage/measured timing headroom. Receipt SHA-256:
`2d5624fc84a2b7592eac442af415fef04c4a0a7231d298090d43602fef443d6a`.
Receipt, plan, unit JUnit and both packages were archived with verified copy hashes.

Hosted run `35158678907` passed quality in **11m42s**, units in **2m04s** and PR
gate in three seconds. CodeQL run `35158676486` passed all three languages. Final
exact-head state was CLEAN, without reviews or unresolved conversations and without
pagination remainder. PostgreSQL jobs were skipped, not passed.

The initial diagnostic `python -m pydoclint` was invalid because the package lacks
`__main__`; its installed executable and the subsequent full certification passed.
The first archive-copy attempt used the wrong unit-report path and stopped; the
actual report was enumerated, copied, and all five source/destination hashes verified.
Neither diagnostic failure was used as acceptance evidence.

Issue #108 retains these contracts as a completed setup prerequisite, not completion
of independently approved authority, the guided journey or profile promotion.
Explicit actual-person approval, scope comprehension, pending/recovery and
accessibility tasks are recorded under
[#92](https://github.com/martonpornoi/maru/issues/92#issuecomment-5705542457).
No new native cases accompany these pure contracts. Native #102, logical recovery
#97, human #92 and integrated #109 remain mandatory acceptance gates.

Next is the request/decision storage and actual-person command workflow. The prior
setup schema-only permission is spent; a separate bounded Authorization-table
metadata observation was requested and remains unanswered. No such observation,
new migration or temporary database has been started. Preserve PostgreSQL-suite
deferral and fail-closed current profiles.
