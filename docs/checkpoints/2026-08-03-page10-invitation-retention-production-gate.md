# Page 10 invitation retention production gate

Date: 2026-08-03

## Outcome

The additive Page 10 invitation-retention boundary is implemented and verified
from an empty PostgreSQL schema. Maru still supplies no jurisdictional default:
deployment must provide one complete, approved, closed JSON policy and the
separately credentialed migration owner must activate its exact digest before
cleanup can run.

Identity migration `0017_invitation_retention_workflow` and audit migration
`0008_identity_retention_audit_uniqueness` add:

- immutable, exact invitation provisioning origin on the reserved account;
- a monotonic, owner-activated policy control containing the approval,
  jurisdiction, trigger, duration, action, and policy digest;
- audited invitation-scoped retention holds with one active-to-released
  transition and no delete/truncate path;
- append-only, audit-bound disposition receipts and `retention-v1` scheduler
  heartbeats;
- an indexed `status`, `last_transition_at`, `id` due-candidate path;
- receipt-bound tombstoning of terminal invitation contact, challenge digest,
  fingerprint, and digest-key lineage while preserving minimized transition,
  command, security-history, and audit evidence; and
- a catalog-driven `SECURITY DEFINER` relationship fence that fails closed if
  a current or future foreign key points at the reserved account outside the
  exact reviewed invitation/challenge/security relationship set.

Disposition is deliberately narrow. It applies only to due `revoked` or
`expired` invitations with the exact provisioning origin, an inactive person
account, no usable password, no verification or privilege state, no second
invitation, no active hold, closed challenge/delivery state, and no other
business, privacy, security, or future catalog relationship. It anonymizes the
abandoned contact graph; it does not delete the account or shorten accepted
identity, audit, registration, legal, payment, or backup retention.

## Production gate and runtime boundary

Readiness generation `page10-invitations-additive-v7` fingerprints the exact
40-function, 58-trigger, and 13-index PostgreSQL contract. Production readiness
also requires the activated control to match the configured policy digest, a
successful matching retention heartbeat no more than 26 hours old, no unheld
due item older than 24 hours, and no surviving C4 delivery envelope on a
terminal invitation.

The runtime PostgreSQL role has only:

- `SELECT` on the owner-activated retention-policy control;
- `SELECT`/`INSERT` on retention receipts;
- `SELECT`/`INSERT`/`UPDATE` on retention holds; and
- no `DELETE` or `REFERENCES` privilege on any restricted Page 10 relation.

Cleanup is bounded to at most 100 candidates per command invocation and reports
remaining work in the heartbeat. The operator must repeat supervised runs when
that count is non-zero. The implementation makes only a best-effort removal of
ordinary Python references after cryptographic material is replaced; it makes
no unsupported process-memory secure-erasure claim.

Migration reversal is intentionally fenced once any invitation, hold, or
retention receipt exists because reversal removes provisioning origin and the
retention controls. A populated deployment requires reviewed forward recovery.

## Verification

- Fresh empty PostgreSQL database: retention and complete readiness contract,
  `152 passed`.
- Invitation commands, scheduler evidence, and raw/concurrent database
  hardening: `51 passed`.
- Genuine runtime-role privilege probes and negative ACL paths: `110 passed`.
- Database-role profile and audit-metadata unit tests: `13 passed`.
- Targeted Ruff lint and formatting: passed for all retention production,
  migration, readiness, authorization, and test files.
- Targeted mypy: no issues in eight production source files.
- `manage.py makemigrations --check --dry-run`: no changes detected.
- `manage.py check`: only expected local warning `identity.W001`; invitation
  delivery remains fail-closed until deployment public-key configuration is
  supplied.

The regression matrix includes strict no-default policy loading, monotonic
activation, holds and audited releases, bounded backlog behavior, concurrent
cleanup, multiple-invitation and current/future relationship blockers, raw
future timestamps, forged challenge/digest-key rewrites, raw update/delete/
truncate attempts with the test escape disabled, normal Django test reset,
fresh migration application, and populated/empty downgrade behavior.

## Remaining deployment actions

1. Obtain the controller/legal-approved policy values, set
   `MARU_IDENTITY_INVITATION_RETENTION_POLICY_JSON`, and retain the approval
   reference outside source control.
2. Apply migrations as the migration owner, run
   `activate_platform_invitation_retention_policy`, and prove the stored digest
   matches deployment configuration.
3. Configure invitation delivery keys, run expiry/delivery/retention workers,
   and schedule retention at least daily with alerts before the 26-hour
   heartbeat and 24-hour backlog ceilings.
4. Reconcile and rehearse the dedicated PostgreSQL runtime-role grants with the
   provided provisioning artifact; do not run cleanup under the migration
   owner.
5. Exercise backup expiry, restore, and forward-recovery procedures. Database
   tombstoning does not itself erase already-created backups.
