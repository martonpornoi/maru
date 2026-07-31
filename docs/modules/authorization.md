# Authorization module

Status: Implemented authority boundary with human access sharing
Last updated: 2026-07-30

## Purpose and requirements

`maru.authorization` is the deny-by-default authority boundary for IDN-002,
IDN-004, IDN-005, IDN-009, IDN-011, QRY-003, ADR 0003, and ADR 0023. A membership or
familiar role name never grants broad access by itself.

Platform administration is a separate principal purpose under ADR 0031.
Capability grants and role assignments reject a platform administrator as
their convention-scoped recipient; the account may still be retained as the
attributed actor, approver, or revoker of an exceptional platform operation.
Active platform administrators receive explicit platform-policy decisions for
code-owned non-self capabilities without stored tenant grants. Capability
declarations marked as requiring break-glass deny that ordinary platform path;
self capabilities remain relationship-bound. Existing sensitive and privileged
operations retain their reason, approval, and audit obligations.

## Owned data and invariants

- a code-owned, versioned capability catalog;
- organization- or edition-scoped direct grants;
- immutable versions of organizer-defined role bundles;
- scoped, effective, expiring, and revocable role assignments;
- grant, approval, and revocation provenance for command-managed authority;
- bounded delegation linked to the authority that produced it; and
- stable policy decisions with fields, obligations, reason code, and policy
  version.

PostgreSQL guards edition/organization agreement, delegation ancestry,
role-bundle scope, and immutable bundle versions even when ORM validation is
bypassed. Revoking any ancestor invalidates its delegated descendants.

## Public commands and decisions

- `decide(principal, capability_code, resource, requested_fields, at)`
- `grant_capability_direct(...)`
- `revoke_capability_grant(...)`
- `create_role_bundle_version(...)`
- `assign_role(...)`
- `revoke_role_assignment(...)`
- `delegate_capability(...)`
- `require_complete_projection(required_fields, permitted_fields)`
- `freeze_bulk_targets(trusted_queryset, target_ids, authorize)`

The current catalog declares basic edition viewing, edition transition,
self-history, minimized staff participation viewing, capability delegation,
direct-grant management, immediate authority revocation, role management, and
security-audit viewing.

Delegation is dual-authority: the actor must hold an active delegable parent
grant and a separate `authorization.delegate` capability. A child cannot
broaden scope, start before, or outlive its parent. Success writes the child
grant, security audit, domain event, and outbox message atomically.

Root grants, immutable role-bundle versions, and role assignments use
independent human control. The actor and approver must be distinct, the
recipient cannot approve their own authority, both controllers must hold the
command capability in the requested organization/edition scope, and a new
grant or assignment cannot outlive either controller's active authority.
Relationship-derived capabilities cannot be converted into stored grants or
role capabilities.

Revocation deliberately uses one authorized controller rather than approval:
removing access must not wait for a second person. Grant and role-assignment
revocation preserve the original issuance reason, record revoker and
revocation reason separately, publish a minimized domain fact, and invalidate
policy immediately. Revoking a parent grant also invalidates all descendants.

Every successful dual-control command writes separate actor and approver audit
events plus one correlated domain event and security-workload outbox message
inside the canonical transaction. Denial and validation outcomes produce
classified audit evidence without creating partial authority. An outbox
failure rolls the authority change and success evidence back, then records one
safe error audit.

## Enforcement

The reusable projection guard fails closed when a serializer contract exceeds
its policy field ceiling. The bulk target freezer requires an open transaction,
a tenant/edition-filtered trusted base query, non-empty unique IDs, an exact
resolved set, row locks, and a positive policy decision for every target before
returning anything to a command.

The edition list/search/count/autocomplete API requires organization scope and
filters the tenant before evaluation. An edition-only grant can retrieve its
exact detail but cannot broaden into an organizer list or suggestions. Detail
demonstrates query-before-fetch and explicit C1 projection. Single and bulk
transition demonstrate edition-scoped privileged mutation. Unknown
capabilities, expired/revoked grants, another tenant, another edition, missing
delegation authority, and wider delegation deny with safe reason codes.

## Convention work access workspace

An authorized controller can open the edition access workspace from the
administration sidebar or any embedded Convention work area:

- `GET /api/v1/organizations/{organization_id}/editions/{edition_id}/access`
  returns the latest shareable role-bundle versions and active organization-
  or selected-edition assignments;
- `POST` to the same route exact-matches one active account email and assigns a
  named role under independent approval;
- `PATCH .../access/assignments/{assignment_id}` atomically revokes the old
  assignment and creates the replacement immutable role assignment; and
- `DELETE .../access/assignments/{assignment_id}` immediately revokes an
  assignment with a mandatory reason.

The workspace requires `authorization.manage_roles`; change and removal also
require `authorization.revoke`, which the API reports separately so the client
does not offer unsupported controls. It excludes the non-shareable
`authority-controller` role. Every query is scoped by trusted organization and
edition route values before records are returned. Sensitive workspace reads
and all underlying authority mutations are audited.

The UI calls role bundles “groups” because Front Desk, Registration, Board,
Treasurer, and similar convention teams are familiar sharing concepts. They
remain complete scoped roles, not Django Groups or page-local allowlists.
People are shown by display name and exact email; assignment UUIDs are
transport identities and are not rendered as primary labels.

Access sharing is not a workforce appointment. It does not fill a position,
check an NDA, add hierarchy/reporting relationships, create staff or volunteer
capacities, or publish an official role. Use the workforce position-assignment
workflow when those consequences are required; use access sharing for a
reasoned system-access assignment.

## Specialist records

Capability grants, role-bundle versions, and role assignments are searchable,
filterable inspection pages. Lists show the person, human-readable role or
capability, organization/edition scope, current state, compact effective term,
delegation, capability summaries, and assignment counts as appropriate.
Exact dates, actor, approver, revoker, issuance reason, and revocation reason
remain in record detail.

These records are command-owned and therefore view-only in specialist Django
records. The
generic Django `Group` model is not exposed; it would create an unsafe second
authorization vocabulary beside Maru's scoped capabilities and immutable role
versions.

## Tests

Tests cover direct grants, roles, self relationship, field intersection,
unknown capability, organization and edition scope, expiry, revocation,
ancestor revocation, narrower delegation, non-delegable capabilities, database
bypass attempts, list/detail/search/count/autocomplete/write non-disclosure,
mixed-authority and unknown bulk target sets, fail-closed projection, atomic
bulk rollback, dual-authority delegation, delegation audit/event rollback, and
privileged command integration. Authority-command tests additionally cover
independent approval, recipient self-approval denial, controller expiry
ceilings, immutable role versioning, unsafe capability rejection, duplicate
authority, cross-tenant target hiding, immediate revocation, persistent
provenance, and audit/event/outbox rollback.
Access-workspace integration tests additionally cover deny-without-disclosure,
human group labels, latest-version selection, organization/edition isolation,
exact-email matching, independent approval, unknown-account rejection,
atomic replacement, immediate removal, and cross-tenant assignment hiding.

## Limitations

Department/resource scopes, step-up execution, service/device principals,
asynchronous approval workflow, grant review reminders, purpose binding, and
policy caching are not implemented. The synchronous independent approver
argument is a command invariant, not yet an approval inbox or pending request
state. Initial production bootstrap of the first two controllers also remains
an operations procedure. The reusable enforcement contracts must be adopted
and extended with each domain slice; they are not a generic shortcut around
domain-specific relationships and state.
