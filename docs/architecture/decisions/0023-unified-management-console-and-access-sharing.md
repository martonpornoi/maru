# ADR 0023: Unified Management Console and contextual access sharing

- Status: Partially superseded by ADR 0026 for host shell and route placement
- Date: 2026-07-30
- Partially supersedes: ADR 0006 separate visible Staff Console
- Requirements: AUD-001 through AUD-003, IDN-002, IDN-004, IDN-005,
  IDN-009, UX-001 through UX-009, UX-011, UX-012, NFR-001 through NFR-003

## Context

Maru grew two visible management surfaces. The React Staff Console owns safe,
recurring workflows, while Django bootstrap administration owns foundation
setup and advanced record inspection. The technical boundary is useful, but
presenting it as “staff versus admin” suggests a hierarchy and makes operators
guess which interface is canonical.

Convention leaders also need an understandable way to grant access to named
people. A page-local ACL or Django Group would be attractive but would create a
second authorization system without organization, edition, field, expiry,
delegation, independent approval, or immutable role-version semantics.

## Decision

Present one **Management Console** as Maru's authenticated planning and
operations product.

- The React application remains the canonical shell for recurring workflows.
- Navigation uses collapsible, permission-aware sections for overview, people
  and access, registration and attendee work, convention setup, and advanced
  records.
- Django admin remains available as the advanced-record route during the
  bootstrap phase. It uses the same Management Console identity, links back to
  operations, and is not a second implementation of recurring commands.
- `/manage/` is the preferred entry point. `/staff/` remains a compatibility
  alias while existing links and deployments migrate.
- A Django staff or superuser account without an assigned convention workspace
  remains in the Management Console and sees the safe empty-workspace state
  with an Advanced records link. It is not silently redirected, and platform
  staff status does not grant convention capabilities.
- The home page contains a distinct Forms section. Implemented registration,
  volunteer-application, and onboarding-document entry points appear there;
  later form modules register additional entries instead of adding another
  home page.
- User-facing navigation and workspaces show names, labels, slugs, and human
  references. UUIDs remain transport identities and may appear only in
  advanced audit, integration, or support contexts where exact identity is
  necessary.
- Command-owned evidence such as edition readiness reviews is entered through
  a capability-checked Management Console workflow. Advanced records may
  inspect it by human labels but do not expose raw scope/reviewer IDs or a
  manual timestamp creation form.

Every active page may expose **Manage access** when the current principal holds
`authorization.manage_roles` in the selected scope. The control opens one
shared access workspace:

- “Groups” are the latest immutable Maru role-bundle versions, including
  familiar convention roles such as Front Desk, Registration, Board,
  Treasurer, and department roles. Django Group remains disabled.
- Access is assigned to an exact existing platform account by email and shown
  using display name and email.
- Page context may recommend suitable groups, but a group retains its complete
  capability meaning; the UI never creates page-specific permissions.
- Assignment and replacement require a reason, effective term, and a distinct
  independently authorized approver. Replacement revokes the old assignment
  and creates the new immutable assignment atomically.
- Removal is immediate, single-controller, reasoned, audited, and uses the
  existing authority-revocation command.
- Tenant and edition scope are taken from the trusted route and re-authorized
  by the command. Hiding navigation is never the security boundary.
- Direct access sharing grants system capabilities only. It does not fill a
  workforce position, satisfy document requirements, consume headcount, add a
  reporting relationship, or create official convention capacities; those
  consequences remain in the workforce appointment workflow.

## Consequences

Chairs and other authorized leaders work in one recognizable product and can
move between operations and advanced records without learning two competing
information architectures. Collapsible sections reduce menu overload, while
the Forms area remains visible as new form-driven modules arrive.

The sharing interaction resembles familiar collaboration products without
weakening Maru's dual-control and scoped-authority invariants. Assigning a
person to Front Desk means assigning an immutable Front Desk role in one
edition, not adding an email to a hidden allowlist.

The Django advanced route still exists and some setup records still use its
forms. Full purpose-built setup builders may replace those links incrementally.
This decision does not authorize duplicating Staff workflows in Django admin
or treating model-save permission as domain authority.

## Alternatives considered

- Copy every Staff action into Django admin: rejected because behavior,
  validation, audit, and tests would diverge.
- Replace Maru roles with Django Groups: rejected because Groups are not
  tenant-, edition-, field-, term-, or approval-aware.
- Add independent ACLs to each page: rejected because page visibility is too
  coarse for view, manage, approve, export, and sensitive-field differences.
- Remove Django admin immediately: rejected because several low-frequency
  setup and evidence views do not yet have purpose-built replacements.
- Display UUIDs as the primary sharing identity: rejected because people
  operate on recognizable names and exact emails; UUIDs remain internal
  transport identifiers.
