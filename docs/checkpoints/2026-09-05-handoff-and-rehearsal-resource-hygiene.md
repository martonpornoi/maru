# Concise handoff and exact-run rehearsal resource hygiene

- Date: 2026-09-05
- Scope: [issue #73](https://github.com/martonpornoi/maru/issues/73)
- Requirements: NFR-001, NFR-002, NFR-003, NFR-011
- Decisions: apply existing ADRs 0074 and 0079; no architecture change
- Evidence boundary: implementation and focused pre-review verification;
  exact-commit certification and protected merge are recorded in the linked PR

## Outcome

The current handoff had accumulated 1,461 content lines and still instructed a
contributor to finish #64 after #64 and #71 had been delivered. `CURRENT.md` is
now a 133-line restart guide. The roadmap's Programme phase now agrees that
review/decisions are implemented and accepted-item conversion is the next
product boundary, not another review implementation.

Documentation standards now explain replacing superseded status, linking
existing milestone evidence, keeping current priorities separate from history,
and selecting task-relevant contracts after the required reading order.
Existing checkpoint/ADR paths, navigation hubs, migrations, dormant modules,
retired-route guards, and production gates remain intact.

The exact older handoff is retained in
[protected Git history](https://github.com/martonpornoi/maru/blob/47960893902d910d86f9b5c8fe5d9b5b2dc65fed/docs/project/CURRENT.md).
Its milestone narratives already have owning records, including
[the first published candidate](2026-08-27-first-immutable-release-candidate-published.md),
[runtime rehearsal](2026-08-29-synthetic-oci-runtime-rehearsal.md),
[static rehearsal](2026-08-30-synthetic-oci-static-delivery-rehearsal.md),
[Department continuity](2026-09-04-programme-department-ownership-continuity.md),
[migration-test isolation](2026-09-05-historical-migration-test-isolation.md), and
[review and decisions](2026-09-05-programme-staged-review-and-decisions.md).
No historical document was deleted or copied into a competing current ledger.

## Cleanup correction and safety

Both OCI rehearsal runners now remove associated anonymous volumes with each
exact label-verified container. PostgreSQL's image-declared data volume exists
even on a one-shot helper that never starts a database; plain container removal
could previously leave it behind.

Docker's container-volume removal leaves named volumes intact. Named rehearsal
volumes still use the existing separate exact-name and ownership-label checks.
Complete namespace validation, interrupted-job discovery, final inventory
checks, and stopped retention behavior are unchanged. No global prune,
unassociated-volume sweep, age-based deletion, database migration, application
authorization change, or production cleanup is introduced.

The [housekeeping guide](../development/docker-housekeeping.md) documents
read-only metadata inventory and separately approved cleanup. Persistent Maru
data, unrelated projects, and volumes whose origin is uncertain are not cleanup
targets merely because Docker reports reclaimable storage. No pre-existing
Docker resource was removed for this issue.

## Focused verification

- Regression-first execution failed at the three expected missing-volume-flag
  assertions; 111 other rehearsal cases passed before the fix.
- Both rehearsal unit suites plus documentation-policy tests pass: 133 cases.
  Tests retain foreign-label refusal, unavailable inventory, incomplete cleanup,
  retention, exact-run discovery, and preservation of unrelated named/orphaned
  volumes. No case or acceptance threshold was removed.
- A real Docker probe exercised each actual runner with newly created empty
  labeled containers, image-declared anonymous data volumes, and an unrelated
  named sentinel volume. Retention preserved both container and storage;
  cleanup removed the anonymous volume and preserved the named sentinel.
  All probe resources were then removed. Before/after inventories proved every
  pre-existing container and volume remained untouched. No database was started.
- Changed Python source/tests pass Ruff lint and formatting checks.
- Documentation policy and maintained-link validation pass across 394 Markdown
  files, four repository skills, and 215 unique requirement identifiers.

These focused results do not substitute for full exact-commit certification or
the protected hosted `PR gate`. Issue #73 and its linked PR own that delivery
evidence; this checkpoint does not predict the eventual merge revision.

## Remaining work

The migration-performance pilot and Programme umbrella #48 remain separate.
Docker housekeeping is disk/resource hygiene, not evidence of faster tests.
Existing Docker leftovers still require an exact ownership inventory and owner
approval; orphaned-volume provenance cannot be inferred from age or a hash name.
