# Page 10 invitation-retention v10 corrective candidate

Date: 2026-08-03

Status: **author-verified corrective candidate; independent acceptance,
policy activation, and production cutover remain blocked**

This append-only checkpoint follows the independent rejection of the v9
candidate. It does not erase that rejection or claim production approval.

## Reproduced defect

A legitimate populated v7 database could contain a disposal receipt created
under approved policy v1 and then advance its owner-controlled policy to v2.
Migration `identity.0018_invitation_retention_v8` incorrectly built the
disposed assessment with the mutable current-control digest while its database
guard also required the immutable receipt digest. The valid v1-receipt/v2-
control state therefore could not upgrade.

## Correction

- Populated receipt backfill now copies `receipt.policy_digest` into the
  disposed assessment and no longer joins the mutable policy control.
- The PostgreSQL assessment guard accepts a disposed assessment only when its
  digest and terminal version match the exact immutable receipt.
- A new non-disposed assessment still must match the singleton current policy
  control and remains forbidden after any disposal receipt exists.
- The exact changed function fingerprint is pinned and the readiness generation
  advances to `page10-invitations-additive-v10`. Counts remain 50 functions,
  75 triggers, and 16 indexes.
- The populated migration regression now executes the complete sequence:
  policy-v1 receipt, supported policy-v2 activation, then `0018` upgrade. It
  proves that the resulting disposed assessment retains the v1 digest while
  the live control retains the distinct v2 digest.
- A complementary raw-SQL regression proves that a new non-disposed assessment
  carrying the historical v1 digest is rejected after v2 activation, while
  the exact current v2 digest succeeds.

The v9 hardening remains intact: database-clock evidence, strict source
allowlists, bounded fair traversal, complete provider-reference tombstones,
terminal disposed evidence, downgrade fences, fixed search paths, revoked
PUBLIC execution, and the absence of synthetic scheduler heartbeats.

## Files changed

- `src/maru/identity/migrations/0018_invitation_retention_v8.py`
- `src/maru/identity/invitation_readiness.py`
- `tests/integration/test_platform_invitation_retention.py`
- `tests/integration/test_page10_invitation_readiness_contract.py`
- directly affected identity, deployment, and ADR documentation

## Verification

- Focused retention and populated migration matrix: **30 passed**.
- Exact Page 10 invitation readiness matrix: **166 passed**.
- Runtime-role unit/integration matrix: **119 passed**.
- Ruff format and lint over the changed Python boundary: **passed**.
- Strict mypy for `invitation_readiness.py`: **passed**.
- `makemigrations identity --check --dry-run`: **no changes detected**; only
  the expected fail-closed local invitation-encryption warning was emitted.
- Documentation validation: **201 Markdown files and 198 requirement
  identifiers valid**.

## Remaining gates

1. A different reviewer must reproduce the v1-to-v2 populated upgrade and
   issue an explicit acceptance or rejection verdict.
2. Retention stays disabled until independent acceptance plus a separately
   approved jurisdiction-specific policy, supervised scheduler/alerting,
   stopped-writer cutover, load evidence, and backup-expiry/PITR rehearsal.
3. Recovery after live `0018` evidence remains fix-forward or a complete
   pre-`0018` database/application restore; evidence must never be cleared to
   force a downgrade.
