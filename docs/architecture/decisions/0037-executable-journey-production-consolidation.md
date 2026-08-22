# ADR 0037: Consolidate through executable convention journeys

- Status: Accepted
- Date: 2026-08-01

## Context

Maru has two useful but incompatible bodies of work.

The current architecture is a security-first Django modular monolith with a
versioned API, tenant and edition scope, append-only audit, transactional
effects, registration, workforce, accreditation, and privacy foundations. The
controlled experience rebuild has mounted four deliberately small management
pages: organization inventory, organization creation, organization record,
and convention-series creation.

Two remote legacy branches contain a much smaller monolithic prototype with
useful interaction evidence for applications, rooms, room combinations,
timetable layers, panels, volunteer shifts, hotels, exports, and signage. They
have no common Git ancestor with the current architecture and use incompatible
identity, scope, authorization, model, migration, and template assumptions.

The page-by-page rebuild restored clarity, but requiring a separate owner gate
before designing every following page now prevents an executable convention
journey from emerging. The documents also mix implemented, mounted,
preserved-but-unmounted, aspirational, and deployment-gated behavior, which
makes the repository feel more complete and more confusing than the running
product actually is.

The product owner has asked for one coherent administration experience capable
of replacing fragmented convention tools, while retaining a stable API for
seasonal public clients. The first reference operation is fictional. The
platform administrator must retain oversight without becoming a participant in
any organization or edition.

## Decision

### Consolidation base

Development continues from commit `327a7d6`, the tip that contains `main`, the
pre-reset foundation, and Pages 0 through 4. Existing local page branches stay
unchanged as review landmarks. No current local branch is merged or
cherry-picked because each is already an ancestor.

The remote legacy histories are read-only behavioral references. Maru may
translate their workflows, tests, wording, or interaction lessons into the
current domain boundaries, but must not merge their histories, copy their
migrations, or import their global-project authorization assumptions.

### Delivery unit

The delivery unit becomes an **executable vertical milestone**, not one
isolated page. A milestone may contain several small page contracts when all are
required for one safe user journey. Every mounted page still requires its
purpose, navigation position, scope, states, permissions, tests, documentation,
desktop evidence, and narrow-viewport evidence.

The first milestone is the edition workspace spine:

1. organization record;
2. convention-series record;
3. audited edition creation;
4. edition record and persistent context;
5. organization representation and access explanation.

The first differentiating operational milestone is:

1. submit a panel proposal;
2. review and accept it into a private programme item;
3. select reusable venue spaces for the edition;
4. place the item with preparation, effective, and teardown times;
5. add department and shift-planning layers;
6. publish an immutable timetable release and API projection.

### One management shell

All authenticated organizer and platform work uses one coherent `/admin/`
namespace and one responsive navigation system. The accepted Pages 1 through 4
establish its current visual grammar. Specialist records and operational boards
may use different task-appropriate layouts inside that shell, but they must not
introduce a second global menu, independent staff application, or competing
identity.

This partially supersedes ADR 0026's requirement that the visible shell remain
an implementation of Django's original administration templates. It preserves
ADR 0026's single namespace and unified-product intent. It also replaces ADR
0030's per-page owner pause with milestone acceptance while preserving ADR
0030's page-contract and evidence discipline.

### Progressive scope

Navigation and trusted server context progress through:

`platform -> organization -> series -> edition -> department/resource`

Scope is derived from the route and authorized record, never from a hidden form
field alone. Platform-wide destinations remain distinct from convention-owned
work. The platform administrator may inspect and administer ordinary records
under platform authority but receives no membership, participation,
registration, department position, shift, or public convention identity.
Restricted HR, legal, safety, medical, wellbeing, and credential-secret reads
retain their narrower purpose and reasoned or break-glass rules.

### Access transparency

Mounted management pages gain a shared effective-access header. It states the
operations available to the current viewer and summarizes the capability,
role, department, relationship, lifecycle, and exceptional-access sources that
make those operations possible. It is computed from authorization policy and
does not become a parallel page-ACL system. Named people are revealed only when
the viewer may already see the underlying relationship. An authorized
**Manage access** action changes the audited source assignment in context.

Department and resource constraints must be added to the authorization model
before department-owned mutation pages are mounted. An edition-wide capability
must not be presented as though it were department-scoped.

### Shared primitives, departmental projections

Departments receive filtered workflows over shared records rather than
separate mini-apps. The shared primitives are identity and participation,
departments and roles, typed applications and forms, venue spaces and
configurations, programme and schedule versions, tasks and shifts, assets and
movements, documents and acknowledgements, conversations and announcements,
finance evidence, audit, and integration events.

A record keeps one stable identity while different departments receive
purpose-minimized layers. For example, one programme item may connect its
public description, room turnover plan, Stage Tech rider, Logistics movement,
Security note, staffing demand, document policy, and public API rendition
without duplicating the event across unrelated applications.

### API and command parity

HTML and API adapters call the same application services. Privileged mutations
must validate trusted scope, authorization, lifecycle, and field policy inside
a transaction; append human-readable audit evidence; and emit an outbox event
when downstream consumers may care. Direct Django-admin saves are not a
production mutation path for audited domain operations.

Public and third-party clients consume explicit versioned projections rather
than module tables. Seasonal frontends may change independently while the
domain and API contracts remain stable.

### Reference data

The repository may ship an independently authored fictional organization
template containing Department names, hierarchy, generic positions,
application-type templates, and example policies. Tests, examples,
screenshots, and demo fixtures use synthetic people only. Public rosters are
not scraped into accounts or fixtures.

## Consequences

- The running product becomes understandable through complete journeys while
  retaining small, reviewable page contracts.
- Pages 1 through 4 are kept, not redesigned or replaced by preserved UI.
- The edition workspace spine is a dependency for every edition-owned feature
  and therefore precedes timetable, logistics, or document pages.
- Authorization scope v2 is a prerequisite for safe department tools and the
  effective-access header's full explanation.
- Programme, venue, schedule, generic applications, knowledge, logistics, and
  conversations require new modules; passing tests in preserved modules do not
  imply that these capabilities exist.
- A capability ledger must distinguish `Mounted`, `API-only`,
  `Preserved/unmounted`, `Partial`, `Absent`, and `Deployment-gated` states.
- Production readiness remains a release decision backed by infrastructure,
  privacy, security, recovery, load, and operational evidence. A broad feature
  list is not itself a production claim.

## Alternatives considered

### Merge the legacy branches

Rejected. They have unrelated histories and incompatible tenant, identity,
authorization, migration, and model boundaries. A merge would maximize code
volume while reducing safety and comprehension.

### Restore the complete pre-reset browser interface

Rejected. It would immediately expose many individually useful workflows, but
would also restore the incoherent dual experience that caused the controlled
rebuild.

### Continue one page followed by a mandatory pause

Rejected as the sole cadence. It is useful for uncertain visual design, but
too slow for dependency chains that have no value until several pages work
together. Milestones retain page-level evidence and owner review.

### Build a separate frontend for every department

Rejected. It would reproduce the current fragmentation and invite duplicated
permissions, records, and histories. Department-specific needs become scoped
views and layers over shared domain objects.

### Replace specialized products all at once

Rejected. Maru first becomes the authoritative record and uses adapters for
payments, email, messaging, accommodation, and other services where replacement
would add risk without proving the core convention workflow.

## Requirements affected

- IDN-012
- HR-006 through HR-010
- SCH-001 through SCH-010
- UX-001 through UX-020
- REG-001, REG-002, REG-022, REG-023
- PRG-001 through PRG-007
- VEN-001, VEN-002, VEN-008
- LOG-001 through LOG-008
- KNO-001 through KNO-009
- OPS-001 through OPS-008
- INT-001, INT-002, INT-006, INT-008
- NFR-001 through NFR-009
