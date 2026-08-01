# Executive Board migration and recovery

Status: Repository rehearsal passed; representative deployment rehearsal required
Last updated: 2026-08-01
Scope: organizations `0008` through `0011`; IDN-011 `0012` and authorization
`0006` cross-references

This runbook covers Maru's explicit organization-representation schema and its
database integrity guards. It is not permission to load production personal
data or a production approval. A real deployment still needs named operators,
a representative restored database, backup/PITR evidence, and the security and
governance approvals in the deployment runbook.

## Safety boundary

These migrations do not infer an Executive Board from Django staff flags,
Groups, account age, email addresses, old role names, or a public roster.
Existing Draft organizations remain Draft. A non-Draft organization without a
compliant Active/Active representation pair or a fully evidenced emergency
Suspended/Suspended pair is a blocker that requires an explicit, reviewed
reconciliation.

The platform administrator may provision and activate the first representation
as an attributed operator. The platform account must never become a
representation subject, organization member, role or capability principal,
participant, registrant, volunteer, or workforce assignee.

The old public-roster rehearsal and browser/API Quick Start paths are retired.
Do not use `bootstrap_convention` as a substitute for Page 8. The preserved
operator service is legacy recovery evidence only and requires a separately
approved reconciliation plan.

## Why a maintenance window is mandatory

Migrations `0009` through `0011` add guards that old writers do not understand.
`0009` freezes
representation and appointment identity, protects linked root assignments,
validates active-Board evidence at transaction commit, rejects platform role
principals, and fences destructive downgrade once governance artifacts exist.
`0010` rejects platform direct-grant principals and completes active Board
membership provenance. `0011` serializes Board relationship writes against
identity eligibility and enforces the correlated, global emergency-containment
transition accepted in ADR 0043.

Stop every web, worker, scheduler, management-command, and integration writer
before migration. Do not use a rolling deployment. Reopen writes only with the
compatible release after the postflight checks pass.

## Preflight

Name the deployment operator, database/recovery operator, incident decision
owner, and application verifier. Record the release commit, database identity,
backup/PITR position, maintenance window, and communication channel without
recording credentials or personal data.

From the release source, run the read-only readiness command:

```powershell
uv run python src/manage.py check_representation_readiness
```

It emits deterministic, privacy-minimized JSON. A clean result has
`"status": "ready"` and zero for every blocker count. A blocked result exits
non-zero after printing counts and at most twenty organization slugs; it never
prints people, emails, names, reasons, or UUIDs. `--no-fail` is for inspection
only and must not be used to waive a blocker.

Resolve every reported class deliberately:

- a non-Draft organization without a compliant Active or emergency-Suspended
  representation, or an Active/Suspended representation whose organization
  lifecycle does not match;
- fewer than two active controllers or a pending invitation on an active
  representation;
- a missing, duplicate, or orphaned reserved `executive-board` bundle;
- a reserved bundle whose version, name, exact capability set, creator,
  controller approver, or activation reason does not match canonical evidence;
- an active appointment whose person, exact activation timestamp, membership,
  assignment scope, effective-from timestamp, no-expiry state, grantor,
  reason, or non-self controller approval is incomplete;
- an unlinked unrevoked root assignment or an active `Executive Board
  controller` membership without its matching active appointment;
- missing or mismatched activation/assignment audits, original activation
  event, or organization-scoped outbox correlation;
- an emergency Active or Suspended Board whose current event, causation audit,
  one global identity-deactivation audit, inactive removed subject, ended
  appointment/membership, revocation audit, or closed authority state is
  incomplete;
- any capability grant or role assignment whose principal is a platform
  administrator; or
- an open provisioning appointment whose subject is not an active, verified
  person.

The category keys and counts are stable and deterministic; one organization
may appear in more than one category while `blocked_organization_count` remains
deduplicated. A valid emergency-Suspended Board is governed, not a migration
blocker: both organization and representation are Suspended, no open Board
term/membership or unrevoked root assignment remains, and all correlated
activation plus emergency evidence is present. The command performs these
checks with ORM-only reads so it can run before `0009`; the migrations repeat
their database assertions and remain authoritative.

Do not invent real people, silently rewrite authority, delete audit evidence,
or weaken the migration. Preserve the blocked database, agree a fix-forward
reconciliation, test it on a restored copy, and retain the decision record.

Also run:

```powershell
uv run python src/manage.py showmigrations organizations authorization audit effects
uv run python src/manage.py migrate --plan
uv run python src/manage.py makemigrations --check --dry-run
uv run python src/manage.py check
```

Before the window, restore a current backup into an isolated target. Run the
same readiness command there and apply the release migrations. Backup success
without a successful restore is not recovery evidence.

## Apply

1. Enter the maintenance window and prove all old writers are stopped.
2. Confirm the target database and release build without printing secrets.
3. Capture the final backup/PITR marker and migration list.
4. Apply migrations from the compatible release:

   ```powershell
   uv run python src/manage.py migrate
   ```

5. If migration fails, keep writers stopped. Do not use `--fake`, disable
   triggers, or deploy old code over a partially investigated state.

Migration `0009` runs a populated-data preflight for platform role principals
and validates every existing active representation against its exact
organization, reserved role version, controllers, memberships, cross-approved
assignments, activation audit, domain event, and outbox evidence. Any mismatch
aborts the migration transaction.

Migration `0010` preflights platform direct grants and assignments plus
provisioning eligibility and active membership provenance. Migration `0011`
locks the governance/evidence tables, validates every active or suspended
representation, and installs a downgrade fence once emergency evidence exists.
Organizations `0012` and the participation/registration/workforce IDN-011
guards are deployed in the same stopped-writer release but use the separate
[convention-subject runbook](idn011-convention-subject-migration-and-recovery.md).
Authorization `0006` may be deployed in the same broader maintenance window,
but its exact issuance ledger, provable-only historical Board/delegation
backfill, readiness report, and nonempty downgrade boundary use the separate
[authority-provenance runbook](authority-provenance-migration-and-recovery.md).
Do not infer ordinary organizer sources from this Board migration.

## Verify before reopening writes

Run:

```powershell
uv run python src/manage.py check_representation_readiness
uv run python src/manage.py showmigrations organizations
uv run python src/manage.py makemigrations --check --dry-run
uv run python src/manage.py check
```

Then use synthetic accounts in an isolated organization to verify:

1. a platform administrator provisions one Draft Executive Board root;
2. two distinct active verified person accounts are invited exactly;
3. each person signs in and accepts only their own invitation;
4. activation requires the current aggregate version, exact organization name,
   all invitations answered, two controllers, and a reason;
5. the organization and representation become Active together;
6. each controller receives the immutable organization-scoped root assignment
   approved by another controller;
7. the platform administrator has no convention relationship or authority
   principal row;
8. Page 8's sensitive appointment-directory read and a denied privileged
   action both create value-minimized audit evidence; and
9. a second demo seed is idempotent.

Also prove that the platform-only emergency command contains the selected
person across every organization, revokes current root authority and sessions,
deactivates the account, and suspends every Board that falls below two active
controllers. This path is incident containment, not routine term management.

Verify that the activation audit, `organizations.representation.changed.v1`
domain event, and outbox message share the expected correlation and contain no
email, display name, reason text, password, session fact, profile value, or
capability list.

Only after these checks pass may the compatible web and worker release reopen
writes.

## Failure and recovery

### Migration has not committed

Keep writers stopped. Preserve the bounded error, migration plan, and database
state. Correct an understood blocker through the approved reconciliation on a
restored copy first, then rerun. Escalate unexpected DDL state to the recovery
owner. Do not fake the migration.

### Migration committed, no new governance write

Prefer a forward fix. A mechanical reverse is allowed only when no
representation, appointment, Executive Board membership, reserved role or
assignment, representation audit, domain event, or outbox artifact exists. The
reverse migration checks this and refuses otherwise.

For a populated database, restore the complete pre-window backup/PITR point
only after proving no canonical post-backup write would be lost and recording
the reconciliation decision. Never reverse only the representation tables.

### Any new governance write occurred

Do not deploy old writers or bypass the downgrade fence. Governance identity,
acceptance, authority, audit, and outbox rows are one control history. Keep the
compatible release in maintenance mode and fix forward. Restore the complete
database only under the incident plan with an explicit data-loss decision.

### Activation or outbox failure

The activation transaction changes everything or nothing. A database, audit,
or required publication failure must leave the organization Draft and all
accepted appointments unchanged. A committed event awaiting delivery is
recovered through the effects worker/replay runbook; do not repeat activation
merely to force delivery.

## Repository rehearsal evidence

On 2026-08-01 the release tree demonstrated:

- the readiness command reported zero blockers before and after the populated
  local upgrade;
- the populated local database applied organizations `0009` successfully;
- a completely empty PostgreSQL database applied all 100 migrations through
  organizations `0009` and reported zero blockers;
- the isolated migration and Executive Board integrity suites passed 38 tests,
  including raw-write rejection, pre-existing platform-principal rejection,
  clean reverse, and populated downgrade fences; and
- the repository restore drill restored the populated database into
  `maru_restore_drill_m21`, reconciled 100 migrations and bounded table counts,
  and removed the drill database afterward.

Subsequent current-tree evidence is deliberately separated by scope:

- 58 combined representation/migration/readiness tests pass;
- the readiness/core focus passes 10 tests, including pre-`0009` exact
  bundle/appointment/audit/event/outbox parity and valid emergency postflight;
- the representation/platform matrix passes 126 tests, including the current
  concurrency and lock-order hardening;
- five emergency-containment tests pass;
- the populated local database applies organizations through `0012` plus the
  participation `0004`, registration `0031`, and workforce `0003` IDN-011
  guards;
- focused fresh PostgreSQL IDN-011 migration tests and a 71-test adjacent
  subject-boundary batch pass;
- the final consolidated backend invocation passes 792 tests in 329.21
  seconds with 90.01 percent coverage and no warnings;
- a separate behavior run passes the same 792 tests in 291.86 seconds;
- fresh database `maru_consolidated_demo` applies all 106 current migrations,
  contains 80 synthetic accounts, two organizations, and six editions, and
  reports readiness 16/16 with zero blockers;
- a current restore drill into `maru_restore_drill_m21` passes and cleanup
  removes the drill database;
- `pip-audit` and the production `pnpm audit` report no known vulnerabilities;
  and
- the production-shaped deploy check is clean.

The earlier 100-migration figures above remain historical `0009` evidence; the
106-migration fresh database and current restore drill exercise the current
local migration graph. Neither local database is a representative deployment
backup or point-in-time recovery certification, and they do not complete the
old-writer/fix-forward production rehearsal.

These are repository/local-environment facts, not proof that a future target's
backup, infrastructure, identities, policies, or operators are ready.

## Evidence to retain per deployment

- release commit/build and exact migration plan;
- named operators and maintenance timestamps;
- preflight JSON and approved reconciliation decisions;
- backup/PITR marker and isolated restore result;
- migration output and postflight JSON;
- synthetic Page 8 correlation identifiers and bounded invariant counts;
- worker/readiness observations; and
- any incident, fix-forward, or restore decision.

Never retain database passwords, submitted reason text, invitation emails,
session material, or production personal data in the deployment record.
