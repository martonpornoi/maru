# M2 representation lifecycle start checkpoint

Date: 2026-08-01
Branch: `codex/full-platform-consolidation`
Outcome: Contract accepted; runtime implementation and verification in progress

## Why this checkpoint exists

M1 established the organization → series → edition record spine, and ADR 0039
started moving it into one coherent `/admin/` shell. M2 now begins with the
smallest safe convention-authority handoff: an explicit Executive Board for a
Draft organization. This file is an append-only resume point, not a completion
or production-readiness record.

No real volunteer, public-roster, or production personal data was copied into
the contract, examples, or tutorial. All tutorial people and email addresses
are synthetic and use the reserved `.invalid` domain.

## Accepted contract

ADR 0040 and Page 8 establish these invariants:

- one purpose-built, fixed Executive Board representation root per
  organization, separate from Django Groups, departments, workforce,
  participation, and generic access sharing;
- platform-only reasoned provisioning for a Draft organization, with the
  platform administrator recorded as actor but never as a convention subject;
- invitation by exact normalized email to an existing active, verified person
  account, with uniform unknown/ineligible disclosure and no account creation;
- an invited membership without capability, followed by version-checked
  accept/decline performed only by the exact authenticated invitee;
- at least two distinct accepted eligible controllers and no unanswered
  invitation before activation;
- exact-name confirmation, reason, and current representation aggregate version
  for activation;
- one immutable reserved root-role version and one organization-scoped durable
  assignment per controller, with a different controller as approver;
- one atomic transaction activating memberships, appointments,
  representation, and organization Draft → Active or changing nothing;
- closed HTML input, row locking, stale/replay/duplicate protection, database
  constraints, value-minimized security audit, registered domain event, and
  transactional outbox evidence; and
- additive migration and fix-forward recovery with no inferred real-person
  backfill.

The normal broad first-authority ceremony from ADR 0024 is superseded by this
path. Its edition lifecycle controls remain, and the former bootstrap command
is recovery evidence only until a separate legacy-reconciliation procedure is
approved.

## Page 8 placement

The accepted GET route is:

```text
/admin/platform/organizations/<organization-slug>/representation/
```

Provision, invite, exact-appointment response, and activate use separate
POST-only child routes. The selected organization menu includes
**Representation & access**. Platform oversight, organization-scoped
representation management, and own-invitation access are separate policies;
route placement, Django staff status, and selected-edition context grant
nothing.

Page 8 is only the root representation slice of UX-020. Department, resource,
field, exceptional-access, and restricted-case explanations are not complete.

## Documentation updated by this checkpoint

- ADR 0040 and the ADR index;
- IDN-012 and new UX-024;
- Page 8's page contract and experience/information architecture;
- organization, authorization, core, module-index, and architecture-overview
  boundaries;
- roadmap, production-consolidation ledger, and current handoff; and
- the synthetic hands-on tutorial.

## Runtime state and unverified work

The shared working tree contains concurrent M1.1 shell and M2.1 runtime work.
This documentation task did not edit application code or tests and did not run
runtime checks. A representation migration and focused Page 8 integration test
appeared from concurrent work while this checkpoint was being written. Their
presence is not verification, and neither is claimed complete here.

Before Page 8 can be accepted, finish and verify:

1. additive representation/appointment migrations and durable database
   constraints;
2. fresh and populated upgrade, active-organization preflight, reserved-role
   conflict, old-writer, rollback/fix-forward, and restore implications;
3. platform/manager/basic-view/own-invite/ordinary/inactive/Django-staff and
   two-tenant list/detail/POST non-disclosure;
4. exact verified account eligibility and platform-subject rejection;
5. duplicate provision/invitation races, invitation stale/replay, and
   concurrent activation;
6. minimum two controllers, all-invitations-answered, eligibility recheck,
   non-self cross-approval, immutable role history, and atomic Draft-to-Active
   behavior;
7. sensitive read and privileged allow/deny audit, domain-event registry/schema,
   outbox rollback/retry, and minimized payloads;
8. complete backend/static/API-client gates affected by the shared branch;
9. menu, direct-link, empty/validation/stale/denied/failure/active states,
   keyboard/axe, desktop, and 390-pixel browser evidence; and
10. owner rehearsal of the updated synthetic tutorial.

Appointment notification discovery, expiry, withdrawal, replacement, ending,
representation suspension/reactivation, quorum recovery, fictional convention
departments, department/resource scope, and full effective access remain later
M2 items rather than hidden omissions.

## Migration and recovery boundary

Do not infer controllers from existing memberships, role assignments, Django
Groups, staff/superuser flags, account order, email, or public rosters. Existing
non-Draft organizations without an active representation require an explicit
preflight report and approved reconciliation; do not silently demote or
auto-enroll them.

Once the first representation write commits, old code is write-incompatible.
Retain compatible code and fix forward, or restore the whole database to a
consistent pre-write point. Do not reverse only representation tables after
memberships, role assignments, audit, or outbox evidence exists. A committed
domain change with pending outbox delivery is recovered through the effects
worker, not by repeating activation.

## Verification performed for this documentation slice

- Runtime tests, Django checks, migration checks, database rehearsals,
  API/client checks, and browser tests: **not run and not claimed**.
- Documentation validator: passed for 157 Markdown files and 195 unique
  requirement identifiers.
- `git diff --check`: passed.

## Resume safely

1. Read `AGENTS.md`, `docs/project/CURRENT.md`, and
   `docs/project/PRODUCTION_CONSOLIDATION.md`.
2. Read ADRs 0031, 0038 through 0040 and Page 8's contract.
3. Run `git status --short --branch` and preserve concurrent work.
4. Confirm a migration exists before exercising Page 8 against any database.
5. Complete the first unchecked M1.1 or M2.1 checklist item without treating
   one track's evidence as verification of the other.
6. Update `CURRENT.md` and add a new checkpoint when runtime verification
   genuinely completes; do not rewrite this start record into a completion
   claim.
