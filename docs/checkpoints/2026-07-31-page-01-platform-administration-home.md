# Checkpoint: Page 1 platform administration home

Date: 2026-07-31
Status: Implemented and verified; product-owner inspection pending
Branch: `codex/page-01-platform-home`

## Outcome

The accepted empty `/admin/` baseline now contains the first restored page: a
read-only organization inventory for active platform administrators. The live
`maru_rebuild_empty` database truthfully shows zero organizations and names
Create organization as the next page without rendering an unfinished control.

The page shows only organization name, slug, lifecycle, convention-series
count, and edition count. It explains that the signed-in account operates Maru
but does not participate in a convention. Empty, populated, denied, and safe
database-failure behavior are implemented. No prior administration,
Convention work, specialist record, registration, or volunteer HTML page was
remounted.

## Platform-administrator boundary

ADR 0031 and IDN-011 add the explicit `person` and
`platform_administrator` account classifications. Migration identity `0010`
classifies existing superusers and constrains every superuser to the platform
classification and every platform administrator to staff/superuser privileges.
The classification is not inferred from record ordering.

An active platform administrator receives explicit platform-policy decisions
for code-owned non-self capabilities without an organization or edition grant.
It may remain the attributed actor, creator, reviewer, approver, or auditor of
platform work. Subject boundaries reject it from organization membership,
capability and role assignment, participation, registration, volunteer
application, onboarding request, and workforce position assignment. Future
capabilities can require break-glass and therefore deny the ordinary platform
path; self-only capabilities remain relationship-bound.

The preserved context API can list all edition identities for the platform
administrator with `participation_status: not_participating` and no capacities.
It creates no participation. The one-shot convention bootstrap now grants
membership, organization/edition authority, participation, capacity, and the
Chair position only to the separate human Chair. The platform administrator is
the audited bootstrap actor and remains outside the convention.

## Live migration and data evidence

Migration `identity.0010_account_kind` applied successfully to
`maru_rebuild_empty`. Direct verification returned:

```text
accounts: 1
account_kind: platform_administrator
is_platform_administrator: true
organizations: 0
series: 0
editions: 0
memberships: 0
participations: 0
registrations: 0
volunteer_applications: 0
position_assignments: 0
```

The `maru` and `marucon_rehearsal` databases were not reset or reused.

## Verification

- 454 backend tests pass against PostgreSQL 17.
- Branch-aware coverage is 90.05%, above the required 90% gate.
- The 23 focused Page 1 and platform-administrator tests pass.
- The 54 directly affected baseline, identity, authorization, context,
  bootstrap, rehearsal, registration-assistance, reporting, workforce, and
  preserved-shell tests pass together.
- Ruff format/lint and strict mypy pass for 181 source files.
- Django system check and migration-drift detection pass.
- Desktop browser inspection at 1280 pixels proves successful handle login,
  semantic headings/regions, the truthful empty state, the account-boundary
  explanation, absence of unfinished actions and old navigation, no horizontal
  overflow, and no console warnings or errors.
- The in-app browser URL policy rejected the temporary narrow-frame technique.
  No workaround was used. Responsive CSS and narrow record layout are present,
  but fresh supported 390-pixel visual evidence remains an explicit acceptance
  limitation rather than being claimed.

- Production-shaped Django deployment settings pass.
- OpenAPI 3.1 generation/validation and generated TypeScript contracts pass.
- The preserved frontend passes typecheck, 20 component tests, and its Vite
  production build; it remains unmounted.
- Documentation validation passes for 124 Markdown files and 187 unique
  requirement identifiers.

## Recovery and next action

The accepted empty baseline remains commit `db5af58` on
`codex/page-by-page-rebuild`; the complete pre-reset experience remains commit
`548f15a` on `codex/pre-reset-20260731` and in the verified temporary snapshot.

The owner must inspect and accept Page 1 before Page 2 begins. Page 2 will use
`codex/page-02-create-organization` and must define its own contract before
mounting `/admin/organizations/new/`.
