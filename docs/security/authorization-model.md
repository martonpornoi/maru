# Authorization model

Status: Implemented foundation with exact scope and lineage; broader domain
coverage remains incremental
Last updated: 2026-09-02

Maru uses deny-by-default policy decisions over capabilities, scopes,
relationships, resource state, and fields. Django's built-in model permissions
are insufficient by themselves.

## Decision shape

```text
Can principal P perform capability C
on resource R and requested fields F
within organization O and edition E
under context X?
```

The policy engine returns:

- `allow` or `deny`;
- permitted field set or redaction projection;
- obligations such as reason entry, step-up authentication, approval,
  watermark, or audit;
- stable policy reason codes safe to expose; and
- policy and input versions for diagnostic traceability.

The response does not expose protected facts through its explanation.

## Principals

- Platform account
- Organization membership
- Edition participation
- Workload identity for a Maru worker
- Approved integration installation
- Offline relay device
- Temporary external collaborator

Authentication proves a principal. It does not itself grant organizer access.
Support impersonation is prohibited; controlled support sessions act as the
support principal and retain both identities in audit.

## Capabilities

Capabilities use stable verb-and-resource names, for example:

```text
registration.view_service_summary
registration.override_eligibility
registration.view_self_profile
registration.manage_self_profile
registration.moderate_public_profile
programme.approve_public_copy
applications.manage_programme_calls
applications.view_programme_proposal_self
applications.edit_programme_proposal_self
applications.respond_programme_invitation_self
applications.manage_programme_proposal_self
applications.submit_programme_proposal_self
applications.import_programme
applications.dispose_programme_import
applications.recover_programme_department_ownership
schedule.publish
workforce.assign_shift
people.view_legal_name
safety.accessibility.dispatch_instruction
audit.view_sensitive_read
exports.generate_restricted
announcements.publish_emergency
```

Capabilities are finer than navigation items but coarser than individual API
routes. A new endpoint must declare an existing capability or introduce one
with documentation and policy tests.

## Scope

A grant has:

- principal;
- capability set or role bundle;
- organization;
- optional series, edition, department, resource set, or owned-object relation;
- effective start and expiry;
- grantor and authority source;
- constraints and required context; and
- revocation and review state.

The evaluated scope is the intersection of all applicable boundaries, never
their union. Global platform administration does not imply access to organizer
content.

## Roles

Roles are versioned bundles used for comprehensibility and provisioning:

- platform infrastructure operator;
- organization owner;
- director;
- edition lead;
- department lead;
- staff member;
- duty role;
- reviewer;
- service desk agent;
- temporary collaborator; and
- integration.

Organizers may create bundles from capabilities that platform policy marks as
storable and role-assignable. A capability being non-delegable prevents a
holder from creating a child grant from their own authority; it does not by
itself prevent independent controllers from placing that capability in a
versioned role. Relationship-derived capabilities cannot be stored in a role.
Separation-of-duty rules and maximum scope remain platform policy.

Changing a role definition does not silently rewrite a settled historical
decision. Active assignments are reconciled explicitly, and the applied role
version is retained.

## Relationship and attribute checks

Capabilities are necessary but not always sufficient. Policies can check:

- self, participant, assignee, owner, reviewer, manager, or duty relationship;
- edition and resource lifecycle;
- on-duty window and physical or network context where justified;
- completed training, qualification, age-band result, or signed policy;
- case assignment and conflict of interest;
- amount threshold and separation of requester, approver, and payer;
- acknowledgement or second-person approval; and
- emergency declaration.

Client-supplied claims never establish these relationships without server
verification.

A Programme proposal collaborator is one such purpose relationship. An active,
verified person may receive or accept an invitation without Participation,
Registration, payment, Workforce, or host status. Accepted collaborators may
edit shared applicant-writable answers; the lead alone manages selection and
roster; each contributor alone revises their proposed-public profile and
consent; and each included collaborator alone acknowledges or declines the
exact seal. Every decision reloads the exact organization, edition,
submission, current relationship, lifecycle, and aggregate version. A proposal
relationship never authorizes Programme items, review, decisions, scheduling,
staffing, publication, or another proposal.

Programme Department ownership adds two deliberately separate paths. Normal
Draft-call or clean-batch reassignment requires current exact authority at both
the source and destination Departments. Historical orphan call recovery uses
`applications.recover_programme_department_ownership` at exact Edition scope,
is nondelegable and break-glass-required, and accepts one caller-supplied target
identifier only. It grants no list, search, content, proposal, import-preview,
or general Programme read. Existing proposal self/history relationships survive
an owner Department's retirement; organizer management, discovery, and new
starts still require a current owner.

## Field-level views

Every API serializer or query projection declares its field catalog and policy.
Sensitive values are omitted, not merely visually hidden.

Example person projections:

| View | May include | Excludes by default |
| --- | --- | --- |
| Public host | approved display name, pronouns, biography, avatar | contact, legal identity, private needs |
| Programme proposal collaborator | shared applicant-writable answers and their own proposed-public profile/consent; current exact seal response for self | other private profiles, invitation addresses, review evidence, decisions, accepted Programme data |
| Volunteer lead | edition name, contact route, qualifications relevant to role, availability consequence | medical details, payment, unrelated applications |
| Front Desk | lookup identifiers, registration and entitlement state, approved fulfilment instruction | HR reviews, case detail, full audit |
| Accessibility task assignee | operational instruction and contact route if needed | diagnosis and original request narrative |
| IT diagnostic | opaque account/resource ID, technical events, correlation state | message and case content |

Write authorization is field-specific too. Possessing `person.update_profile`
does not permit changing verified identity, role, access, or participation
history.

## Query enforcement

Authorization begins at the candidate query, not after serialization:

1. establish organization and edition context from trusted routing;
2. constrain the base queryset to resources visible for the capability;
3. apply relationship and state constraints;
4. select the authorized projection;
5. suppress unauthorized counts, facets, suggestions, and existence signals;
6. authorize each bulk action against its frozen target set; and
7. record required audit without sensitive query text where unnecessary.

Fetching broadly and filtering in Python is prohibited for tenant or restricted
data.

Organization structure applies this rule in two stages. A name-free exact-edition
`workforce.view_structure` decision runs before organization, edition, or
holder names are queried; a fresh final decision runs before the completed
name-bearing response is released. `workforce.manage_structure` is independent
and does not imply read, while Department/resource-only authority is too narrow
for an edition-wide tree. Current holder labels are loaded only after bounded
workforce relationships pass time, exact-scope, pinned-lineage, and active-
person checks.

The structure projection is all-or-explicit-overflow. Code-owned row, depth,
and expanded-edge ceilings return `structure_limit_exceeded` with no partial
Department tree. Department management protects the multi-query read with one captured
aggregate version, a repeatable-read attempt, an exact comparison after the
snapshot, one complete retry, and generic failure after a second movement.
Mutations independently require exact manage authority and an expected current
aggregate version inside the command transaction.

Department retirement asks Applications for a closed tri-state dependency
projection under the shared exact-edition mutex. Call and import probes both
run; any known `blocked` wins, otherwise any `unavailable` fails closed, and
only two clear results permit retirement. Workforce receives no category,
count, name, identifier, source, identity, payload, or digest. The seam is not
a list API and cannot be used to infer which Programme object exists.

The V02 reference implementation provides a reusable field-projection guard
and transactional bulk-target freezer. A bulk command supplies an already
tenant-scoped trusted queryset; the freezer rejects missing/cross-scope IDs,
locks the complete exact set, and authorizes each target before the command may
mutate. External error shapes intentionally do not distinguish an unknown
identifier from an existing but unauthorized one.

## High-impact obligations

| Action | Minimum obligation |
| --- | --- |
| Sensitive case read | explicit case relationship; access audit |
| Break-glass read | step-up, reason, short expiry, alert, review |
| Restricted export | purpose, minimization, watermark/classification, expiry |
| Root permission or role grant | independent approver, storable capability, controller scope and expiry ceiling, reason, grant audit |
| Emergency announcement | authorized duty role, reason, validity, post-review |
| Financial override | reason, authority threshold, separation where configured |
| Archive correction | amendment record, reason, approval, affected projections |
| Account merge | strong verification, impact preview, dual-account trail |
| Programme ownership orphan recovery | exact Edition, one caller-supplied ID, nondelegable break-glass authority, reason, immutable evidence, no discovery |

## Delegation and elevation

A principal can delegate only capabilities marked delegable, within their own
grant, no longer than their own expiry, and within equal or narrower scope.

Root grants and role changes are a separate governance operation. They require
two distinct controllers with the corresponding management capability in
scope, and cannot outlive either controller. The recipient cannot approve their
own new authority. Revocation requires one explicit revocation controller so
unwanted access can be removed immediately; the revoker and reason are audited.

Elevation uses a separate short-lived session and step-up authentication. The
interface must display active elevated scope. Elevation never turns into a
permanent role automatically.

The Programme ownership recovery capability is declared but dormant: neither
current profile, ordinary platform root, route, job, nor UI can exercise it.
Activation requires a later accepted recovery ceremony; database access or
platform-administrator status is not a substitute.

## Restricted case boundary

Safety categories use separate capabilities, assignments, and storage
projections. Membership in one safety team does not imply access to other case
categories.

Break-glass is for time-critical response, not managerial convenience.
Platform database administrators are operationally capable of infrastructure
access, so encryption, access procedure, monitoring, and organizational
controls must address that residual risk honestly.

## Offline authorization

An offline client receives a signed, encrypted, expiring capability manifest
for a narrow edition function, device, data subset, and period. It cannot mint
permissions or expand its dataset.

Each offline command carries device identity, local sequence, actor, issued
policy version, idempotency key, and client time. The server re-evaluates
reconcilable policy and returns applied, duplicate, superseded, or manual-review
state.

## Machine and integration access

Workload and connector identities:

- have no interactive password;
- use rotated short-lived credentials where supported;
- receive explicit API scopes and tenant context;
- cannot inherit the installing human's changing authority;
- have an owner, purpose, data-use declaration, and review date; and
- are disabled without deleting their delivery or mutation history.

## Denial experience

A denial returns a stable reason such as:

- wrong edition;
- permission absent;
- assignment required;
- lifecycle does not allow action;
- step-up authentication required;
- approval required; or
- resource unavailable.

The client provides the next safe action, such as requesting access or switching
edition, without confirming protected resource existence.

## Policy verification

Automated tests must include:

- every capability with representative allow and deny cases;
- cross-organization and cross-edition matrix tests;
- list, detail, search, counts, exports, files, webhooks, and realtime channels;
- self versus staff versus duty relationships;
- field read and write projections;
- expired, revoked, inherited, and delegated grants;
- archive, live, and restricted-case states;
- bulk operations with mixed-authority targets;
- offline manifest expiry and replay; and
- property-based assertions that narrowing a grant cannot increase access.
- exact-ID orphan recovery with no list/read oracle, current-profile/root-role
  denial, nondelegability, break-glass obligation, and cross-tenant/edition
  indistinguishability.

Production policy decisions expose metrics by reason code, never subject data.
An authorized diagnostic tool can replay a recorded input snapshot against a
policy version without granting the operator the protected content.
