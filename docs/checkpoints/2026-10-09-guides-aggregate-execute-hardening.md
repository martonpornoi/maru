# Checkpoint: Guides inherited trigger execution hardening

- Date: 2026-10-09
- Phase: Guides implementation; native workflow verification pending
- Requirements: EVT-008, KNO-012, KNO-013
- ADR: [0119](../architecture/decisions/0119-guidance-adoption-and-purpose-authority.md)

## Failure and diagnosis

The first native workflow attempt completed fresh migration and exact-provenance
activation, then refused public Guides setup with “Guidance setup integrity is
unavailable.” It failed after 201.281 seconds elapsed; pytest reported one error
in 199.23 seconds. Its evidence remains in the task-local ignored log
`.tools/guidance-development/native-first-20261009T131905Z-c430960d.log`.

That workflow fixture uses `proves_safe_runtime_database_role`, which replaces
only the configured-runtime-role safety probe with a passing result. Its actual
SQL, provenance and personal acceptance commands do not establish a genuine
restricted-runtime login or role boundary. That separate acceptance remains a
later browser-harness or restricted-login native-fixture gate.

The read-only catalogue diagnosis is retained at
`.tools/guidance-development/readiness-diagnosis-20261009T132649Z-58edb341.json`.
All 17 relation shapes and pinned migration sources matched. Function bodies,
behavior-bearing attributes, owners and trigger attachments also matched. Only
`maru_validate_edition_aggregate_version()` failed both execute-ACL checks:
`function_execute_owner_only` and `function_execute_boundary_closed` were false.
The saved projection establishes an excessive ACL, without recording individual
grantees. Its predecessor migration leaves PostgreSQL's default PUBLIC execution
in place; canonical runtime provisioning already revokes that permission.
Authorization and the independently inspected Knowledge catalogue passed their
own contracts. Complete Knowledge readiness was not established: its Events
prerequisite failed, and the empty observation database was not activated.

The exact owned schema container was stopped after inspection. No rows,
migrations, grants, triggers or pins were changed in that database. It remains
stopped; Announcements certification owns native capacity.

## Repair and recovery boundary

Events 0023 adds a standalone PUBLIC revoke for the inherited aggregate trigger,
outside the loop that drops new Guides functions on reversal. Events 0024 still
replaces only the body while preserving the original OID, owner, ACL and other
attributes. Unused reversal restores the predecessor body but deliberately keeps
PUBLIC execution revoked. It cannot drop that function or reopen public access.
Existing joined retained-data downgrade fences remain unchanged.

Only the owning Events 0023 normalized source pin changes, to
`434220bb59bd3fc3f4834164aea79719117cbae2228c17cff57c3f6ea3e0009d`.
No relation shape, function body, trigger, Authorization helper, Knowledge fence
or runtime allowlist changes. Additional unexpected grants continue to deny
readiness. No existing installed database or migration recorder was modified;
subsequent verification needs fresh migrations and new source-bound evidence.

## Verification and remaining work

The focused database-free suite passes 134 tests in 28.73 seconds, covering the
ACL source contract, exact readiness composition, the existing foundation/native
source contracts, explicit supporting-trigger inspection and PostgreSQL acceptance
policy. The first unit attempt caught a qualified-name expectation error in the
new test; its failed log is preserved beside the corrected passing run:
`.tools/guidance-development/aggregate-acl-units.log` and
`.tools/guidance-development/aggregate-acl-units-final.log`. Scoped Ruff and format
checks use the repository's existing migration exclusions.

The explicit historical inventory now names the two actual foundation
MigrationExecutor functions and all three Knowledge reversal/refusal functions.
Function-scoped fixtures and complete parameter groups remain indivisible. Fresh
readiness and ACL-drift tests stay current. Source-only graph inspection confirms
the exact owner sets: Announcements, Authorization, Events, Knowledge and
Organizations for the foundation file; the first four for Knowledge. Timing
provenance is unchanged; new groups receive the existing largest-group fallback.

New native regression sources cover the fresh migrated ACL/readiness, PUBLIC
grant drift refusal and unused
reverse/reapply preserving identity, ownership, ACL and the exact predecessor and
successor bodies. They are unrun while Announcements certification owns native
capacity. The original public setup workflow and joined downgrade-refusal cases
also require a fresh native run. No full certification, restricted-runtime,
browser, independent-person or production acceptance is claimed.

## Subsequent source-binding preparation

A read-only review of the prepared Guides browser harness found Announcements'
`_GUIDANCE_SUCCESSOR_SHA256` still empty. The repaired value is
`992c26023f05c8b3ae0fc3cf940dfa7debf863813dc64ebf3967203481413d25`, the exact
normalized source for its existing `0004_guidance_combined_admission` migration.
It matches the prior schema observer's source inventory; that inventory is not
proof of Announcements native function readiness. No migration, SQL, relation
fingerprint, execute permission or other checkout's empty pin changes.

A database-forbidden regression first reproduced the empty-pin refusal. The
repair passes 45 source, domain and contextual-disclosure cases; missing/changed
source and failed native/schema inspection remain unavailable. Ruff, formatting
and scoped mypy pass. The first repaired run exposed a test-only qualified versus
normalized function-name error; its log remains beside the corrected results.
Fresh native readiness, combined adoption and genuine browser evidence remain
pending. The earlier 14,090-case full feedback predates this small source repair
and does not certify the changed checkout.
