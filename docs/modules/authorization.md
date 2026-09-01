# Authorization module

Status: Implemented exact organization/edition/department/resource authority,
sealed exact-version adoption-profile targets, protected Executive Board and
Maru-operator roots, provenance writing, profile-compatible access management,
and guarded exact-lineage policy/runtime activation; dormant Applications
Programme capabilities remain unadopted and production legacy reconciliation
and cutover remain gates
Last updated: 2026-09-01

## Purpose and requirements

`maru.authorization` is the deny-by-default authority boundary for IDN-002,
IDN-004, IDN-005, IDN-009, IDN-011, IDN-012, IDN-014, EVT-006, QRY-003,
UX-020, UX-024, UX-028, UX-030, NFR-013, ADR 0003, ADR 0023, ADR 0040,
ADR 0041, ADR 0044, ADR 0080, ADR 0081, ADR 0082, and ADR 0083. A membership,
account, familiar role name, or visible destination never grants broad access
by itself.

Platform administration is a separate principal purpose under ADR 0031.
Capability grants and role assignments reject a platform administrator as
their convention-scoped recipient; the account may still be retained as the
attributed actor, approver, or revoker of an exceptional platform operation.
Active platform administrators receive explicit platform-policy decisions for
code-owned non-self capabilities without stored tenant grants. Capability
declarations marked as requiring break-glass deny that ordinary platform path;
self capabilities remain relationship-bound. Existing sensitive and privileged
operations retain their reason, approval, and audit obligations.

An inactive account is denied before self-relationship, platform, direct-grant,
or role-assignment evaluation. This platform-wide login-disable invariant does
not replace the explainable organizer-scoped restrictions required by ADR 0013.

For an exact edition target, the same tenant-scoped resolver seals both the
persisted adoption-profile code and version. Policy requires that exact pair
to resolve and that its immutable manifest explicitly pin the requested
capability; module-prefix membership is not permission. An unknown pair or an
unpinned capability returns `module_not_adopted` before self-service, platform
policy, direct grants, or role assignments are considered. Platform oversight
is therefore not a hidden modularity bypass, and later same-namespace catalog
growth cannot widen an existing profile version. Organization-scoped setup
remains available under its explicit non-edition policy.

Authority writers repeat that manifest check after locking and re-resolving the
exact edition. Direct grants, role assignments, and delegated children cannot
persist a capability that the locked `(profile_code, profile_version)` does not
pin, even when the caller supplied a formerly valid sealed target. Failure is
classified as `module_not_adopted`, records only denial or error audit evidence,
and creates no authority, domain event, or outbox message.

The catalog now also declares nine exact-edition Programme capabilities for
private items, readiness, delivery facts, Department discussion, and approved
public copy. Authorization migration `0020_programme_capabilities` teaches the
PostgreSQL minimum-scope function those closed codes and refuses downgrade once
authority evidence uses them. This is schema readiness, not admission: neither
current v1 manifest pins any Programme capability, so policy and authority
writers still return `module_not_adopted` before evaluating platform or stored
authority.

Authorization migration `0021_applications_programme_capabilities` adds the
dormant Applications-owned Programme vocabulary:

- `applications.manage_programme_calls` at exact current Department scope
  within the edition, with no hierarchy inheritance; and
- relationship-derived self capabilities to view, edit, respond to an
  invitation, manage, and submit one's own Programme proposal.

This closed capability-vocabulary change advances the Authorization decision
policy version to `2026-09-01.1`. The version records the exact catalog and
minimum-scope policy used to make decisions; it does not admit the capability
into an edition profile.

Authorization migration `0022_programme_import_capabilities` adds two dormant,
delegable declarations:

- `applications.import_programme`, bounded to one exact Department, for
  staging, organizer preview, and protected apply; and
- `applications.dispose_programme_import`, bounded to one exact Edition, for
  continuity disposal without staged-content read authority.

The import declaration carries reason, audit, and sensitive-read obligations;
disposal carries reason and audit but cannot reveal or apply staged content.
The closed minimum-scope catalog and decision policy advance to
`2026-09-01.2`, and populated grants or role-bundle evidence fence downgrade.
Neither declaration is pinned by a current profile, and the migration creates
no grant, role, root, adapter admission, route, or writer.

The self capabilities are non-persistable and non-role-assignable. They resolve
from the authenticated active, verified person and the exact current lead or
accepted-collaborator relationship; a caller-supplied person identifier never
establishes self. Lead-only selection, roster, seal, reopen, submit, withdraw,
and collaborator-only profile/consent and response obligations remain command-
level relationship checks in Applications.

Neither current literal v1 manifest pins these capabilities. Their manifest
fingerprints remain unchanged, so platform policy, a direct grant, a role, a
same-prefix capability, or durable dormant data still fails with
`module_not_adopted`. The migration extends the closed minimum-scope vocabulary
and its populated downgrade fence; it does not create a grant, role, root,
profile, route, or Applications writer.

## Owned data and invariants

- a code-owned, versioned capability catalog;
- organization-, edition-, department-, or exact-resource-scoped direct grants;
- immutable versions of organizer-defined role bundles;
- scoped, effective, expiring, and revocable role assignments;
- grant, approval, and revocation provenance for command-managed authority;
- an append-only typed issuance ledger that pins exact actor/approver sources
  or the code-owned initial accountable-representation ceremony;
- bounded delegation linked to the authority that produced it;
- immutable typed bindings between authorization scope and domain-owned
  resources, beginning with `workforce.position`;
- a durable first-scoped-write marker for fail-closed recovery; and
- stable policy decisions with fields, obligations, reason code, and policy
  version.

PostgreSQL guards edition/organization agreement, delegation ancestry,
role-bundle scope, and immutable bundle versions even when ORM validation is
bypassed. Revoking any ancestor invalidates its delegated descendants.

## Public commands and decisions

- `decide(principal, capability_code, resource, requested_fields, at)`
- `decide_verified_principal_exact_edition(...)`, the identifier-only adapter
  that reloads current active/email-verified principal state, seals the exact
  tenant-coherent edition target, and returns a complete ordinary fail-closed
  `PolicyDecision` without exporting Identity or Events model instances;
- `grant_capability_direct(...)`
- `revoke_capability_grant(...)`
- `create_role_bundle_version(...)`
- `assign_role(...)`
- `revoke_role_assignment(...)`
- `require_authorized_control_horizon(...)`, the transaction- and
  lock-requiring read-only assertion for compatible domain writers
- `delegate_capability(...)`
- internal `select_authorized_control_source(...)`,
  `authority_issuance_is_current(...)`, and
  `role_bundle_provenance_is_historical(...)` boundaries for compatible
  writers and sensitive explanations
- `current_role_assignment_ids(...)`, the bounded, identifier-only public read
  boundary used after another module has resolved its own relationships
- `resolve_organization_target(...)`, `resolve_edition_target(...)`,
  `resolve_department_target(...)`, `resolve_resource_target(...)`, and
  persisted owner/self target resolvers
- `require_complete_projection(required_fields, permitted_fields)`
- `freeze_bulk_targets(trusted_queryset, target_ids, authorize)`

The current catalog declares basic edition viewing, edition creation, bounded
Draft/Preparing profile change, edition transition,
self-history, minimized staff participation viewing, capability delegation,
direct-grant management, immediate authority revocation, role management, and
security-audit viewing.

Organization structure read projection uses the separate edition-capable
`workforce.view_structure` and `workforce.manage_structure` declarations.
Manage does not imply view, and a capability stored only at Department or
resource scope is deliberately too narrow for the complete edition tree.

M2 adds organization basic view, organization profile change, series creation,
series change, and the security-critical
`organizations.manage_representation` capability. The representation command
uses exact organization scope and carries reason, audit, and approval
  obligations. These declarations extend the existing policy; they do not create
  a second representation flag or grant authority from membership alone.

ADR 0080 adds the immutable `maru-operators@1` root role. It preserves the
Executive Board's independent-control and provenance model while adding only
organization setup, edition lifecycle/profile, and implemented Workforce
capabilities. Registration, payment, Participation, attendance, and unrelated
module capabilities are absent. Its canonical assignment is the sole
organization-scoped storage exception for edition-bounded capabilities, so the
same accountable operators can govern successive Workforce-only editions.
Ordinary direct grants and roles retain their exact-edition minimum scope;
database triggers reject broader persistence. Policy also admits any reserved
representation root only when the target's exact manifest pins that root-role
code. It therefore refuses to apply the Maru-operator root to a full-convention
edition, including one later created by a platform administrator in the same
organization.

Delegation is dual-authority: the actor must hold an active delegable parent
grant and a separate `authorization.delegate` capability. A child cannot
broaden scope, start before, outlive its parent, or enter an exact edition whose
manifest does not pin the parent's capability. Success writes the child grant,
security audit, domain event, and outbox message atomically.

Root grants, immutable role-bundle versions, and role assignments use
independent human control. The actor and approver must be distinct, the
recipient cannot approve their own authority, both controllers must hold the
command capability in the requested organization/edition scope, and a new
grant or assignment cannot outlive either controller's active authority.
Relationship-derived capabilities cannot be converted into stored grants or
role capabilities.

Compatible ordinary writers now select and lock one exact source issuance for
each controller in the target transaction. Selection is server-owned and
deterministic: narrowest containing scope, direct grant before role assignment,
least surplus expiry with unbounded last, then issuance ordinal. Callers never
submit a source identifier. Generic platform policy is ineligible for these
organizer commands. Role definitions use point-in-time controller authority;
grants and assignments require the complete requested horizon. A legacy or
malformed source fails closed without creating the target or partial evidence.

`require_authorized_control_horizon(...)` lets a compatible domain writer
require one exact current controller source to cover a requested persistent
interval while the same target transaction holds the selection locks. It
returns no selected source or provenance. Equal start and expiry boundaries are
valid; a bounded source cannot cover an unbounded interval. An uncovered start
and an uncovered ending have distinct stable validation reasons, while
unavailable, revoked, or expired authority remains a name-free denial. Adapters
and domain modules must translate those reasons without exposing controller
identities, issuance or grant identifiers, source timestamps, or raw
provenance.

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

ADR 0040 defines one bounded exception for establishing the first controllers.
An active platform administrator may create the reserved immutable
`executive-board` role-bundle version and act as grantor only inside the atomic
Draft-to-Active representation command. At least two accepted eligible
controllers are required, and each assignment is approved by a different
accepted controller in a deterministic cycle. The platform administrator is
never principal or approver. The reserved role is thereafter managed only by
the representation lifecycle: generic role-version, assignment, replacement,
projection, and revocation commands treat it as unavailable. The initial path
cannot be reused as a general approval bypass.

Every compatible initial activation also writes one typed issuance for the
reserved bundle and each root assignment. Its actor control points to the exact
platform-operated activation and its approver control points to the exact
different accepted appointment used by the deterministic cross-approval cycle.
These controls are historical ceremony evidence, not reusable platform
organizer authority. The Board target, representation, appointments, ledger,
audit, event, and outbox remain one transaction.

Organizations `0009` additionally protects linked root assignments at the
database boundary. An active representation must retain the exact immutable
bundle capability set, two or more eligible active controllers, active
memberships, effective non-self cross-approved assignments, and correlated
activation audit/domain-event/outbox evidence. Direct ORM or SQL mutation of
representation identity, appointment provenance, linked assignment scope, or
platform-principal roles is rejected.

Organizations `0010` rejects platform principals for direct grants as well as
role assignments and protects exact Board membership provenance. Organizations
`0011` keeps current authority consistent with ADR 0043 emergency containment:
ended terms retain immutable historical cross-approval evidence, while active
authority, membership, and quorum remain Active-only. Organizations `0012`
and the corresponding participation, registration, and workforce migrations
extend IDN-011 to every covered convention-subject relationship.

ADR 0041 implements the persistent scope lattice—organization → edition →
exact department → exact typed resource—and explicitly denies implicit
department-tree inheritance. Grants and assignments derive scope from one
valid parent tuple. Immutable `ScopedResourceBinding` records identify a
code-owned resource kind within an exact organization, edition, and department
chain; the first kind resolves a real workforce Position.

The ordered `authorization 0004 → workforce 0004 → authorization 0005`
migrations preserve every existing organization- or edition-wide meaning,
harden owning-record containment, backfill reproducible Position bindings,
activate catalog/scope/delegation/revocation guards, and install a durable
downgrade fence. No historical assignment is silently narrowed. The operator
procedure is
[`authorization-scope-v2-migration-and-recovery.md`](../operations/authorization-scope-v2-migration-and-recovery.md).

Authorization `0006` adds `AuthorityIssuance` and `AuthorityControl`, exact
present-row PostgreSQL guards, delegated-parent/zero-control enforcement, and
a nonempty-ledger downgrade refusal. It is deliberately additive: legacy
targets may remain without issuance until provable Board/delegated backfill and
explicit ordinary-authority reconciliation. The stopped-writer procedure and
recovery boundary are documented in
[`authority-provenance-migration-and-recovery.md`](../operations/authority-provenance-migration-and-recovery.md).

Authorization `0007`, paired with audit `0005`, installs the dormant
generation latch, immutable one-row activation marker, same-transaction audit
proof, writer barrier, deferred exact-completeness validators, no-truncate and
reverse fences, and hardened definitions for the older issuance/control/audit
guards it depends on. Audit `0006` adds the reciprocal reserved-operation insert
guard; authorization `0008` delegates only the latch row lock to a
revoked-by-default definer helper so the runtime writer remains serialized
without latch `UPDATE`. Organizations `0013` and workforce `0005` then pin the
four remaining runtime-executable Board/Workforce helpers, and their persistent
trigger callers, to `pg_catalog, public, pg_temp` with `public`-qualified object
and helper references. Authorization `0009` is the convergence leaf and central
downgrade fence; each owning migration also retains its own active-state fence
if the recorder row is damaged. Authorization `0010` and workforce `0007`
extend that same production contract across retired-Department authority and
the Organization structure writer boundary. Authorization `0019` and
Organizations `0014` extend the exact catalog for purpose-bounded Maru-operator
control without rewriting Board evidence. Readiness now fingerprints the
complete current security-critical function set, including the 21-helper
runtime closure and all 14 Organization structure trigger helpers, and verifies
the complete exact trigger-attachment catalog.
The Organization structure subset is exactly 28 attachments, including statement/row event
types, enabled state, `UPDATE OF` column lists, and deferred timing, on
PostgreSQL 17. The downgrade-fence subset also includes all eight
authorization `0010` retired-Department trigger attachments and all three of
their pinned functions. A clean reverse fails readiness through the required
migration-recorder set; partial trigger or function loss fails both the
database-completeness and downgrade-fence gates, so the latter cannot remain
misleadingly resolved.
Activation requires the exact-required external fence, an owned top-level
`READ COMMITTED` transaction, zero blockers, and a stopped-process
acknowledgement. It is irreversible and idempotent after its one successful
marker/audit commit.

`database_role_safety.py` is the read-only PostgreSQL role boundary shared by
activation reporting and public readiness. Its role name, required function
identities, and protected-relation identities are bound parameters. Controlled
migration/cutover-owner sessions use
`target_role_is_safe` to inspect the configured future runtime login without
impersonating it; web/worker health additionally uses
`current_session_is_safe`. ADR 0046's fixed 25-boolean result denies dangerous
attributes, reserved/predefined names, reachable membership admin options,
database or non-system schema/relation/function ownership, database/schema
creation and temporary objects, table trigger/truncate/maintenance, explicit
effective parameter ACLs, non-origin persistent/live trigger settings,
sequence update, object/column grant options, and an unusable data plane. A
safe role has database `CONNECT`, schema `USAGE`, ordinary four-operation DML,
`SELECT`/`INSERT` on Organization structure receipts,
`SELECT`/`INSERT`/`UPDATE` on Organization structure controls, and sequence
`USAGE`/`SELECT`; materialized views and the exact activation control trio
(`django_migrations`, marker, and latch) are SELECT-only and deny table- and
column-level `REFERENCES`. Both Organization structure relations deny `DELETE` and
`REFERENCES`, and receipts additionally deny `UPDATE`.
Department remains on the ordinary DML plane behind its stopped-writer
retirement trigger. The current-session proof additionally
matches `CURRENT_USER`, `SESSION_USER`, and this backend's
`pg_stat_activity.usesysid` to the configured target. Role switching and
session-authorization impersonation therefore prove privileges but never a
healthy runtime login.

`RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V3` enumerates the 21 non-trigger
helpers reachable from current triggers and direct policy execution, including
the narrow definer helper that takes the latch row lock without granting latch
`UPDATE` to runtime. Every non-system function is closed to `PUBLIC`; the role
must execute every listed identity, and neither it nor any membership-reachable
role (including `NOINHERIT` roles available through `SET ROLE`) may execute an
unlisted one. All 21 helpers, including the Board validators, two purpose-
bounded Maru-operator validators, and the Workforce evidence matcher, are
definition-fingerprinted; the audit-owned
reserved-activation operation guard is pinned too. Only the controlled owner
mutates the migration recorder, marker, or latch; the reserved
audit append is valid only as its exact same-transaction companion. The
credential-free operator SQL is the matching executable grant specification.
The 14 `SECURITY DEFINER` Organization structure trigger helpers are definition-fingerprinted
but deliberately absent from this executable allowlist: PostgreSQL invokes
them only through the 28 pinned triggers, and both `PUBLIC` and the runtime
role remain unable to call them directly.

Policy accepts only `ResolvedAuthorizationTarget` values sealed by explicit
database resolvers. Route UUIDs can narrow a query but cannot assert tenant,
department, resource, lifecycle, or owner facts. Commands lock and re-resolve
the target, repeat their policy decision in the transaction, and derive audit
and event scope from that target. Organization authority covers narrower
same-tenant targets; edition authority covers that edition; department
authority covers only that exact department and its bound resources; resource
authority covers only that exact binding.

Issuance fields are append-only at the PostgreSQL boundary. Replacement uses a
new record; revocation is single-control, evidence-complete, and one-way; hard
deletion is refused. Role bundles reject unknown, duplicate, null, and
relationship-only capabilities. Delegation cannot change capability or tenant,
move sideways or upward, start before or outlive a parent, or form a cycle.
The full chain is evaluated on every decision, so ancestor revocation remains
immediate.

Department retirement preserves immutable resource bindings and expired or
revoked authority as history; those rows do not keep the Department live. New
bindings and current authority remain forbidden beneath the retired target,
and any retained binding still blocks hard deletion. Because normal target
resolvers intentionally exclude retired Departments, two dedicated close-only
commands may add revocation evidence to an expired, unrevoked capability grant
or non-reserved role assignment. They first authorize and recheck
`authorization.revoke` at a current containing organization or exact edition,
then lock and prove the stored organization/edition/Department/resource chain.
Audit and event scope comes from that persisted historical row. Wrong tenant,
wrong edition, current Department, unexpired authority, and already-revoked
authority fail closed; the commands cannot issue, extend, move, or reopen
authority.

`ensure_workforce_position_binding(position=...)` is the explicit live-write
integration for the currently supported typed resource. It locks and re-reads
the persisted Position, creates the same deterministic immutable binding as
activation backfill, returns an existing exact binding idempotently, and fails
closed when existing scope or deterministic identity conflicts. Owning
workflows call this public application service after Position persistence in
their transaction; Maru deliberately does not use a model signal, generic
foreign key, or hidden cross-module database write trigger for this step.

## Enforcement

The reusable projection guard fails closed when a serializer contract exceeds
its policy field ceiling. The bulk target freezer requires an open transaction,
a tenant/edition-filtered trusted base query, non-empty unique IDs, an exact
resolved set, row locks, and a positive policy decision for every target before
returning anything to a command.

`events.create` and `events.change_profile` carry the same minimized C1
response ceiling as `events.view_basic`; successful mutation responses are
checked against that ceiling rather than treating write permission as an
unbounded read. Creation is organization-scoped and profile change is exact-
edition-scoped. HTML platform administration remains a separate platform
policy path and creates no stored convention grant.

The `/admin/` shell does not use Django `is_staff` as a convention-authority
shortcut. Active platform administrators receive platform scope. Every
ordinary shell entry, tenant name, navigation link, edition option, and context
change is derived through the same canonical capability decision as its
destination. Compatibility readers validate legacy grant chains before
cutover; exact readers validate pinned issuance lineage afterward. A required
but dormant/malformed contract and a revoked pinned ancestor produce no
organizer projection. Specialist Django records remain separately staff/model-
permission protected.

The navigation projection resolves organization, edition, department, typed
binding, and owning Position chains through identifier-only bulk reads. Its
tenant-chain query count is constant as authority cardinality grows; exact
issuance checks use a fixed schema-qualified PostgreSQL call in chunks of 256
and preserve positional results. A role assignment proves one representative
capability from its immutable, provenance-validated bundle, then projects only
known persistable capabilities from that same bundle. A 257-scope regression
guards both query amplification boundaries without loading tenant names.

Every exact-edition authority row is also narrowed against that edition's
immutable manifest before it enters the projection. When organization-scoped
authority expands into candidate editions, the name-free projection preserves
the kind of each source: direct capabilities are checked individually,
ordinary organizer roles must remain compatible as a complete capability set,
and reserved purpose roots must be pinned by role code. Admin selection and
self-context then repeat this exact-pair check before querying or returning an
edition name. A Maru-operator assignment can therefore disclose Workforce-only
editions in its organization without fanning out into a full-convention
edition.

`current_role_assignment_ids(...)` accepts at most 4,096 already bounded
RoleAssignment identifiers. In compatibility mode it applies current term and
revocation checks. In exact mode it additionally resolves the stored scope and
validates each row's pinned issuance lineage through the existing bounded
authorization evaluator; a required-but-dormant or malformed exact contract
returns no IDs. The workforce structure query calls this before asking identity
for any holder label, so invalid role evidence cannot disclose a person's
name.

`check_scope_v2_readiness` emits a count-only JSON report. Migration-data
`status` is intentionally separate from `production_status`. The guarded exact
policy, recursive readiness, completeness guards, and final fence are locally
implemented and activated with synthetic data. A real deployment remains
blocked until ordinary legacy authority is explicitly reconciled and the
stopped-writer cutover/recovery ceremony is completed. No current claim treats
the local activation as permission to infer legacy evidence or relabel the
platform production-ready.

After authorization `0006` is present,
`check_authority_provenance_readiness` inspects the reachable issuance graph
and emits only stable aggregate blocker/review counts. A zero-blocker `status`
means stored data is structurally ready; `activation_status` additionally
requires the dormant PostgreSQL 17 guard catalog; `production_status` requires
the exact marker/audit/policy and downgrade fence. The command never prints
people, capabilities, organizations, target identifiers, or entered reason
values, and `--no-fail` changes only its process exit behavior.

`backfill_provable_authority_provenance` is read-only by default and can append
only exact initial Executive Board ceremony rows plus exact delegated-parent
chains. Mutation requires `--apply --acknowledge-writers-stopped`, locks and
verifies one graph transaction, remains idempotent, supports immutable
suspended/ended Board history, and suppresses private exception context.
Ordinary legacy grants, role definitions, and assignments are count-only
review debt and must be deliberately revoked/recreated; the reconciler never
infers their actor or approver sources.

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
  `authority-controller`, `executive-board`, and `maru-operators` roles from
  role lists, assignment projections, exact resolution, replacement, and
  removal. Every
query is scoped by trusted organization and edition route values before
records are returned. Sensitive workspace reads and all underlying authority
mutations are audited.

The UI calls role bundles “groups” because Front Desk, Registration, Board,
Treasurer, and similar convention teams are familiar sharing concepts. They
remain complete scoped roles, not Django Groups or page-local allowlists.
People are shown by display name and exact email; assignment UUIDs are
transport identities and are not rendered as primary labels.

For an adopted-profile edition, every listed organizer-created group and
assignment must have a non-empty capability set wholly pinned by the exact
profile manifest. Arbitrary organizer role codes are not manifest entries;
reserved accountable roots instead require their exact root-role pin. Query
projections filter incompatible historical groups before disclosure, while
exact role lookup, create, replace, and assignment commands reject a crafted
incompatible role at edition, Department, or resource scope with
`module_not_adopted`.

Access sharing is not a workforce appointment. It does not fill a position,
check an NDA, add hierarchy/reporting relationships, create staff or volunteer
capacities, or publish an official role. Use the workforce position-assignment
workflow when those consequences are required; use access sharing for a
reasoned system-access assignment.

## Shared page Access component and preview

The stable `{% maru_page_access %}` template contract mounts one computed
**Access** explanation in the administration, baseline-management, and public
registration shells. It resolves the persisted organization, edition, exact
Department, or supported typed resource before evaluating capabilities. The
signed workspace locator is only a tamper-evident pointer; the server re-resolves
the complete tenant chain and current authority on every request.

Mutable scoped pages link to the canonical role-assignment commands. They do
not store page ACLs. Platform, own-record, attendee/public audience,
representation, safeguarding, and security pages explain their fixed policy
and omit mutation. Named people and immutable role versions are released only
after `authorization.manage_roles` succeeds and the sensitive relationship read
is audited.

The server-rendered workspace supports exact-person and hypothetical immutable-
role previews. Preview never changes the session principal, never enables write
controls, is capped by the real viewer's field authority, is private/no-store,
and appends minimized audit evidence. Assignment and revocation POSTs ignore
all preview concepts and authorize the real signed-in account against the exact
resolved target.

## Specialist records

Capability grants, role-bundle versions, and role assignments are searchable,
filterable inspection pages. Lists show the person, human-readable role or
capability, resolved human scope, current state, compact effective term,
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
Provenance-specific tests cover fresh/additive migration, clean reverse and
nonempty downgrade refusal, model and raw-SQL immutability, typed target/control
shape, exact persistent and Board bases, delegated zero-control parent lineage,
deterministic least-authority selection, bounded point-in-time definitions,
cycle/depth fail-closed behavior, pinned no-rebind revalidation, Board current-
state loss, stale relation caches, and transactional rollback.
Access-workspace integration tests additionally cover deny-without-disclosure,
human group labels, latest-version selection, organization/edition isolation,
exact-email matching, independent approval, unknown-account rejection,
atomic replacement, immediate removal, and cross-tenant assignment hiding.
Workforce-only coverage additionally proves incompatible-group filtering,
crafted assignment rejection, profile denial before platform policy, and
retained Workforce groups.
They also prove that Board controllers and platform administrators cannot use
generic authority commands or the workspace to list, version, share, replace,
or revoke reserved Executive Board authority.

Representation & access policy, command, and browser-adapter tests cover exact organization
scope, bounded platform bootstrap, non-platform subjects, two distinct cross-
approvers, reserved role conflicts, stale/replayed activation and invitations,
inactive or suspended controllers, immutable role creation, platform exclusion,
rollback, and cross-tenant/principal non-disclosure. Populated and empty
migration, restore drill, sensitive read/denial audit, and responsive browser
evidence pass. Scope-v2 evidence includes additive-schema,
workforce-integrity, activation/reverse, database-bypass, exact policy,
command, adapter, and privacy-minimized readiness-command suites. Final
consolidated full-suite and coverage totals are recorded in
`docs/project/CURRENT.md` and the milestone checkpoint rather than duplicated
here.

## Limitations

Production legacy reconciliation/cutover, representative authority load,
step-up execution,
service/device principals,
asynchronous approval workflow, grant review reminders, purpose binding, and
policy caching are not implemented. The synchronous independent approver
argument is a command invariant, not yet an approval inbox or pending request
state. Representation & access replaces the old operations-only first-controller procedure and
its initial backend security matrix passes. The reusable
enforcement contracts must be adopted
and extended with each domain slice; they are not a generic shortcut around
domain-specific relationships and state.

The shared contextual workspace resolves organization, edition, exact
Department, workforce Position, charity selection, and venue-space targets.
Additional future typed-resource kinds must register their deterministic
binding resolver before receiving a mutation link. Appointment
expiry/replacement/end and explicit legacy authority reconciliation remain
open.
