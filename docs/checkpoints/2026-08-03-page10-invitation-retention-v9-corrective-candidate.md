# Page 10 invitation-retention v9 corrective candidate

Date: 2026-08-03

Status: **author-verified corrective candidate; independent acceptance and
production activation remain blocked**

This append-only checkpoint records the response to all seven release blockers
in `2026-08-03-page10-invitation-retention-v8-second-adversarial-findings.md`.
It does not erase either rejection, select a lawful retention duration, activate
a policy, or claim an independent verdict.

## Seven-blocker closure

1. PostgreSQL now guards scheduler heartbeat/cursor rows at INSERT time. Times
   must use a coherent database-clock progression, and a cursor must identify
   the exact transition timestamp and UUID of an existing terminal invitation.
2. Public policy activation and retention-run services no longer accept a time
   override. Policy, disposal, tombstone, audit, assessment, and scheduler
   evidence materialize database time; callers cannot backdate it.
3. Populated v7 upgrade rewrites the complete parent, attempt, and late-outcome
   provider graph even when a legitimate old value already matches
   `disposed-provider-<32hex>`. The migration's temporary transition allowance
   is replaced by the terminal post-upgrade guard in the same atomic migration.
4. Fair traversal inspects active holds, records an `active_hold` assessment,
   advances the cursor, and counts held work, while readiness backlog excludes
   currently held invitations. Release makes the same row disposable later.
5. A disposed assessment is terminal at both model and PostgreSQL boundaries.
6. The receipt-bound one-time parent provider tombstone transition permits
   empty and non-empty legacy states, then freezes the complete parent delivery
   row, including aggregate version and timestamps. Child provider evidence is
   terminal too.
7. Adjacent migration-owner helpers now address the split update trigger, and
   the complete adjacent, query, format, lint, and typing matrices are green.

## Operational evidence and demo boundary

Delivery, expiry, and retention heartbeats use one materialized database time.
The runtime role retains only the INSERT/SELECT scheduler access the guarded
writers require. The synthetic educational fixture deliberately creates no
`PlatformInvitationSchedulerRun`: a fabricated heartbeat would make readiness
report a scheduler that never ran. Its comprehensive admin-model test exempts
only that operational evidence model and positively asserts it remains empty.

## Migration and recovery

Identity `0018_invitation_retention_v8` remains the undeployed additive
candidate migration; its filename is unchanged because no accepted or deployed
v8 schema exists. Empty `0018 -> 0017 -> 0018` reversal and reapplication pass.
A populated-v7 edge fixture with an already-shaped provider value upgrades all
three reference locations to one new matching tombstone. Populated v8 evidence
continues to refuse downgrade, so recovery after use is fix-forward or a whole
database/application restore to one consistent pre-`0018` point.

## Readiness and least privilege

Readiness generation `page10-invitations-additive-v9` pins 50 function
fingerprints, 75 exact trigger contracts, and 16 index contracts, with no
uncataloged Page 10 function or trigger. The additional trigger is the
INSERT-time scheduler strict-time/coherence guard. The provider-parent trigger
is attached to every update so post-transition changes outside the provider
column cannot bypass full-row terminality.

## Verification performed

- Focused retention, including both migration edge rehearsals: **29 passed**.
- Exact Page 10 invitation readiness: **166 passed**.
- Runtime-role unit/integration matrix: **119 passed**.
- Adjacent invitation commands, delivery worker, database hardening,
  reconciliation, and scheduler rows: **78 passed** with no teardown warning.
- Invitation query matrix: **7 passed**.
- Comprehensive synthetic demo seed/idempotence contract: **1 passed**; zero
  synthetic scheduler rows confirmed.
- Fresh exact catalog: **50 functions, 75 triggers, 16 indexes**, all ready and
  no uncataloged Page 10 objects.
- Populated-v7 already-shaped provider upgrade: **passed**.
- Empty reverse/reapply plus post-reapply catalog inspection: **passed**.
- `makemigrations identity --check --dry-run`: **no changes detected** (the
  documented identity warning remains expected).
- Ruff format and lint over the changed boundary: **passed**.
- Strict mypy over the four changed production modules: **passed**.
- Documentation validation: **passed**.

## Remaining gates

1. A different reviewer must rerun the adversarial matrix and record a new
   explicit acceptance or rejection verdict.
2. No retention policy may be activated before that verdict and a separate
   jurisdiction-specific policy approval, stopped-writer migration rehearsal,
   supervised scheduler deployment, alerting/load evidence, and backup-expiry/
   PITR recovery rehearsal.
3. Page 10 writer reconciliation, cutover, and broader deployment acceptance
   remain separate gates. This author-side result is not production approval.
