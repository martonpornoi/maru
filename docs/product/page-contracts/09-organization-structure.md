# Page 9 contract: Organization structure

- Status: Page 9a.1 bounded version-fenced read, shared Department command and
  stopped-writer database core, and strict HTML/API mutation adapters mounted;
  definitive repository/coverage acceptance passes, while responsive-browser,
  accessibility, owner, and deployment-recovery acceptance remains pending
- Route: `/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/structure/`
- Current browser mutations: separate POST-only template application,
  Department create, complete update/reparent with automatic sibling placement,
  retire, and protected delete actions reached through same-shell child GET
  pages
- Current API: strict
  `/api/v1/organizations/<organization-id>/editions/<edition-id>/workforce/structure`
  GET projection plus five strict template/Department mutation operations
- Requirements: IDN-002, IDN-004, IDN-009, IDN-011, IDN-012, EVT-002,
  EVT-003, HR-007, HR-010, HR-011, UX-019, UX-020, UX-025, AUD-001,
  AUD-005, INT-001, NFR-001 through NFR-004, NFR-008, and NFR-009
- Decisions: ADRs 0007, 0028, 0036, 0039 through 0042, 0044, 0045, and 0048

## Purpose and primary users

Page 9 lets an authorized organizer establish and maintain the Department tree
for one exact event edition. It also explains how that operational structure
sits beneath the organization's accountable governance without creating a
second representation record.

The first management slice serves:

- an active platform administrator exercising explicit oversight as an actor,
  never as a convention subject;
- an organizer with `workforce.view_structure` effective at the exact edition,
  who may read the complete minimized tree; and
- an organizer who additionally has `workforce.manage_structure` at that
  edition, who may apply the built-in reference and manage Departments.

It is not a Board appointment page, people directory, general access editor,
Position/role-bundle editor, volunteer assignment tool, or generic specialist
model form.

## Implemented Page 9a.1 read and management slice

The current implementation mounts the canonical overview, its same-shell child
pages, five browser mutation actions, the strict GET projection, and five API
mutation operations. It removes the older React Convention work `structure`
destination and `?view=structure` path, so there is one browser workflow and
one current navigation action. Every adapter calls the shared application
services and database write protocol; no Page 9 adapter writes a Department
through a model form or direct ORM save.

The organizations module returns only the fixed **Executive Board** label and
its `absent`, `provisioning`, `active`, or `suspended` representation state.
The workforce projector separately returns edition Departments, Positions,
reporting labels, and current minimized holders. The governance anchor has no
Department identifier or workforce parent and remains separate even when a
legacy operational Department is also named Executive Board.

The current projector owns these hard ceilings:

| Projection dimension | Page 9a.0 ceiling |
| --- | ---: |
| Departments | 256 |
| Positions | 1,024 |
| effective holder relationships | 4,096 |
| Department or Position reporting depth | 32 |
| expanded cross-position `other_roles` edges | 16,384 |

Every row-limited query uses a limit-plus-one probe. Crossing any ceiling or
depth/expanded-edge bound returns `structure_limit_exceeded` with an empty
Department collection; no partial hierarchy or holder label is returned.
Malformed parent/reporting graphs fail through the generic dependency boundary
instead of being repaired or presented incompletely.

A holder label is resolved only after the workforce relationship is current,
the linked RoleAssignment has one supported exact edition/Department/resource
scope shape, authorization confirms that assignment's current pinned lineage,
and identity confirms an active person account. The projection exposes display
name and other operational role labels only. It excludes login handle, email,
account kind/state, assignment identifier, entered reason, and authority
provenance.

The HTML and API read adapters capture one projection instant and repeat a
fresh final `workforce.view_structure` decision before releasing the
name-bearing response. The GET rejects every query parameter with a typed
`400`, uses a non-disclosing `403` for missing authority or unavailable route
scope, and a generic `503` for database, integrity, or policy dependencies.
Those `400`/`403`/`503` RFC 9457 responses are explicit in OpenAPI.

After the fresh final decision, the overview, child forms, and any audited
invalid/conflict rerender append one minimized
`workforce.structure.read` sensitive-read audit containing actor, exact
organization/edition target, source channel, outcome, obligation, and only the
policy version, actual resolved route name, and actual HTTP method as safe
metadata. A failed POST therefore records its POST action provenance rather
than pretending that the rerender was a GET. Audit persistence is part of the
disclosure boundary: a
failure returns the same generic name-free `503` and releases no holder label
or partial structure.

The read is fenced by the exact edition structure aggregate version. Its
Department, Position, assignment, identity-label, and governance queries run
inside one snapshot attempt; READ COMMITTED adapters compare the control
version before and after composition and retry the complete read once. A
second movement fails through the generic name-free dependency boundary.
Fresh final authorization remains independently required because snapshot
coherence is not a substitute for current authority.

## Placement, scope, and navigation

The shared sidebar reveals **Organization structure** once beneath the selected
edition. It is current exactly once on the overview and each Page 9 child page,
and uses the same Maru logo, record header, modules, form language, focus
treatment, and responsive stacking as Pages 3 through 8. No second menu,
workspace selector, or Quick Start panel is added.

The canonical browser surface is:

```text
GET  .../structure/
GET  .../structure/template-application/
POST .../structure/template-applications/
GET  .../structure/departments/new/
POST .../structure/departments/
GET  .../structure/departments/{department_id}/
POST .../structure/departments/{department_id}/update/
POST .../structure/departments/{department_id}/retire/
POST .../structure/departments/{department_id}/delete/
```

The ellipsis is the exact persisted organization/series/edition slug chain.
Overview access requires view authority; every management child and action
requires both the exact view and manage decisions. GET and POST responsibilities
are separate, every action is CSRF protected, every rendered name-bearing or
form response is private `no-store`, and a successful mutation uses
POST/Redirect/GET. Child pages and actions reject query parameters rather than
accepting an alternate mode. Framework-generated denied/not-found responses
remain name-free but are not claimed by this rendered-response cache contract.

The route's organization, series, and edition slugs are untrusted locators. The
view resolves the complete persisted chain before a tenant name enters the
response. A selected-edition session neither changes route scope nor grants
access. Anonymous users follow the standard login redirect. Inactive, foreign,
unknown, stale-lineage, and under-scoped users receive the existing safe
denied/not-found boundary without another tenant's names or counts.

An organizer needs `workforce.view_structure` effective at the edition target;
a capability stored only at one Department or Position is deliberately too
narrow for the complete tree. Management requires a second current decision
for `workforce.manage_structure`. Platform oversight is evaluated separately
and never creates a membership, participation, role assignment, or workforce
assignment.

The header computes, rather than stores, these access explanations. It names
safe role groups or people only when the current viewer may already see those
relationships. It does not show a hidden-principal count, imply that hierarchy
means access, or provide a page-local ACL. A **Manage access** action appears
only when the exact underlying authorization workflow is mounted and the
current viewer can use it; no inert or authority-bypassing shortcut is shown.

## Governance-anchored projection

The first branch is composed as:

```text
Executive Board — governance state from OrganizationRepresentation
  Convention Coordination — top-level Department in this edition
    operational Departments
      optional nested Departments
```

Executive Board is a discriminated presentation node from the organizations
module. It reports only its fixed human label and truthful absent,
Provisioning, Active, or Suspended state. It has no Department identifier and
is never persisted or mirrored as a Department, Position, generic group, or
PositionAssignment. Page 8 remains the owning representation workflow.

Convention Coordination is a real Department with no persisted parent. Page 9 visually
places it beneath the governance node. Every subsequent parent relationship is
an exact same-organization, same-edition Department edge. Moving a Department
changes presentation structure only; it does not move, widen, replace, or
inherit a CapabilityGrant or RoleAssignment.

The read result has stable ordering and code-owned ceilings. It either returns
the complete permitted structure within those ceilings or an explicit
`structure_limit_exceeded` state; it never presents an incomplete editable tree
as complete. It may include existing Position labels, reporting edges, and
currently effective permitted holders under HR-010, but excludes email,
account state, appointment identity, private HR/application/document data,
reason text, raw authority provenance, and unrelated tenant data. Transport
identifiers used for links and commands are not rendered as human content.

## Empty state and built-in reference

The overview offers **Use the fictional MaruCon starter** to an authorized manager
when an edition has no workforce structure. The immutable built-in selection is
`marucon-reference@1`; a later template is another version, never an edit of
version 1.

Page 9a.1 implements and pins the code-owned template catalog, transactional
application command, and strict browser/API adapters. The catalog is
immutable, resolves only the exact versioned
identifier without aliases, validates bounded unique codes/names/order,
requires exactly one root whose parent precedes every child, forbids an
Executive Board Department, and retains canonical UTF-8 JSON plus SHA-256
content evidence. Version 1 has Convention Coordination as its sole root and
all 21 operational Departments as its direct children.

Version 1 creates these 22 Department records:

```text
Convention Coordination
  Attendee Services
  Registration
  Programme
  Stage Production
  Venue Operations
  Logistics
  Volunteer Support
  Safety
  Accessibility
  Technology
  Communications
  Design & Publications
  Exhibitors
  Charity
  Guest Relations
  Accommodation
  Hospitality
  Finance & Procurement
  Partnerships
  Live Operations
  Archive & Handover
```

It does not create Executive Board. It also creates no account, membership,
appointment, representation, Participation, registration, capability grant,
role bundle, Position, volunteer opportunity, application, onboarding request,
assignment, shift, or public-roster relationship.

The action is available only for a Draft or Active organization, a Draft or
Preparing edition, and an empty exact-edition workforce structure. Empty means
zero Departments, Positions, PositionAssignments, workforce resource bindings,
and earlier structure-template receipts. A pre-existing registration, venue,
or other separately owned edition configuration is not treated as workforce
content and is untouched.

| Field | Type and format | Bounds and blank meaning | Normalization | Classification and writer | Lifecycle and retention |
| --- | --- | --- | --- | --- | --- |
| `template` | Closed built-in code and integer version | Exactly one currently offered immutable version; required | No aliases | C0 code-owned choice; exact structure manager | Source version/digest retained permanently in application receipt |
| `expected_version` | Integer | Exactly `0` for first application; required | Strict integer parsing | C1 control metadata; exact structure manager | Compared under aggregate lock; winning application advances once |
| `confirmation_name` | Unicode text | Exact current edition name, at most 160 characters; required | No case folding or whitespace rewriting | C1 high-impact confirmation; exact structure manager | Used for the attempt; not copied as a second edition fact |
| `reason` | Unicode text | 1–240 characters; required | Trim ends and collapse ordinary whitespace | C1 administrative rationale; exact structure manager | Retained in command evidence but excluded from event payload |
| `retry_key` | UUID | Required in browser state; absent from API JSON | Canonical UUID | C1 control metadata; server creates browser value | Immutable application receipt; API uses `Idempotency-Key` header |

Unknown fields and any client-supplied organization, series, edition, actor,
template digest, output version, state, timestamp, audit, or event value are
rejected. Concurrent applications serialize. A replay with the same actor,
scope, key, and normalized input returns the first outcome; changed reuse
conflicts. A partial template is never committed.

## Department creation and editing

The Department editor is available only in Draft and Preparing editions under
a non-Suspended, non-Closed organization. The page offers create, complete
update/reparent with automatic sibling placement, retire, and protected delete
as separate operations.

| Field | Type and format | Bounds and blank meaning | Normalization | Classification and writer | Lifecycle and retention |
| --- | --- | --- | --- | --- | --- |
| `name` | Unicode text | 1–160 characters; required | Trim ends and normalize ordinary whitespace | C0/C1 operational label; structure manager | Editable before retirement; old value survives in audit/activity meaning where required |
| `description` | Unicode text | 0–1,000 characters; blank means no description | Trim outer whitespace; preserve meaningful internal punctuation | C1 operational description; structure manager | Editable before retirement; excluded from audit/event payload |
| `parent_department_id` | UUID or blank | Blank means top-level; otherwise required exact current Department | Canonical UUID; no alias/name lookup | C1 relationship; structure manager | Must remain in exact edition; never implies authority inheritance |
| `expected_version` | Integer | 0 for first mutation of an absent structure, otherwise current positive value | Strict integer parsing | C1 control metadata; structure manager | Compared under structure lock; changed command advances once |
| `reason` | Unicode text | 1–240 characters; required | Trim ends and collapse ordinary whitespace | C1 administrative rationale; structure manager | Retained with command/audit purpose; excluded from public projection |
| `retry_key` | UUID | Required only for creation | Canonical UUID | C1 control metadata; server/browser or API header | Retained in immutable creation receipt |

Department code, organization, series, edition, retirement state, aggregate
version result, actor, timestamps, and browser display order are server-owned.
Code is generated as a stable lower-case slug of at most 80 characters with
deterministic same-edition collision handling and cannot be edited later.

For browser commands, Maru assigns presentation order while holding the edition
structure lock. Creation and reparenting append after all persisted siblings at
the chosen level. An ordinary edit preserves a unique current order; if that
Department shares a legacy or integration-supplied order with a sibling, the
save repairs the edited Department into the nearest following free position so
it does not jump past unrelated later siblings. Existing equal orders remain
deterministic by normalized name and stable identifier until individually
edited; a read never performs a hidden write. The strict API retains the
bounded explicit `display_order` field for integrations that deliberately plan
an ordering.

The parent selector is scoped before names are loaded. It excludes the current
Department, its descendants, retired records, and every foreign organization
or edition. The service re-resolves the submitted identifier and repeats cycle
and exact-chain checks under stable locks. Database constraints remain the
final protection against raw, bulk, or concurrent cycles.

A normalized no-op returns success without advancing the version, audit, event,
or outbox. A stale expected version returns a conflict with reload guidance and
does not merge fields automatically. Browser validation and conflict responses
retain the exact submitted retry key and expected version, disable a stale
submission, and require an explicit reload; they never silently refresh those
control values.

## Retirement and protected deletion

Retirement is a separate one-way POST action in Page 9a. It accepts only the
current expected structure version and reason. It is refused while the
Department has a current child, open Position, an active assignment whose term
has not ended, unclosed authority that is effective now or scheduled for later,
or another dependency whose meaning would be obscured. Successful retirement
preserves the Department, stable code, parent history, and every closed
relationship, including immutable Position bindings, and prevents new
children, Positions, or access targets.
An immutable typed-resource binding is retained historical evidence and does
not by itself block retirement, even though it still prevents hard deletion
and a new binding cannot be created beneath a retired Department. Reactivation
needs a future explicit contract.

Hard deletion is limited to an unused leaf Department. In addition to expected
version and reason, the form requires `confirmation_name` exactly equal to the
current Department name. Under lock the service proves there is no child,
Position, PositionAssignment, workforce resource binding, authority,
cross-module reference, or operational history beyond initial creation. It
never cascades. Failure returns a protected conflict and identifies retirement
as an alternative only when retirement itself is safe.

The database deletion contract recognizes all 13 current Department foreign
keys, including the Applications, Charities, Logistics, Registration, and
Venues references added after the original Page 9 cutover. Workforce `0008`
depends on those exact FK-creator migrations. Its reverse restores the `0007`
allowlist and therefore fails deletion closed until the successor references
are removed by a graph-consistent downgrade.

Template-created Departments are not privileged: they can be changed, moved,
retired, or deleted under these same rules in the edition copy. The immutable
template receipt remains truthful even after the copy diverges.

## Shared service and API boundary

The HTML and API adapters share the same bounded workforce query,
organizations governance-anchor query, and mutation services. The mounted Page
9a API surface is:

```text
GET    /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/structure
POST   /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/structure/template-applications
POST   /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/departments
PUT    /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/departments/{department_id}
POST   /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/departments/{department_id}/retire
DELETE /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/departments/{department_id}
```

API scope comes only from the route. Template application and creation require
one canonical UUID `Idempotency-Key` header and reject that key in JSON. The
same supplied key must be retained by a caller that retries; client helpers do
not invent a replacement. Update, retire, and delete use the expected aggregate
version in their closed body. DELETE has a required JSON body containing
`expected_version`, exact `confirmation_name`, and `reason`.

The mutation status contract is:

| Operation | Success | Declared problems |
| --- | --- | --- |
| template application | `201`; identical replay `200` | `400`, `403`, `409`, `503` |
| Department creation | `201`; identical replay `200` | `400`, `403`, `404`, `409`, `503` |
| complete Department update | `200` | `400`, `403`, `404`, `409`, `503` |
| Department retirement | `200` | `400`, `403`, `404`, `409`, `503` |
| protected Department deletion | `200` | `400`, `403`, `404`, `409`, `503` |

Template success returns only `aggregate_version`. Department success returns
only `department_id` and `aggregate_version`. Closed JSON serializers reject
unknown properties and type coercion, including strings or booleans submitted
for integer fields. Canonical UUID fields accept only the lower-case,
hyphenated form.

Authentication and exact view/manage authorization occur before an
idempotency header or body is parsed. Missing authority and unavailable route
scope share the non-disclosing `403` code `structure_authorization_denied`.
Only after authorization may an unavailable, foreign, retired, or otherwise
ineligible Department/parent target return the name-free `404` code
`structure_department_unavailable`. Problems use the repository's RFC 9457
media type and stable codes for validation, stale, protected, lifecycle,
limit, denied, not-found, idempotency-conflict, and dependency failures.

The GET response is the exact organization and edition labels, minimized
governance discriminator, and either one complete nested structure or the
explicit empty overflow state. Its declared problem statuses are `400`, `403`,
and `503`; it does not declare a separate not-found shape that could reveal
whether a foreign route exists. OpenAPI and generated clients must remain
deterministic.

Each mutation locks and verifies the organization -> series -> edition chain,
structure aggregate, and affected Departments, repeats policy and lifecycle,
validates the complete resulting model, and commits one aggregate version,
minimized audit, `workforce.structure.changed.v1`, and transactional outbox
fact together. Failure of any member rolls back all members. No adapter may
fall back to direct model save.

## Page states

- **Empty:** governance anchor plus explanation, reference action for managers,
  and manual create action; no Specialist-record detour.
- **Populated:** complete nested Department tree, existing minimized Position
  projection, source/version summary, and controls according to exact access.
- **Diverged copy:** source receipt remains visible while explaining that the
  edition is independent of the built-in version; once its aggregate advances
  beyond the template application result, the overview says **Reference copy
  changed** rather than implying live synchronization.
- **Read-only lifecycle:** Ready, Live, Closing, Archived, Cancelled, Suspended,
  or Closed reason shown with no mutation controls.
- **Validation:** field-local errors, safe entered values retained, no partial
  tree or evidence.
- **Stale/idempotency conflict:** winning version retained with reload guidance.
- **Protected:** dependency-safe explanation without leaking hidden people or
  records.
- **Denied/not found:** no foreign tenant name, structure, count, or principal.
- **Limit exceeded:** explicit complete-tree-unavailable state; no misleading
  partial editor.
- **Dependency failure:** generic retry guidance and no partial write.

Every state needs keyboard order, visible focus, associated errors, semantic
tree/list or heading structure, sufficient contrast, and desktop plus 390-pixel
evidence without horizontal overflow.

The overview is the only page that renders the complete tree. Child editors
use bounded parent labels and native form controls, never a copy of the full
hierarchy. At narrow widths hierarchy indentation is reduced, actions stack,
and the parent selector remains within the viewport. These are implemented
interaction rules; the final authenticated desktop/390-pixel state matrix,
keyboard traversal, and automated accessibility evidence remain release gates.

The shared baseline form stylesheet explicitly lets native single-select
controls grow beyond Django Admin's fixed 30-pixel height. This keeps the
currently selected Parent Department label visible after pointer or keyboard
selection while retaining the native control and its accessible name.

## Current implementation evidence

The pre-adapter command/database graph passes 1,471 tests in 1,538.40 seconds
on fresh isolated PostgreSQL at 90.13 percent branch coverage. The strict
mutation API focus passes 48 tests. A fresh isolated combined Page 9 gate
passes 159 tests in 102.89 seconds across core/forms, bounded reads, HTML
mutations, mutation and adjacent workforce APIs, exact-lineage navigation, and
unified routing. These invocations overlap and must not be summed.

Adapter hardening adds 118 targeted cases: 59 HTML, 50 API/contract, and 9
immutable-template invariants. The HTML selection passes 59 tests with 27
deselected in 28.13 seconds, and the adjacent API/contract batch passes 152
tests in 73.90 seconds. The definitive adapter-expanded repository invocation
passes all 1,693 tests in 1,653.43 seconds at 90.50 percent total
branch-inclusive coverage. Final Ruff, mypy, Django/system/migration,
deploy-shaped production-settings, deterministic OpenAPI/client, frontend, and
dependency gates pass. Chrome was unavailable to current desktop automation,
so the authenticated desktop/390-pixel state matrix, keyboard/automated
accessibility, owner rehearsal, representative production cutover, and whole-
database restore/PITR evidence remain pending.

## Migration and recovery implications

Workforce `0006` and the stopped-writer `0007` cutover create one
structure-control aggregate per existing
populated edition without changing Department identifiers, names, parents, or
codes. Such rows are marked legacy-existing and receive no template receipt.
Names such as Executive Board or Convention Coordination never trigger representation,
template, person, role, or parent inference. Empty editions remain eligible at
version zero.

Workforce `0008` changes no table or retained data. It replaces the closed
Department-FK contract helper only after every current reference creator is
installed, preserves its owner and ACL, and adds its recorder row and exact
13-reference catalog to fail-closed readiness.

Preflight reports count-only malformed scope, cycle, duplicate-control,
unsupported-reference, and version blockers, with at most bounded safe edition
labels under platform-only operation. Database guards protect immutable
organization/edition/code and receipt provenance, monotonic aggregate version,
same-edition parents, cycle freedom, non-cascading retirement, and incompatible
downgrade after the first new write.

After that activation, generic Department/Position specialist records are
inspection-only for mutations covered by Page 9. Recovery fixes forward or
restores workforce, authorization bindings, audit, events, and outbox to one
consistent point. It never deletes only the structure control/receipt or
invents template provenance for legacy rows.

## Acceptance checks

- exact platform/view/manage/department-only/inactive/anonymous/foreign and
  unknown access matrix for page, nav, header, and every command;
- Executive Board comes only from OrganizationRepresentation and no Department,
  Position, appointment, membership, participation, assignment, role, or grant
  is synthesized by the structure template;
- exact 22-Department version-1 content and parent/order/code determinism;
- empty-only application, same-input replay, changed-input conflict,
  concurrent apply, stale version, and atomic rollback;
- strict fields, Unicode/bound/control validation, collision-safe codes,
  same-edition parents, self/descendant/cross-tenant rejection, and concurrent
  cycle prevention;
- create/no-op/update/reparent, browser automatic placement and duplicate-order
  repair, API reorder version behavior, and minimized correlated audit/event/
  outbox evidence;
- retirement dependency matrix and exact-confirmation non-cascading deletion;
- deterministic bounded complete projection, explicit overflow, no email,
  account state, private evidence, hidden count, or rendered technical ID;
- fresh final authorization plus minimized HTML/API sensitive-read audit before
  disclosure, with audit failure returning a name-free `503` and no partial
  labels;
- query-count ceilings and prefilter-before-name proof for every scope level;
- HTML/API service parity, strict RFC 9457 problems, OpenAPI validation, and
  deterministic generated client;
- separate same-shell child GET/POST routes, CSRF, rendered-response no-store,
  PRG, one current navigation item, strict browser input, retained
  retry/version controls, and actual method/route read-audit provenance;
- fresh and populated migration, raw/bulk SQL guards, concurrency, downgrade
  fence, restore/fix-forward rehearsal, and no inferred legacy provenance; and
- empty/populated/diverged/read-only/validation/stale/protected/denied/limit/
  dependency states at desktop and 390 pixels with accessibility evidence.

## Explicit non-goals

- Creating, changing, or assigning Positions, including Lead, Deputy, or
  Volunteer roles; this is Page 9b after the authority-bearing contract.
- Provisioning, changing, or publishing Executive Board appointments.
- Inferring access from Department nesting or editing CapabilityGrants and
  RoleAssignments as page-local ACL entries.
- Merging the reference into a populated tree or synchronizing a copy to a
  later built-in version.
- Importing real-convention usernames, people-to-role mappings, contact information,
  avatars, or other live roster data.
- Structural change control for Ready, Live, or Closing editions.
