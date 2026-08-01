# IDN-011 convention-subject migration and recovery

Status: Repository implementation; representative deployment rehearsal required
Last updated: 2026-08-01
Scope: organizations `0012`, participation `0004`, registration `0031`, and
workforce `0003`

This runbook installs the database form of Maru's non-participating platform
administrator invariant. It is not permission to use production personal data
or a production approval. A real deployment still needs named operators, a
representative restored database, backup/PITR evidence, and the approvals in
the deployment runbook.

## Safety boundary

A platform administrator may remain an attributed actor, creator, reviewer,
approver, or auditor. The migrations inspect only convention-subject fields:

- organization membership and every representation-appointment state;
- edition participation;
- registration, attendee profile, and attendee fursuit ownership; and
- volunteer application, onboarding request, and workforce assignment.

They do not reject provisioning, invitation, submission, review, approval, or
audit provenance. They never reclassify an account, delete a relationship, or
invent a replacement person.

## Why a maintenance window is mandatory

Each migration adds `BEFORE INSERT OR UPDATE` subject guards and a deferred
`identity_account.account_kind` reclassification trigger. Subject guards lock
the referenced identity row `FOR UPDATE`, serializing a convention-subject
write with a concurrent person-to-platform change.

Inside each transactional migration, trigger DDL runs before the existing-data
scan. PostgreSQL's table lock drains earlier writers and remains held through
the final count-only preflight and commit. This prevents a writer from entering
after a clean scan but before the guard becomes effective.

Stop web, worker, scheduler, management-command, import, and integration
writers. Do not use a rolling deployment. Reopen writes only with compatible
code after every postflight check passes.

## Preflight

Name the application operator, database/recovery operator, incident decision
owner, and verifier. Record the release commit, target database identity,
backup/PITR marker, maintenance window, and communication channel without
recording credentials or personal data.

On a representative restored database, run these count-only checks:

```sql
SELECT 'organization_memberships' AS relationship, COUNT(*) AS blockers
  FROM organizations_organizationmembership AS relationship
  JOIN identity_account AS subject ON subject.id = relationship.account_id
 WHERE subject.account_kind != 'person'
UNION ALL
SELECT 'representation_appointments', COUNT(*)
  FROM organizations_representationappointment AS relationship
  JOIN identity_account AS subject ON subject.id = relationship.account_id
 WHERE subject.account_kind != 'person'
UNION ALL
SELECT 'participations', COUNT(*)
  FROM participation_participation AS relationship
  JOIN identity_account AS subject ON subject.id = relationship.account_id
 WHERE subject.account_kind != 'person'
UNION ALL
SELECT 'registrations', COUNT(*)
  FROM registration_registration AS relationship
  JOIN identity_account AS subject ON subject.id = relationship.account_id
 WHERE subject.account_kind != 'person'
UNION ALL
SELECT 'attendee_profiles', COUNT(*)
  FROM registration_attendeeregistrationprofile AS relationship
  JOIN identity_account AS subject ON subject.id = relationship.account_id
 WHERE subject.account_kind != 'person'
UNION ALL
SELECT 'attendee_fursuits', COUNT(*)
  FROM registration_attendeefursuit AS relationship
  JOIN identity_account AS subject ON subject.id = relationship.account_id
 WHERE subject.account_kind != 'person'
UNION ALL
SELECT 'volunteer_applications', COUNT(*)
  FROM workforce_volunteerapplication AS relationship
  JOIN identity_account AS subject ON subject.id = relationship.account_id
 WHERE subject.account_kind != 'person'
UNION ALL
SELECT 'onboarding_requests', COUNT(*)
  FROM workforce_onboardingdocumentrequest AS relationship
  JOIN identity_account AS subject ON subject.id = relationship.account_id
 WHERE subject.account_kind != 'person'
UNION ALL
SELECT 'workforce_assignments', COUNT(*)
  FROM workforce_positionassignment AS relationship
  JOIN identity_account AS subject ON subject.id = relationship.account_id
 WHERE subject.account_kind != 'person';
```

Every count must be zero. The migrations repeat these checks transactionally
and abort with bounded counts if a blocker remains.

Also run:

```powershell
uv run python src/manage.py showmigrations organizations participation registration workforce
uv run python src/manage.py migrate --plan
uv run python src/manage.py makemigrations --check --dry-run
uv run python src/manage.py check
```

Do not print account identifiers, emails, names, application text, onboarding
documents, registration data, or appointment reasons during routine preflight.
If a count is non-zero, preserve the database and agree which fact is wrong:
the platform classification or the convention relationship. Reconcile through
an approved module command or reviewed repair on a restored copy. Do not
silently reclassify, delete, disable triggers, or fake the migration.

## Apply

1. Enter the maintenance window and prove all old writers are stopped.
2. Confirm the target and compatible release without printing secrets.
3. Capture the final backup/PITR marker and migration plan.
4. Apply migrations:

   ```powershell
   uv run python src/manage.py migrate
   ```

5. If any count-only preflight fails, keep writers stopped and follow the
   reconciliation procedure above.
6. Never use `--fake`, temporarily alter an account kind, or disable a trigger
   merely to make deployment continue.

## Verify before reopening writes

Run the preflight query again; every count must remain zero. Then run:

```powershell
uv run python src/manage.py showmigrations organizations participation registration workforce
uv run python src/manage.py makemigrations --check --dry-run
uv run python src/manage.py check
uv run pytest -q tests/integration/test_platform_administrator_database_boundary.py tests/integration/test_idn011_database_migrations.py
```

In an isolated synthetic tenant, verify that:

1. bulk and direct-SQL subject writes reject a platform administrator;
2. reclassifying an existing subject to platform administrator fails at
   transaction commit;
3. organization appointment rejection applies while Invited, Accepted, Active,
   Declined, or Ended;
4. a platform administrator still works in supported actor/provenance fields;
5. competing subject-write and reclassification transactions serialize and
   cannot both commit; and
6. every failed operation leaves the account and relationship unchanged.

Only after these checks pass may compatible web and worker processes reopen
writes.

## Failure and recovery

### Migration has not committed

Keep writers stopped. The migration transaction rolls back its functions,
triggers, and preflight together. Preserve the bounded error and migration plan,
reconcile the blocker on a restored copy, and retry from the compatible release.
Do not fake the migration.

### Migration committed, no later subject write

Prefer a forward fix. Mechanical reverse removes only these guards, not subject
data. Reverse solely in a controlled maintenance window after proving that no
new subject or account-kind write relied on them and that the previous release
remains compatible with every other applied migration.

### Any later subject or account-kind write occurred

Do not deploy old writers or remove the guards. Keep compatible code and fix
forward. Restore the complete database only under the incident plan with an
explicit data-loss decision and mutually consistent backup point.

### Unexpected blocking or deadlock

Keep writes closed and retain bounded PostgreSQL error, lock-wait, and
transaction evidence without query parameters or personal values. Do not weaken
the identity-row lock. Escalate to the database and incident owners, reproduce
against a restored copy, and fix forward only after the competing lock order is
understood.

## Evidence to retain

- release build and exact migration plan;
- named operators and maintenance timestamps;
- count-only preflight and postflight output;
- backup/PITR marker and isolated restore result;
- focused invariant and concurrency test result;
- reopening decision; and
- any reconciliation, incident, fix-forward, or restore decision.

Never retain database passwords, personal identifiers, registration/profile
values, application text, documents, appointment reasons, or session material
in this deployment record.
