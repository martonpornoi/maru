# Product requirements

Status: Baseline  
Last updated: 2026-08-15

This document defines stable product requirements. Identifiers are used by
architecture documents, implementation issues, tests, and release notes.

## Domain terminology

- **Platform account:** A person's global login and platform-level preferences.
- **Organization:** An independently governed organizer and tenant.
- **Convention series:** A recurring convention brand owned by an organization.
- **Event edition:** One independently configured occurrence, such as
  `MaruCon 2026`.
- **Participation:** A person's relationship with an event edition, possibly in
  several capacities.
- **Department:** An organizational unit scoped to an organization or edition.
- **Assignment:** A time-bounded responsibility, position, shift, or hosting
  commitment.
- **Archive:** A read-only-by-default historical edition and its durable records.

## Functional requirements

### Identity, tenancy, and participation history

- **IDN-001 — One platform account:** A person must be able to use one account
  across supported conventions without separate convention passwords.
- **IDN-002 — Tenant isolation:** An organization may access only data shared
  with or created for that organization. A global account must not create
  implicit cross-organizer data access.
- **IDN-003 — Multiple capacities:** A person may simultaneously be an attendee,
  volunteer, staff member, host, dealer assistant, guest, or other configured
  participant in one edition.
- **IDN-004 — Scoped authority:** Permissions must be expressible by
  organization, event edition, department, function, resource, and field.
- **IDN-005 — Delegation:** Authorized leads must be able to grant limited,
  expiring responsibility without granting broad administrator access. Root
  authority and role changes require independent approval and cannot outlive
  either controller's authority. Each controller's exact authority source must
  be retained immutably; expiry, revocation, or invalidation of a pinned source
  makes dependent current authority ineffective without silently rebinding to
  another source. Authorized revocation remains immediate.
- **IDN-006 — Purpose-partitioned person data:** Platform identity,
  organizer relationships, edition registration profiles, restricted
  operational contacts, and approved public renditions must remain distinct.
  Reusing a person's data across editions requires compatible purpose, notice,
  and an explicit user action.
- **IDN-007 — Verified identity lifecycle:** Capacity-holding public actions
  require a verified account unless an explicitly reviewed provisional policy
  applies. Verification, recovery, session inventory and revocation,
  privileged step-up, enumeration resistance, and abuse limits must use
  expiring, single-use evidence and produce user-visible security history.
- **IDN-008 — Scoped restrictions and appeal:** An organizer restriction must
  state its organization or edition scope, kind, effective period,
  attendee-safe explanation, authority, and operational consequences. It must
  remain separate from platform login state, support reasoned revocation and
  appeal, and never disclose one organizer's restriction to another.
- **IDN-009 — Human access sharing:** Authorized controllers must be able to
  review and manage access using human-readable people and role-group names.
  Adding or changing access must select an exact individual, immutable role
  version, tenant/edition scope, effective term, reason, and independent
  approver; removal must remain immediate and reasoned. Contextual sharing
  controls may recommend roles but must not create page-local ACLs, expose
  unauthorized identities, or grant beyond either controller's authority.
  Every authority-derived shell entry, tenant or edition name, selector,
  navigation link, queryset prefilter, and API projection must use the same
  current exact-lineage decision as its destination. A required but dormant,
  missing, or malformed lineage contract must reveal no organizer scope.
- **IDN-010 — Human login aliases:** A platform account may have one
  case-insensitively unique human login handle in addition to its normalized
  email. Local sign-in must accept either exact identifier without revealing
  which identifier exists, while account recovery and verified contact remain
  email based. Handles may contain Unicode, spaces, underscores, apostrophes,
  and slashes used by convention communities; leading/trailing whitespace,
  control characters, and identifiers that look like email addresses are not
  allowed.
- **IDN-011 — Non-participating platform administration:** Platform
  administrators must be explicitly classified independently of account age or
  record ordering. They may inventory and provision platform tenants and act as
  attributed operators, but must not be subjects of organization membership,
  convention capability or role grants, edition participation, registration,
  volunteer applications, onboarding requests, or workforce assignments.
  This is a database invariant: direct SQL and ORM bulk writes, concurrent
  subject creation, and later account-kind reclassification must fail without
  preventing the platform administrator from remaining an attributed actor,
  creator, reviewer, approver, or auditor.
  Platform oversight must not silently create any of those relationships, and
  restricted case access remains subject to SAF-004 rather than following from
  platform-administrator status.
- **IDN-012 — Organization representation:** Every organization must have an
  Executive Board as its accountable representation root before the
  organization can move from Draft to Active. Initial provisioning must be a
  reasoned platform operation that creates no platform-administrator
  membership, appointment, grant, participation, registration, or workforce
  relationship. Controllers must be exact existing active person accounts with
  verified email, must accept their own versioned invitations, and must remain
  eligible at activation. Activation requires at least two distinct accepted
  controllers, no unanswered controller invitation, current aggregate state,
  exact organization confirmation, and cross-approved assignments to one
  immutable root-role version; it atomically activates the representation,
  memberships, appointments, authority, and organization or changes nothing.
  Only active Executive Board authority and explicit platform oversight may
  modify organization properties. Appointment replacement, ending,
  suspension, and reactivation must be reasoned commands that preserve prior
  terms and immediate revocation rather than editable status fields. Existing
  non-Draft organizations without representation require explicit migration
  reconciliation and must never receive inferred real-person assignments.
  A reasoned platform emergency containment may start from any open Board
  invitation or term. Before globally deactivating the person and revoking
  sessions, it must atomically close every Invited, Accepted, or Active Board
  appointment for that account across organizations, end matching Board
  memberships, and revoke linked root assignments. Each affected Board may
  remain Active only with at least two eligible active controllers; otherwise
  its representation and organization must be Suspended and all local Board
  root authority ended. Historical activated-and-ended approvers remain valid
  provenance but never current authority. The representation is the
  organization governance anchor, not an edition Department, Position, generic
  group, or workforce assignment; a structure projection may place operational
  departments visually beneath it but must not mirror it into those records.
- **IDN-013 — Platform-issued account invitations:** An active platform
  administrator may reserve and invite a person account as an optional identity
  onboarding convenience, independently of public registration. The command
  must normalize and reserve an exact unique email and optional login handle,
  create only an inactive person account with an unusable password, and send a
  single-use, expiring acceptance challenge through a durable retryable effect.
  The recipient chooses their own policy-valid password and proves control of
  the invited address; no administrator-selected or shared production password
  is allowed. Reissue, revocation, expiry, delivery state, acceptance, and safe
  replay must be versioned and audited without persisting or emitting the raw
  bearer secret. An invitation must never overwrite or disclose an existing
  identity and must create no organization membership, representation,
  authority, participation, registration, application, onboarding, workforce,
  or other convention relationship. Fixtures, tests, and tutorials may use
  only deterministic synthetic identities and reserved example domains.

### Multi-convention and event editions

- **EVT-001 — Multiple organizers:** One deployment must serve multiple
  independently governed organizations. An organization is the tenant and
  accountable organizer; it may own several convention series, each of which
  is a recurring public brand rather than a separate authority boundary.
- **EVT-002 — Edition as project:** Operational work must be scoped to an event
  edition. Each edition owns configuration, dates, venue data, registration,
  programme, staffing, communications, and reports.
- **EVT-003 — Inheritance:** A new edition may copy selected configuration,
  forms, roles, schedule templates, products, and documents from a prior edition
  or an approved versioned template without sharing mutable records. Imported
  configuration must retain provenance and require target-edition review before
  activation.
- **EVT-004 — Independent lifecycle:** Editions must move independently through
  draft, preparation, ready, live, closing, archived, and cancelled states.
  Authorized leaders must be able to review the current state, valid next
  states, and consequences in embedded Convention work; every transition
  requires a reason and terminal transitions require explicit confirmation.
- **EVT-005 — Time and locale:** Each organization must define searchable,
  code-backed country, default-language, and time-zone suggestions, and each
  edition must define its authoritative time zone, languages, currencies, date
  formats, and local policy configuration. Persist IANA time-zone identifiers,
  ISO language/country codes, and currency codes rather than display labels;
  show human-readable names and UTC/DST offsets at data-entry boundaries.

### Archival history

- **ARC-001 — Personal history:** People must be able to view their historical
  participation, including attendance level, host contributions, volunteer
  assignments, completed shifts, staff positions, dealer involvement, and other
  explicitly retained achievements.
- **ARC-002 — Historical meaning:** Archived records must preserve the labels,
  edition names, role names, and relevant status snapshots as they existed at
  the time. Later renaming must not rewrite history.
- **ARC-003 — Read-only archive:** An archived edition is immutable by default.
  Corrections require explicit authority, a reason, and an audit entry.
- **ARC-004 — Visibility:** Personal, organizer-only, and public historical
  information must remain distinct. Users control optional public history.
- **ARC-005 — Retention:** Archival value does not override retention rules.
  Operational history should be retained without keeping unnecessary legal,
  medical, HR, identity-document, or payment data.

### Activity, audit, and engagement

- **AUD-001 — Administrative audit:** Sensitive reads and privileged mutations
  must record actor, action, scope, target, time, source, and outcome.
- **AUD-002 — User-visible security history:** Users must be able to review
  important account events such as sign-ins, credential changes, consent
  changes, exports, and account-linking actions.
- **AUD-003 — Operational timeline:** Authorized staff must be able to see a
  meaningful timeline for registrations, applications, orders, assignments,
  cases, messages, and publication actions.
- **AUD-004 — Purpose limitation:** Engagement analytics must be separated from
  security audit data, minimized, documented, and disabled where no justified
  purpose exists.
- **AUD-005 — Tamper evidence:** Audit records must not be editable through
  normal application interfaces and must have integrity monitoring.

### Internal communication

- **MSG-001 — Platform inbox:** Users and authorized teams must have a searchable
  platform inbox that replaces scattered operational Telegram groups and email
  chains.
- **MSG-002 — Conversation scope:** Threads may belong to an edition,
  department, application, registration, incident, shift, programme item, or
  another domain object.
- **MSG-003 — Team inboxes:** Departments must support shared queues, assignment,
  status, priority, internal notes, followers, and service expectations.
- **MSG-004 — Audience controls:** Conversations, notes, and attachments must
  enforce participant, department, tenant, and sensitivity boundaries.
- **MSG-005 — Delivery preferences:** Users may receive notifications through
  configured channels while the canonical message and read state remain inside
  Maru.
- **MSG-006 — Search and continuity:** Authorized replacements must be able to
  understand prior decisions without access to former staff members' personal
  accounts.
- **MSG-007 — Registration service notifications:** Registration, payment,
  wait-list, restriction, and deadline events must create a canonical,
  localized inbox message before optional email delivery. Delivery must be
  idempotent, retryable, preference-aware without treating operational mail as
  marketing, and expose permanent failure to an owned staff queue.

### Central announcements and external publishing

- **ANN-001 — Compose once:** Staff must be able to create one canonical
  announcement and prepare channel-specific variants.
- **ANN-002 — Supported destinations:** Connectors should support the convention
  website, platform inbox, email, push notifications, X, Bluesky, Telegram,
  Barq, and future channels where supported APIs and organizer credentials are
  available.
- **ANN-003 — Workflow:** Announcements must support drafts, previews,
  localization, approvals, scheduling, immediate emergency publication, and
  cancellation.
- **ANN-004 — Delivery state:** Each channel delivery must record attempts,
  remote identifiers, success, failure, retry state, and the published form.
- **ANN-005 — Adapter isolation:** External networks must be adapters. Their
  outages, limits, removals, or API changes must not damage the canonical
  announcement.
- **ANN-006 — Audience targeting:** Internal announcements may target edition,
  registration tier, role, department, venue, shift, or saved audience, subject
  to authorization and communication preferences.

### HR, staffing, and onboarding

- **HR-001 — Configurable pipeline:** HR must be able to configure application,
  review, interview, offer, acceptance, onboarding, active, inactive, and
  offboarding stages.
- **HR-002 — Checklists:** Onboarding must support role-specific tasks,
  agreements, policy acknowledgements, training, certifications, system access,
  equipment, and accountable owners.
- **HR-003 — Organization history:** Authorized HR users must see prior
  organization roles and relevant eligibility without exposing unrelated
  convention data.
- **HR-004 — Least-privilege provisioning:** Onboarding and offboarding must
  create, review, expire, and revoke access predictably.
- **HR-005 — Progress and reminders:** Candidates, staff members, leads, and HR
  must see appropriate progress, blockers, deadlines, and reminders.
- **HR-006 — Sensitive separation:** HR cases, accommodations, conduct matters,
  and ordinary staffing records must have separate access policies.
- **HR-007 — Positions and published opportunities:** Editions must support
  reusable position templates, edition-owned departments and reporting
  hierarchy, explicit headcount, several people in one position where allowed,
  and one application opportunity per position. A published opportunity must
  remain discoverable when filled unless an organizer explicitly withdraws it,
  while clearly stating whether new applications are accepted.
- **HR-008 — Reviewed onboarding evidence:** An organizer may request a
  versioned agreement or onboarding document from a named person. The source
  file must remain private, type/size/malware checked, separately reviewed with
  a reason, and retained under an approved HR policy. Assignment or access may
  depend only on an approved current requirement; an uploaded file by itself
  grants nothing.
- **HR-009 — Shift demand and commitment lifecycle:** Edition staffing must
  distinguish required headcount, suitable open work, a person's claim,
  organizer confirmation, removal, completion, and a locked coverage plan.
  Capacity and overlap checks must be transactional; volunteers see their own
  commitment state without gaining access to other volunteers' private records.
  A published Shift must retain its Position, time, place, briefing, break,
  rest, and supervision expectation rather than changing silently after a
  claim. Suitability must use current explicit Position and Availability facts;
  a claim is not confirmation. Confirmation must be independent from the
  claimant and recheck current qualification, Availability version, overlap,
  rest, and capacity. Locking must reject unconfirmed or stale coverage and
  require an explicit reasoned choice for underfill. A person may withdraw from
  open planning without supplying a free-text explanation; organizer removal,
  demand lifecycle changes, and accepted underfill require directly
  inspectable rationale. Completion may occur only after the locked work ends,
  cancellation must retain truthful removal evidence, and unfinished demand
  must prevent closure of its Position. Browser and API adapters must share
  strict optimistic idempotent commands, bounded complete projections,
  tenant/person isolation, minimized audit/event evidence, and database-owned
  capacity, interval, lifecycle, receipt, and dependency enforcement.
- **HR-010 — Workforce structure projection:** Authorized edition participants
  must be able to understand the department and reporting hierarchy on a
  separate, responsive page. The projection must support nested departments,
  several leads or deputies, multi-holder positions, and one person holding
  positions in several departments. It exposes only public operational names,
  position labels, and reporting relationships; email, HR evidence, account
  state, technical identifiers, and unrelated organizer data remain excluded.
- **HR-011 — Versioned edition structure management:** An authorized edition
  structure manager must be able to create, rename, describe, order, reparent,
  retire, and safely remove Departments through audited, tenant- and
  edition-scoped application services shared by HTML and API clients. Every
  change must use optimistic concurrency, strict inputs, exact parent-chain
  validation, cycle prevention, and non-cascading retention rules. Maru must
  provide an immutable, versioned, repository-owned fictional MaruCon starter
  whose edition-owned copy places Convention Coordination above the
  independently authored operational Department taxonomy and can diverge
  without changing its source. The browser must keep sibling
  ordering server-owned: create and reparent append automatically, ordinary
  edits preserve a unique current position, and an edited duplicate position
  is repaired under the aggregate lock. Strict API integrations may continue
  to provide an explicit bounded presentation order.
  It may be applied only to an empty Draft or Preparing edition, retains exact
  source-version and retry provenance, and creates no account, membership,
  representation, participation, Position, assignment, role, capability, or
  registration relationship. The Executive Board remains the separate
  OrganizationRepresentation governance anchor and may be composed visually
  above Convention Coordination without becoming a Department or an
  authority-inheritance edge. Retirement preserves immutable typed-resource
  bindings and closed
  authority as historical evidence: those rows do not by themselves block
  retirement, but they continue to block hard deletion, and no new binding or
  current authority may target a retired Department. Retirement must first end
  every active assignment whose term has not ended and every unclosed authority
  term that is effective now or scheduled for later. Position management is
  governed separately by HR-012; assignment activation remains subject to its
  immutable role-bundle, typed-resource, dual-control, lifecycle, and recovery
  requirements.
- **HR-012 — Versioned Position and opportunity management:** An authorized
  edition structure manager must be able to create, maintain, publish, and
  close Positions through strict tenant- and edition-scoped HTML and API
  workflows backed by the same application services. Creation must select one
  published organization-owned Position template with historical role-bundle
  provenance, one active Department, an optional acyclic same-edition reporting
  Position, an explicit purpose, and bounded headcount. It must atomically
  create the Position, its private draft volunteer opportunity, and its exact
  typed resource binding. The separately governed legacy authority-recovery
  bootstrap may relax only the historical-provenance lookup for its exact first
  Convention Chair while retaining the same command evidence and exposing no
  browser or API override. Organization, edition, Department, template, role
  bundle, code, capacity mapping, creator, and creation version are immutable;
  title, purpose, headcount, and reporting line may change only while the
  Position is current. Publishing the paired opportunity may open a planned
  Position but must never create an application, assignment, participation, or
  access grant. Every mutation must advance the shared edition structure
  aggregate once and retain actor, reason, changed fields, audit, domain event,
  and outbox evidence; the reason must be directly inspectable in the Position
  workflow. Closure requires exact-title confirmation, is one-way, preserves
  all history, closes any nonfinal opportunity, and must fail while proposed or
  active assignments, current direct reports, unfinished Shift demand, or
  current/future scoped authority depend on the Position. Generic Position and opportunity model
  forms remain inspection-only once this workflow is mounted. An internally
  consistent legacy Position may begin governed history at its first real
  change without inventing a creation version, actor, or receipt.
- **HR-013 — Governed Position assignment lifecycle:** An authorized exact-
  edition manager must be able to propose one active known person for a current
  Position, inspect that person's Position-specific onboarding readiness, and
  retain a reason and effective interval without granting authority. The known-
  person selector must be bounded to an existing organization, edition,
  application, onboarding, or Workforce relationship and must not become a
  general account directory. A proposal reserves approved headcount but creates
  no participation, RoleAssignment, capability, or schedule commitment.
  Approval or rejection requires a different currently authorized controller,
  fresh step-up authentication, a reason, and the exact current assignment
  version. Approval must recheck lifecycle, headcount, immutable RoleBundle
  provenance, current proposer and approver authority, candidate identity, and
  every required onboarding document under one transaction, then activate the
  linked role and participation capacities. Ending an active assignment
  requires fresh step-up authentication and revocation authority, retains its
  reason, revokes the linked role, and completes only capacities no longer
  needed by another active assignment. HTML and API adapters must share strict,
  idempotent commands with authorization before input parsing, immutable
  receipts, audit and registered domain-event evidence, optimistic assignment
  versions, and stopped-writer database enforcement. The assigned person may
  see their own Position, Department, state, interval, and available next
  actions, but not organizer reasons, controller identities, other candidates,
  or other people's assignments.
- **HR-014 — Person-owned edition availability:** A person with a proposed or
  active Position assignment must be able to keep a private draft and
  deliberately share their complete workable time windows for that exact
  edition. No assignment, application, registration answer, profile value, or
  organizer action may imply or overwrite availability. A submitted plan with
  no windows means explicitly not available; no submitted plan means unknown.
  Each window is an aware, non-overlapping interval inside the edition's local
  calendar horizon and is either available or preferred. Browser entry must
  use the edition's IANA time zone and reject ambiguous or nonexistent local
  minutes; API entry must carry an explicit offset. The owner may replace the
  complete plan optimistically, save it as a private draft, share it, or
  withdraw it. Withdrawal must remove current exact windows immediately while
  retaining only minimized command evidence. An independently capability-
  authorized organizer may see only open-assignment people, operational
  Position labels, the shared consequence, and submitted windows; draft
  content, notes, prior windows, unrelated people, and private HR data remain
  excluded. Organizer reads require a minimized sensitive-read audit before
  disclosure. HTML and API adapters must share strict idempotent commands,
  immutable receipts, audit and registered domain-event evidence, optimistic
  plan versions, tenant and edition isolation, bounded complete projections,
  and database enforcement. Exact windows are C2 current operational data;
  their post-edition disposal period must come from an approved organization
  retention policy rather than a code constant.

### Programme, shifts, and timetable planning

- **SCH-001 — Shared planning model:** Programme sessions, shifts, room
  availability, venue restrictions, people, resources, rehearsals, and
  dependencies must participate in one conflict-aware planning model.
- **SCH-002 — Multiple views:** The same source data must support attendee,
  participant, volunteer, department, venue, room, person, resource,
  cross-department, review, run-of-show, digital signage, and convention-book
  views.
- **SCH-003 — Decision support:** Planning must surface conflicts, missing
  qualifications, understaffing, excessive hours, unavailable people, travel or
  turnaround constraints, dependencies, and unpublished changes.
- **SCH-004 — Drafts and publication:** Schedules must support draft versions,
  review, comparison, approval, publication, and revision history.
- **SCH-005 — Personal decision view:** Volunteers must be able to compare
  suitable open shifts against their qualifications, interests, existing
  commitments, break needs, and preferred availability.
- **SCH-006 — Edition outputs:** Approved timetable data must feed public APIs,
  personal calendars, signage, staff briefings, exports, and print layouts.
- **SCH-007 — Human override:** Authorized planners may override warnings with a
  recorded reason; hard safety or authorization constraints cannot be silently
  bypassed.
- **SCH-008 — Service days, layers, groups, and projections:** Editions must
  define service-day windows and scheduling precision, order and lock
  visibility layers, group related or recurring items with explicit sequence,
  and derive interactive, API, print, signage, person, room, and staff
  projections from the same approved schedule version.
- **SCH-009 — Three-phase work envelopes:** Every scheduled programme or
  operational item must distinguish preparation, effective delivery, and
  teardown intervals, with an invariant ordering of preparation start,
  effective start, effective end, and teardown end. Effective delivery in a
  selected space conflicts with every room-occupying phase of another item.
  The preceding item's teardown may overlap the following item's preparation
  in the same space as one visible turnover window; person, qualification,
  exclusive-equipment, composite-space, and hard-availability conflicts remain
  independently enforced. Every move or accepted warning records the old and
  new envelope, actor, reason where required, and schedule version.
- **SCH-010 — Access-controlled planning layers:** A schedule item must support
  separately authorized layers for released programme copy, room operations,
  setup and teardown work, technical riders and cues, security and crowd
  planning, logistics, staffing demand, multimedia, accessibility delivery,
  and departmental discussion. Layers share the item's stable identity and
  timing but retain their own visibility, edit authority, ownership, history,
  and publication rules. A comment or shift layer must not silently alter the
  approved public schedule.

### Querying, reporting, and export

- **QRY-001 — Search-first operations:** IT, Front Desk, HR, Registration, and
  other departments must have fast global and module-specific search.
- **QRY-002 — Safe query builder:** Authorized users must be able to filter,
  sort, group, aggregate, save, share, and rerun queries without writing SQL.
- **QRY-003 — Field catalog:** Queryable fields must have human-readable names,
  descriptions, formats, sensitivity classifications, and permission rules.
- **QRY-004 — Role-oriented defaults:** The platform must ship useful saved
  views and dashboards for common department questions. The registration
  baseline must include a confirmed-attendance country breakdown and minimized
  badge-preparation view.
- **QRY-005 — Export formats:** Meaningful tabular data should be exportable as
  CSV and XLSX. Stable printable artifacts should be exportable as PDF. Calendar
  data should support iCalendar where appropriate.
- **QRY-006 — Asynchronous exports:** Large exports must run as background jobs
  with progress, expiration, access checks at execution and download time, and
  an audit record.
- **QRY-007 — Sensitive output controls:** Sensitive exports must support
  minimization, watermarking or classification, expiry, and restricted sharing.
- **QRY-008 — Reproducibility:** Reports must record filters, edition scope,
  generation time, requester, data version where practical, and template
  version.

### Staff and administration experience

- **UX-001 — Purpose-built console:** Django admin may support early data
  management, but recurring staff workflows must use a role-oriented operations
  console.
- **UX-002 — Relevant home:** A user's home view must prioritize their assigned
  work, deadlines, unread conversations, schedule, warnings, and recent items.
- **UX-003 — Low interaction cost:** Common tasks must support direct search,
  bulk actions, keyboard operation, sensible defaults, and preserved context.
- **UX-004 — Responsive feedback:** Navigation and routine operations must feel
  immediate. Performance budgets and representative datasets must be tested in
  CI and release validation.
- **UX-005 — Error recovery:** Destructive or high-impact actions require clear
  confirmation, and reversible actions should provide undo or recovery.
- **UX-006 — Progressive disclosure:** Simple tasks must remain simple while
  advanced controls are available when needed.
- **UX-007 — Accessibility:** Public and staff interfaces must target WCAG 2.2
  AA and remain usable with keyboard and assistive technology.
- **UX-008 — Consistency:** Statuses, filters, tables, forms, timelines, and
  permission-denied behavior must be consistent across modules.
- **UX-009 — Edition working context:** Staff and bootstrap-administration
  surfaces must preserve one explicitly selected event edition and scope
  edition-owned lists, details, counts, and choices to it by default.
  Platform-wide records must be clearly distinguished. Cross-edition reuse must
  be an explicit source-selection action, remain within authorized tenant
  scope, and create independent edition-owned records.
- **UX-010 — Platform identity and seasonal theming:** Maru's own operational
  surfaces must use one documented, accessible platform identity and asset
  source. Convention-owned public clients may replace layout, animation,
  artwork, and annual theme without forking domain rules. Semantic state must
  remain readable without color, and organizer assets remain separately owned,
  governed, and withdrawable.
- **UX-011 — Contextual bootstrap guidance:** Convention work's Setup guide
  must give new organizers one concise, ordered convention-creation path while
  preserving the complete administration directory for later changes. The
  setup path must distinguish organizer-, series-, edition-, and ongoing
  tasks, respect model permissions, and must not imply that navigation order
  grants authority or proves setup completion. It must not occupy the global
  administration header or repeat on every record page. For a new Draft
  organization it must direct the operator to Representation & access's explicit Executive
  Board handoff rather than silently creating organization, edition, workforce,
  or participation authority. A legacy non-Draft organization without
  representation requires a separately approved reconciliation procedure. The
  former broad browser ceremony and management API are retired; only the
  operator command and underlying service remain recovery evidence, not a
  second normal setup workflow.
- **UX-012 — Unified management console:** Recurring operations, setup
  navigation, access management, forms, and specialist records must appear as
  sections of the original `/admin/` shell with one collapsible,
  permission-aware global navigation. API-backed workflows may be embedded
  inside that shell, but must not render a second global menu or a visually
  competing application shell. Embedded inner pages use the same
  record-oriented title, help, module, form, table, button, spacing, and
  responsive patterns as specialist record pages. Each operation
  has one canonical workflow; Django records remain part of the same product
  rather than a competing console. User-facing pages prefer
  names, slugs, references, and labels over UUIDs, retaining technical
  identifiers only where audit, integration, or support work genuinely needs
  them. Command-owned evidence workflows must derive trusted scope, actor, and
  server time rather than asking operators to copy technical IDs or manually
  author audit timestamps. `/admin/` is the canonical authenticated home;
  specialist records and embedded convention workflows remain below the same
  URL hierarchy. Former `/manage/`, `/staff/`, and `/admin/records/` entry
  points must not host or redirect to alternate interfaces.
- **UX-013 — Controlled experience rebuild:** Maru may enter an explicit
  page-by-page rebuild state without discarding its tested domain, security,
  audit, migration, or API foundation. In that state the default browser
  experience exposes only local Sign in and one authenticated empty
  administration home; prior administration, specialist-record, registration,
  volunteer, and convention-work pages are not mounted. Health and versioned
  API contracts remain available for backend verification. Reintroducing a
  page requires an agreed purpose, navigation place, minimum information,
  authorization boundary, empty/loading/success/denied/failure behavior,
  desktop and narrow evidence, automated tests, and updated documentation.
  No later page may be treated as current merely because its preserved code or
  API still exists. Leaving the controlled state requires an accepted decision,
  collision-safe canonical routes, one coherent navigation grammar, current
  authorization evidence, and fresh verification of every remounted surface.
- **UX-014 — Platform administration home:** The first page restored after the
  controlled baseline must provide a platform-wide organization inventory at
  `/admin/platform/organizations/`, inside the canonical `/admin/` shell, and
  make it available only to active platform administrators. It must explain
  that platform access is not convention participation, show an honest empty
  state when no organization exists, show only organization identity,
  lifecycle, series count, and edition count when records exist, and fail
  read-only with a safe error when the inventory is unavailable. It must not
  introduce a convention selector, setup strip, unfinished link, or
  convention-owned data.
- **UX-015 — Minimal organization creation:** Create organization of the controlled rebuild
  must let an active platform administrator create a draft organization from
  its name alone. Maru generates a collision-safe stable slug and applies
  code-owned locale defaults. Creation is atomic and audited and must not create
  organization membership, convention authority, an Executive Board, a series,
  an edition, or participation. Validation remains on the form, a successful
  creation returns to the organization inventory, and database failure leaves
  no partial organization. Name remains the only required operator-supplied
  value even when Create organization also accepts the optional complete profile in UX-016.
- **UX-016 — Complete organization setup and navigation:** Platform administration home and Create organization
  must share a persistent Platform administration side navigation containing
  **Organizations** and **+ Add**, with the current destination identified.
  Create organization must let the platform administrator complete public identity, legal
  identity and address, representative and registration references, contact
  channels, additional imprint wording, primary country, default languages,
  and default time zone during initial creation. Only organization name is
  required; omitted properties keep safe blank or code-owned defaults. The page
  must make Draft status and the no-governance/no-convention boundary explicit.
  Legal/imprint details are organization-owned C1 data, are not published merely
  by entering them, and must be audited by field name without copying their
  values into audit metadata.
- **UX-017 — Organization record management:** The organization inventory must
  link each organization name to one record page, and the shared Platform
  administration navigation must present **Organizations** and a compact
  adjacent **+ Add** action on one row. An active platform administrator may
  update the organization's complete profile without changing its stable slug
  or lifecycle. A deletion action must require exact-name confirmation and an
  explicit acknowledgement, be separately posted and audited, and succeed only
  for a Draft organization that has no related series, editions, membership,
  authority, participation, registration, workforce, communication, or other
  protected records. Validation or persistence failure must retain the record
  and show a safe retry state. Once IDN-012 governance is introduced, active
  Executive Board authority must receive the same property-editing path without
  granting the platform administrator convention participation.
- **UX-018 — Organization-scoped convention-series creation:** An organization
  record must show its convention series and a contextual action to create one
  beneath that organization. Create convention series must require only the recurring public
  brand name; description, website, public contact email, and initial
  active/inactive availability are optional or safely defaulted. The parent
  organization and collision-safe bounded slug are code-owned. Creation must
  repeat active platform-administrator authorization, lock and verify the
  organization is not Closed, validate the complete series, and atomically
  append value-minimized audit evidence. It must not create an edition,
  membership, authority, participation, registration, governance, or workforce
  record. Denied, unknown-parent, validation, persistence, and audit failures
  must disclose no cross-tenant data and leave no partial series.
- **UX-019 — Progressive, context-scoped administration navigation:** Every
  mounted administration page must be reachable from the shared side menu at
  the scope where it belongs. Platform-wide destinations remain visible
  globally; organization-owned destinations appear only after an organization
  is selected and name that organization as their context. A creation action
  sits beside its corresponding destination, each current page has exactly one
  current navigation action, and every action has an unambiguous accessible
  name. The desktop shell must align the menu near the viewport edge using
  ordinary page padding rather than centering the whole administration grid;
  narrow layouts must stack without horizontal overflow. Navigation context
  never grants authority, lists another tenant's records, or accepts or
  reparents tenant ownership.
- **UX-020 — Effective-access header:** Every mounted management record and
  workflow must show a concise, computed summary of who may view, edit,
  comment, approve, or administer it at the current scope. The explanation is
  derived from platform authority, capability grants, role assignments,
  department relationships, resource ownership, field ceilings, lifecycle,
  and exceptional access; it is not a manually maintained page ACL label.
  Named people are shown only to viewers already authorized to see that
  relationship. An authorized **Manage access** action edits the underlying
  audited assignments in context, while denied users receive an explanation
  that does not disclose protected principals. Platform administration does
  not imply convention participation, and restricted-case access continues to
  require its separate reasoned or break-glass policy. The compact summary
  belongs directly after the page heading, stays understandable while
  collapsed, and expands in place for the permitted actions and authority
  source; it must not become duplicated global chrome or a second page title.
- **UX-021 — Convention-series record:** Every convention series listed on its
  organization record must link to one scoped record page. The page shows
  stable organization and slug identity, active/inactive availability, the
  editable public brand profile, an edition inventory, a contextual **+ Add**
  edition action when creation is allowed, and a value-minimized human activity
  history. Saving uses an expected profile version, locks and revalidates the
  exact organization-owned series, changes no ownership or slug, writes only
  actual fields, and atomically appends audit and domain-event evidence. The
  page does not implement series transfer, destructive deletion, publication,
  governance, participation, registration, or workforce side effects.
- **UX-022 — Series-scoped edition creation:** A selected active convention
  series beneath a non-Closed organization must provide one edition-creation
  page. The organization and series are trusted route scope; name, start date,
  end date, time zone, languages, and currencies are bounded and validated,
  with locale defaults inherited visibly from the organization. Maru creates a
  collision-safe slug, Draft lifecycle, aggregate version, actor attribution,
  idempotency receipt, audit event, and minimized domain event in one
  transaction. The browser carries a hidden UUID retry key; the API requires a
  UUID `Idempotency-Key` request header and rejects that key in JSON. A retry
  with the same actor, scope, key, and normalized payload
  returns the first edition; reuse with different input fails. Creation grants
  no membership, representation, authority, participation, registration,
  application, department, position, shift, or venue selection.
- **UX-023 — Edition record and workspace context:** A created edition must
  redirect to a scoped record page reachable through organization, series, and
  edition navigation. The page shows lifecycle, stable identity, dates, locale,
  currencies, parent records, access summary, latest meaningful update, and
  human activity. Draft and Preparing profile fields may be updated through an
  expected-aggregate-version command; Ready, Live, Closing, Archived, and Cancelled
  profiles are read-only until an explicit lifecycle/change-control workflow
  permits otherwise. Saving cannot directly change lifecycle, slug, parent,
  authority, participation, registration, or operational configuration. The
  selected route establishes display context only and never grants access.
- **UX-024 — Representation and access handoff:** A selected organization must
  expose one **Representation & access** page in the shared administration
  navigation. It must explain the purpose and current state of the Executive
  Board, show platform oversight separately from convention authority, and
  guide the initial sequence of provision, exact-account invitation,
  invitee-owned accept or decline, and two-person activation. Managers may see
  bounded appointment identity and exact email only inside their authorized
  organization; an invitee may see and answer only their own open invitation;
  other viewers receive no principal or cross-tenant disclosure. Provision,
  invitation, response, and activation are separate POST actions with closed
  input contracts, safe replay behavior, row locking, positive expected
  versions where state can become stale, value-minimized audit and outbox
  evidence, and atomic rollback. Activation must require exact organization
  confirmation and display that it will move the organization from Draft to
  Active. The page must not create a Django Group, department, edition
  participation, registration, or workforce position, and its initial root
  summary must not be presented as the complete department/resource/field
  effective-access editor.
- **UX-025 — Edition organization-structure page:** A selected edition must
  expose one **Organization structure** destination beneath that edition in the
  shared administration navigation. Its responsive hierarchy places the
  minimized Executive Board governance anchor above the edition-owned Helper
  Board and nested Departments, while clearly distinguishing representation,
  operational reporting, and software authority. The header and navigation
  must derive view and edit explanations from the exact current policy
  decision; platform oversight remains non-participating, department-only
  authority does not reveal the complete edition tree, and hidden people or
  tenant names are never disclosed. The first management slice applies the
  exact versioned built-in reference or edits Departments through closed,
  reasoned, expected-version forms and the same strict API services. Template
  application requires a retry key and exact edition confirmation; hard delete
  requires exact department-name confirmation and proof that no child,
  Position, assignment, authority, resource binding, cross-module reference,
  or operational history depends on the record. Overflow, stale, denied,
  validation, protected, persistence, audit, and outbox failures must be
  explicit and leave no partial tree. Ready, Live, Closing, Archived, and
  Cancelled editions are read-only until a separately accepted structural
  change-control workflow permits otherwise.
- **UX-026 — Registration setup and account onboarding:** Registration setup and account onboarding must expose
  one edition-scoped **Registration** workspace in the shared `/admin/` shell
  and one platform-scoped **Accounts** inventory with an adjacent **Invite**
  action for active platform administrators. The registration workspace guides
  an authorized organizer from an explicit blank, published-template, or exact
  prior-edition source through target review, draft form and product setup,
  minor policy, profile extensions, activation, and current status without a
  second application shell or global Quick Start. Every page shows truthful
  lifecycle, provenance, validation, downstream effects, and computed
  effective-access explanations; denied, empty, dependency-failure, stale,
  overflow, replay, and delivery-failure states disclose no unauthorized
  tenant or person data. Browser and versioned API adapters use the same
  command/query contracts, and platform account onboarding remains visibly
  separate from convention participation and registration.

- **UX-027 — Coherent navigation and personal surface:** Once an organization,
  series, and edition are selected, every currently authorized destination
  must appear in one searchable, non-duplicated navigation list rather than a
  second hierarchy of folder-like scope menus. The selected context remains
  explicit in the header and route. An active person may pin only a stable,
  code-owned destination; every render must resolve and authorize the pin
  again, and a revoked, stale, malformed, deleted, or foreign target must
  disappear without disclosure. `/my/` is the canonical authenticated personal
  surface for registrations, payments, profile, applications, orders, and
  other self-owned relationships. It shares Maru's identity and navigation
  grammar without presenting an attendee as an administrator. Personal and
  administrative destinations remain separate surfaces with one explicit
  switch between them; neither surface may leak the other surface's pins or
  menu hierarchy. Pin controls are progressive customization rather than
  permanent row-level clutter.
- **UX-028 — Read-only access preview:** An authorized access manager may
  evaluate one exact existing person or one immutable role-bundle version at
  one resolved scope. Preview must not replace the request principal, create a
  session, issue authority, bypass step-up, execute a mutation, or change audit
  attribution. A persistent banner identifies the target, scope, mode, and
  evaluation time; protected details remain capped by the previewing actor's
  own disclosure authority. Starting a sensitive preview is audited, hidden or
  foreign targets fail without disclosure, and mutation endpoints always
  authorize the real principal independently of preview state.
- **UX-029 — Professional responsive management experience:** The canonical
  management shell must prioritize a small role- and context-relevant set of
  durable tasks while retaining every authorized specialist destination behind
  one progressively disclosed gateway and searchable registry. Search must use
  code-owned labels, descriptions, and stable task keywords rather than hidden
  record values. Search results must distinguish task matches from technical
  records and lead with the task count; technical records remain collapsed
  until requested. Creation commands belong beside their owning resource.
  Planned capabilities may have one truthful, non-interactive roadmap home but
  must not appear as dead links or imply availability. Common tasks must be
  reachable from the relevant home in no more than two navigation decisions
  without a direct URL. The shell and converted journeys must have no
  page-level horizontal overflow at 320, 390, 768, 958, 1,024, 1,280, or 1,920
  CSS pixels or at 200 percent zoom; only explicitly labelled data regions may
  scroll. Intermediate and narrow navigation must provide a labelled overlay
  drawer with backdrop, close control, `aria-expanded` and `aria-controls`,
  Escape-to-close, focus containment and return, and background scroll lock.
  While the drawer is open, background chrome and content must be inert and
  hidden from the accessibility tree. High-frequency narrow-screen record
  lists should become labelled cards when preserving row context is more useful
  than horizontal table scrolling. An embedded client must synchronize its
  selected organization/edition context with the host shell before releasing
  scoped record content and must not render a second competing selector.
  A detail drawer that blocks interaction with the page must expose labelled
  modal-dialog semantics, move focus inside, contain keyboard focus, close on
  Escape, isolate and scroll-lock the background, and return focus to its
  opener.
  Empty, populated, denied, validation, stale, dependency-failure, and success
  states require keyboard, automated-accessibility, and rendered evidence
  before broad browser acceptance is claimed.

### Registration, orders, and attendee service

- **REG-001 — Configurable registration:** Each edition must support
  versioned registration periods, capacities, eligibility, pricing, questions,
  agreements, waiting lists, and approval policies. An edition may start from a
  blank setup, a reviewed prior edition, or an approved template, but the
  resulting configuration is edition-owned and independently versioned.
  Sections, questions, and products must be addable, editable, reorderable, and
  removable while the owning configuration or template remains a draft.
  Active, published, submitted, and financially referenced records remain
  immutable or use explicit lifecycle commands.
- **REG-002 — Purpose-bound forms:** Conditional forms must disclose purpose
  and visibility, reuse only compatible data with the user's knowledge, and
  retain the exact submitted schema version.
- **REG-003 — Products and entitlements:** Products, variants, bundles, quotas,
  discounts, vouchers, memberships, donations, and non-financial entitlements
  must remain distinguishable.
- **REG-004 — Order lifecycle:** Orders must support reservations, expiry,
  payment attempts, changes, transfers, cancellation, partial or full refunds,
  disputes, and reconciliation without rewriting financial history.
- **REG-005 — Payment boundary:** Payment-card data must remain with compliant
  payment providers. Provider messages must be authenticated, idempotent, and
  reconciled against locally recorded intent.
- **REG-006 — Explainable eligibility:** Staff and attendees must be able to
  understand why an item, price, status, or action is or is not available,
  subject to fraud and security limits.
- **REG-007 — Attendee service view:** Authorized service staff must resolve
  identity and see a consolidated, purpose-limited view of registration,
  payment state, entitlements, credentials, fulfilment, and relevant contact.
- **REG-008 — Controlled exceptions:** Waivers, manual changes, complimentary
  items, overrides, and corrections require explicit capability, reason,
  relevant evidence, and an attendee-visible consequence where appropriate.
- **REG-009 — Check-in and fulfilment:** The platform must support check-in,
  credential issuance, badge printing, item handover, reprints, revocation, and
  reconciliation across online and authorized offline clients.
- **REG-010 — Capacity integrity:** Concurrent sales and allocation must not
  oversubscribe hard capacity. Holds, expiry, wait-list promotion, and manual
  overrides must be transactional and observable.
- **REG-011 — Public registration entry:** A person without an account must be
  able to discover an open edition, create one platform account, and submit its
  registration without entering a staff surface. Returning users must be able
  to choose among open editions and see which editions they already joined.
- **REG-012 — Edition registration profile:** Registration may collect
  edition-owned identity, contact, address, emergency-contact, character, and
  media fields only with field-level purpose, sensitivity, visibility, and
  retention notice. Optional public-attendance publication must be a separate
  edition consent, require confirmed admission, and expose only a minimized
  rendition with approved media. A country shown publicly must be entered for
  that purpose and must never be inferred or copied from the address field.
  Telephone entry must pair a recognizable country code, flag, and calling
  prefix with the local number, then store one validated canonical
  international value.
- **REG-013 — Profile sections and derived facts:** Organizers may group
  edition registration questions into ordered, versioned sections. Staff-owned
  facts such as volunteer department and special-ticket entitlement must be
  derived from their authoritative domain records rather than attendee
  self-assertion. Public and badge attendee-level labels must use those
  authoritative facts and must not disclose exact price or payment evidence.
- **REG-014 — Headless and reference clients:** Registration meaning,
  availability, prices, purposes, and lifecycle consequences must be available
  through versioned API contracts so a convention can replace its visual
  frontend without forking domain rules. A bundled form may demonstrate the
  contract, but every client command is revalidated by Maru.
- **REG-015 — Reviewed profile reuse and amendment:** An authenticated
  returning attendee may explicitly accept, change, or reject a clearly sourced
  prior-profile suggestion. Submission must create an independent edition
  snapshot; current-edition self-service changes must not mutate earlier
  profiles or the immutable registration submission. Edition publication
  consent must never be preselected from history.
- **REG-016 — Structured public profile and moderated media:** Pronouns must
  use a maintained vocabulary with conditional write-in, spoken languages must
  use interoperable codes with a configured maximum, and attendees may record
  multiple edition fursuits. New or changed public images must remain private
  until an authorized reasoned review; an exact approved file may be reused
  only by its owning account in compatible organizer scope. Public status
  styling must include readable labels and never rely on color alone.
- **REG-017 — Provider-backed payment evidence:** A paid reservation must use a
  locally recorded intent and a provider-hosted checkout. Browser return is
  never proof of payment; only an authenticated, replay-resistant, idempotent
  provider event may confirm money. Mismatch and uncertainty must enter an
  owned exception queue without silently changing admission.
- **REG-018 — Operational finance evidence:** Provider payments, refunds, fees,
  disputes, chargebacks, receipts, cancellations, and settlements must produce
  append-only, edition-scoped operational evidence. High-risk attendee-facing
  changes require separate proposal and approval. Maru's evidence is not a
  statutory general ledger.
- **REG-019 — Safe media and minor admission:** Public-profile images must be
  type, size, decode, malware, and safe-rendition checked before moderation or
  publication. An edition admitting minors must activate a versioned age and
  guardian policy; required consent blocks payment and confirmation until
  accepted.
- **REG-020 — Credential and closure integrity:** Confirmed admission may issue
  a revocable, minimized credential. Offline check-in must use signed,
  time-bounded device manifests and idempotent reconciliation. Archival must
  require reviewed readiness evidence, zero unresolved operational queues, an
  immutable closure manifest, and a current recovery reference.
- **REG-021 — Staff-assisted registration:** Authorized staff may create the
  same edition registration for an exact existing account, or explicitly
  create a new unverified account when the email has never belonged to one,
  outside public opening or product-sale hours only with a reason and separate
  actor/subject evidence. New-account creation requires an explicit display
  name and policy-valid temporary password, warns the staff actor, never
  overwrites an existing or inactive identity, and receives its own privileged
  audit event.
  The command must still use an active immutable configuration, validate
  answers, age policy, eligibility, price, currency, capacity, payment
  deadline, restrictions, and duplicate-registration rules. It may not mark a
  paid product paid, waive payment, or silently make an incomplete profile
  public.
- **REG-022 — Post-submission profile extensions:** An organizer may add
  versioned, edition-owned profile fields after registrations exist without
  changing the immutable submitted form or its schema snapshot. Every field
  defines type, purpose, classification, one reader audience (`self`, exact
  registration staff, one exact active Department/team, all confirmed
  attendees, or public), a separate writer policy (attendee, registration
  staff, or both), source provenance, review state,
  and retirement. Values are append-only revisions with actor, time, source,
  reason where staff acts, and audit evidence. Attendees can read and update
  only their visible permitted fields; authorized staff can update only fields
  permitted to staff in the exact tenant/edition scope. Staff-owned facts such
  as Infinity-ticket status remain authoritative entitlements rather than
  profile answers. Value changes use a per-registration/stable-key expected
  sequence and scope-bound idempotency key, append one immutable receipt with
  minimized audit/effect evidence, and preserve exact historical replay after
  later revisions. Current reads are bounded, policy-filtered, final-
  reauthorized, audited snapshots; broad service-summary or on-behalf
  authority does not imply staff access to extension values. Confirmed-attendee
  and public projections additionally require the subject's current edition-
  directory consent and confirmed/check-in state, expose only approved
  minimized definitions, and disappear immediately on withdrawal. Platform-
  administrator status alone never authorizes a profile-value read.
- **REG-023 — One registration, separate applications:** An account may have at
  most one attendee registration in an edition. Hosting a panel, performing,
  DJing, volunteering, operating a Maid Café service, submitting conbook or Art
  Show material, applying as a dealer, and similar contribution processes are
  separate typed applications and must not create duplicate registrations or
  overload the attendee form. An application may require an eligible
  registration and may create a programme item, allocation, assignment,
  artwork, document, or other typed record only through an explicit accepted
  transition. Application state alone grants no ticket, payment state,
  convention role, or access.
- **REG-024 — Governed registration setup:** Registration configuration,
  reusable template versions, sections, questions, products, ordering, minor
  policy, and post-submission profile-extension definitions must be changed
  only through purpose-built commands once the Registration setup and account onboarding writer migration is
  activated. Each command must resolve and lock the exact organization and
  edition, enforce lifecycle and exact capabilities, reject unknown or
  client-owned scope/evidence fields, require a positive expected aggregate
  version where state may be stale, and provide scope-bound idempotent replay.
  Successful tenant mutations atomically preserve source version and digest,
  append value-minimized audit evidence, and enqueue the minimized domain
  event or required downstream effect; failure changes nothing. Active or
  published definitions are immutable, later change creates a traceable new
  version, and value revisions remain append-only. Zero custom questions is a
  valid configuration because purpose-specific typed edition-profile fields
  remain independently available. An omitted import value may use a documented
  source/default, but an explicit invalid value such as capacity zero must be
  rejected rather than treated as omission. HTML, versioned APIs, fixtures,
  and internal tools must call the same application services.
  Direct model-admin, inline, fixture, or ORM writers may remain only during a
  documented additive migration with legacy-origin reconciliation, readiness
  evidence, a rollback fence, and an explicit final stage that makes those
  paths read-only or removes them; their temporary presence must never be
  described as the canonical workflow. Maru may ship an immutable, code-owned
  convention-registration starter catalog. An authorized organizer must
  explicitly select one exact starter version and copy it into an edition-owned
  draft; copied rows are independent, require review before activation, retain
  starter version/digest provenance, and never live-update when either the
  catalog or another organizer changes.

- **REG-025 — Paid tier replacement and governed capacity:** A confirmed
  attendee may replace their current admission product only through an
  explicit same-account upward offer that reserves target capacity and charges
  the exact positive difference between current configured prices. The source
  admission and entitlement remain effective until authenticated payment
  succeeds; success atomically swaps product, price evidence, and entitlement
  so exactly one admission remains. Expiry releases the target hold, and this
  path never permits transfer, downgrade, arbitrary repricing, or browser-return
  payment proof. Overall and product capacity are effective values derived from
  initial configuration plus append-only adjustments bounded by configured
  hard ceilings. Wait-list review selects the next configured number in strict
  FIFO order without operator-picked people, while every adjustment, offer,
  expiry, payment result, and exception records actor and time.
- **REG-026 — Edition catalog and owned orders:** Merchandise, convention
  support, charity support, donations, and scarce supporter offers must use an
  edition-owned catalog separate from admission products. Products and variants
  retain sale window, price snapshot, fulfilment, beneficiary, preorder, per-
  order limit, and finite-stock policy. A charity beneficiary must be a current
  confirmed edition selection. Finite availability is derived from append-only
  stock evidence and cannot exceed its hard ceiling; donation variants are
  stockless and limited-supporter variants cannot silently become unlimited or
  preorderable. An attendee owns one immutable order-line snapshot and locally
  recorded payment intent; only authenticated, idempotent provider evidence may
  mark it paid. Staff activity and attendee history expose purpose-limited
  projections without joining catalog orders to admission entitlements.

### Programme intake and curation

- **PRG-001 — Calls for participation:** Editions must define calls, tracks,
  formats, questions, deadlines, public fields, consent, and content policy.
- **PRG-002 — Collaborative proposals:** Submitters may invite co-hosts,
  retain drafts, receive requests, submit revisions, and control which profile
  information is proposed for publication.
- **PRG-003 — Structured review:** Review stages must support configurable
  rubrics, conflicts of interest, optional anonymization, independent scoring,
  discussion, moderation, and accountable decisions.
- **PRG-004 — Decision communication:** Accept, reject, wait-list, and revision
  decisions must use templates while preserving a canonical conversation and
  any required acknowledgement.
- **PRG-005 — Accepted-item advance:** Acceptance must create tracked work for
  public copy, host confirmation, technical needs, accessibility, media
  consent, schedule availability, files, and other configured readiness.
- **PRG-006 — Publication separation:** Private proposal and review data must
  remain separate from approved public programme data, even when derived from
  the same item.
- **PRG-007 — Delivery record:** Authorized teams may retain planned versus
  actual time, attendance observations, show report, recording or asset state,
  and host contribution under explicit retention policy.

### Governance, planning, and readiness

- **PLN-001 — Mandate and success:** An edition must record accountable
  leadership, mandate, objectives, measures, assumptions, constraints, and
  decision authority.
- **PLN-002 — Connected work:** Projects, milestones, tasks, dependencies,
  decisions, risks, issues, and change requests must link to the people,
  departments, budget, schedule, spaces, assets, and policies they affect.
- **PLN-003 — Ownership:** Work must have one accountable owner, optional
  contributors, deadline, state, priority, edition scope, and escalation path.
- **PLN-004 — Evidence-backed readiness:** Readiness must be calculated from
  owned criteria and current evidence, never from an unexplained percentage.
- **PLN-005 — Risk management:** Risks must record likelihood, impact,
  treatment, owner, review date, residual status, triggers, and linked
  contingency work.
- **PLN-006 — Decision record:** Material decisions must retain question,
  context, options, decider, rationale, date, consequences, and supersession.
- **PLN-007 — Change control:** Material scope, policy, budget, venue, schedule,
  or service changes must expose affected dependencies and required approval
  before taking effect.
- **PLN-008 — Handover:** Roles and departments must maintain structured
  handover state, unresolved commitments, recurring knowledge, and acceptance
  by a successor or accountable lead.

### Finance, procurement, contracts, and sponsorship

- **FIN-001 — Operational budgets:** Editions must support versioned budgets,
  cost centers, restricted funds, forecasts, commitments, actuals, variance,
  and responsible owners in edition currencies.
- **FIN-002 — Approval policy:** Purchase requests, orders, expenses,
  reimbursements, refunds, complimentary value, and write-offs must follow
  configurable amount- and scope-based authority.
- **FIN-003 — Procurement trail:** A procurement must connect need, quotes,
  selection rationale, vendor, contract, purchase authorization, delivery,
  acceptance, invoice, and dispute.
- **FIN-004 — Expense safety:** Reimbursement workflows must collect required
  evidence, protect bank and tax details, detect duplicates, communicate state,
  and export approved records.
- **FIN-005 — Contract obligations:** Contracts must expose owners, dates,
  deliverables, renewal or termination triggers, data obligations, insurance,
  and linked operational work without making all terms broadly visible.
- **FIN-006 — Sponsor fulfilment:** Sponsor agreements must map promised
  benefits to owners, deadlines, assets, approvals, delivery evidence, and
  post-event reporting.
- **FIN-007 — Reconciliation:** Registration, merchandise, dealer, charity,
  auction, cash, provider, and inventory activity must produce reconcilable
  operational ledgers and assigned exceptions.
- **FIN-008 — Accounting boundary:** Maru must integrate with or export to an
  authoritative accounting system and must not represent its operational
  records as a statutory general ledger.

### Venue, lodging, travel, and hospitality

- **VEN-001 — Venue model:** Editions must represent sites, buildings, rooms,
  zones, entrances, routes, capacities, access properties, service hours,
  contacts, and versioned floor-plan references.
- **VEN-002 — Space booking:** Programme, staff, commercial, guest, storage,
  catering, rehearsal, and private-use bookings must share availability and
  setup/teardown constraints.
- **VEN-003 — Accommodation inventory:** Hotel properties, room types, nights,
  accessible features, blocks, assignments, release dates, and provider
  references must be manageable without storing unnecessary guest data.
- **VEN-004 — Fair allocation:** Oversubscribed rooms or entitlements must
  support versioned allocation policy, eligibility, randomized or scored
  rounds, reproducible results, appeals, and controlled overrides.
- **VEN-005 — Room groups:** Attendees may form consent-based room groups or
  respond to organizer-supported room-share workflows without forced public
  disclosure of personal contact details.
- **VEN-006 — Travel and arrival:** Authorized hospitality teams must coordinate
  guest or crew itineraries, transfers, arrival windows, accessibility needs,
  contacts, and changes with field-level restrictions.
- **VEN-007 — Hospitality obligations:** Catering, green rooms, lounges,
  credentials, comps, and special guest commitments must have owners, schedule,
  inventory, and fulfilment state.
- **VEN-008 — Reusable venue facts and edition overrides:** Stable properties,
  buildings, rooms, combinations, capacities, equipment, and floor-plan
  references may be reused across editions. An edition must explicitly select
  them, then own local display names, blocks, availability windows, and
  operational restrictions without mutating the reusable source. Schedule
  placement outside an applicable hard availability window must fail.

- **VEN-009 — Operational space intervals and public minimization:** Each
  edition space selection must resolve to immutable physical member spaces and
  versioned hard availability. A booking records setup, effective, and teardown
  intervals; physical conflicts and configured/fire capacities are enforced
  transactionally across combinations. Teardown immediately followed by a
  later setup is allowed, but setup/effective and effective/teardown overlap is
  not. Approval and publication require independent authorized actors. Public
  and attendee schedule projections expose only approved effective programme
  information and approved public layouts, never internal/security layouts or
  setup and teardown operations.

### Accreditation and physical access

- **ACC-001 — Credential model:** A credential must derive edition identity,
  role, entitlement, zone and time access, issuance state, and physical or
  digital token from explicit policy.
- **ACC-002 — Zone policy:** Physical access zones and exceptions must support
  time windows, age or training requirements, escort rules, and revocation.
- **ACC-003 — Issuance custody:** Blank stock, printed credentials, keys,
  wristbands, radios, and similar controlled items require inventory and
  accountable handover.
- **ACC-004 — Verification minimization:** Scanning must reveal only the
  decision and minimum details required for the checkpoint, not a general
  participant dossier.
- **ACC-005 — Revocation propagation:** Lost, replaced, expired, suspended, and
  revoked credentials must propagate to connected verification clients and
  reconcile after offline use.

### Assets, inventory, and logistics

- **LOG-001 — Asset identity:** Serialized and bulk assets must support type,
  owner, condition, storage, current custody, value class, maintenance, and
  edition allocation.
- **LOG-002 — Chain of custody:** Issue, transfer, return, loss, damage, and
  disposal must record actor, recipient, time, place, condition, and evidence
  appropriate to risk.
- **LOG-003 — Demand and reservation:** Departments may request and reserve
  assets or consumables against schedule, quantity, capability, and priority,
  with conflicts made visible.
- **LOG-004 — Movements:** Loads, deliveries, vehicles, drivers, routes,
  loading windows, storage, and handovers must connect to venue constraints and
  operational time.
- **LOG-005 — Kits and manifests:** Reusable kits, packing lists, load
  manifests, issue sheets, labels, and return checklists must derive from
  current asset data.
- **LOG-006 — Supplier delivery:** Expected delivery, acceptance criteria,
  receiver, discrepancy, corrective action, and invoice linkage must form one
  traceable process.
- **LOG-007 — Stock control:** Merchandise and operational stock must support
  adjustments, counts, locations, low-stock signals, wastage, and
  reconciliation without allowing silent quantity edits.
- **LOG-008 — Storage containment and whereabouts:** Year-round storage sites,
  containers, boxes, vehicles, loading areas, venue staging areas, and rooms
  must form a validated, acyclic containment and movement graph. The current
  location and custody of a tracked box, asset, or stock lot are projections of
  append-only receive, pack, move, load, unload, handover, count, and return
  events rather than freely editable fields. Movements record responsible
  actors, source, destination, time, edition allocation where applicable,
  condition or discrepancy, and manifest evidence. Maru may track equipment
  and vehicles for a documented operational purpose, but must not silently
  track volunteers' personal location.

### Safety, accessibility, welfare, and case work

- **SAF-001 — Separated case work:** Medical, safeguarding, conduct, security,
  welfare, accessibility, and general service records must use purpose-specific
  schemas and access policies rather than one broadly visible incident table.
- **SAF-002 — Duty routing:** Reports must route to qualified, on-duty roles
  with acknowledgement, escalation, and handover rules. Urgent real-world
  action must not wait for software.
- **SAF-003 — Minimum disclosure tasks:** Restricted information must be able to
  generate an ordinary operational task containing only the instruction needed
  by its assignee.
- **SAF-004 — Break glass:** Emergency access to restricted records must be
  time-limited, reasoned, prominently logged, notified for review, and never
  available merely because someone is a platform administrator.
- **SAF-005 — Case integrity:** Cases must retain chronology, reporter and
  subject communication, action ownership, evidence custody, external
  references, decisions, closure, and amendment without silent rewriting.
- **SAF-006 — Emergency planning:** Editions must maintain versioned response
  plans, command roles, contacts, assembly information, participant assistance
  needs, exercises, and offline copies.
- **SAF-007 — Accessibility requests:** People must be able to request
  accommodations and control appropriate sharing; coordinators must translate
  requests into scoped delivery work across departments.
- **SAF-008 — Public access information:** Published venue and programme
  information must include structured access features, known barriers, content
  or sensory notes where appropriate, and a maintained help channel.
- **SAF-009 — Retention trigger:** Restricted case categories must have explicit
  retention owners, triggers, holds, access review, subject-rights procedure,
  and defensible deletion or anonymization.
- **SAF-010 — Wellbeing constraints:** Workforce planning must support maximum
  hours, minimum rest, lone-working rules, supervision, and individual
  accommodations without exposing their sensitive justification.

### Dealers, art, charity, merchandise, and furry-specific services

- **FUR-001 — Commercial applications:** Dealer and artist applications must
  support portfolio, categories, table needs, assistants, power, content
  boundaries, review, wait-list, agreements, payment, and setup instructions.
- **FUR-002 — Floor planning:** Commercial spaces must support capacity,
  configurable table geometry, accessibility, power, adjacency constraints,
  setup slots, assistants, and a publishable map derived from approved state.
- **FUR-003 — Art and auction intake:** Art show and auction items must retain
  creator or donor, provenance, rights, condition, category, reserve, display,
  beneficiary, custody, bids, settlement, and collection.
- **FUR-004 — Bid integrity:** Auction bidding and close must use an auditable
  append-only record, defined tie and eligibility rules, controlled correction,
  and reconciliation to payment and item handover.
- **FUR-005 — Charity stewardship:** Charity beneficiaries, restrictions,
  campaigns, donated value, collected funds, costs, settlement, evidence, and
  public reporting must remain reconcilable.
- **FUR-006 — Merchandise lifecycle:** Merchandise must connect design approval,
  supplier, variant, order or preorder, stock, sales channel, pickup, refund,
  and residual inventory.
- **FUR-007 — Fursuit facilities:** Fursuit lounges, changing areas, storage,
  headless zones, water, drying or repair services, parade participation, and
  handlers must be represented as spaces, services, capacities, and staffing.
- **FUR-008 — Themed and social activities:** Meetups, dances, photoshoots,
  gaming, cafés, parades, competitions, and similar community activities must
  reuse programme, capacity, queue, staffing, consent, safety, and publication
  primitives rather than bespoke mini-apps.
- **FUR-009 — Age and content boundaries:** Adult programming, art, vendor
  content, and controlled zones must have explicit edition policy, age
  verification consequence, signage, access rules, and minimum-disclosure
  enforcement.
- **FUR-010 — Mascot and media assets:** Character, logo, photo, recording, and
  biography use must record owner, license or consent, scope, expiry,
  attribution, approved rendition, and withdrawal consequences.

- **FUR-011 — Governed charity partners:** An organizer may maintain reusable
  charity partner identity, imprint, contacts, location, description, and
  governed media without turning that partner into a Maru tenant organization.
  Each edition owns its proposal, responsible Department, review state,
  confirmation or rejection decision, restricted rationale/comments, and
  publication state. Confirmation, media approval, and publication require
  independently authorized evidence. Public projections include only active,
  confirmed, explicitly published snapshots with current approved media;
  rejected partners, private comments, contacts, and rejection reasons remain
  restricted. Multiple partners may be reviewed or published for one edition.

### Knowledge, policy, forms, and support

- **KNO-001 — Versioned knowledge:** Policies, runbooks, FAQs, briefings, venue
  facts, role guides, and templates must have owners, audience, review date,
  version, approval, and supersession.
- **KNO-002 — Contextual delivery:** The relevant approved guidance must appear
  beside the task or decision it governs and remain available in searchable
  knowledge views.
- **KNO-003 — Policy acknowledgement:** Required acknowledgements must retain
  exact policy version, person, time, method, and any later replacement without
  implying that reading proves understanding.
- **KNO-004 — Form builder:** Authorized teams must create versioned,
  conditional, localized, accessible forms from classified field types with
  validation, purpose, visibility, and retention metadata.
- **KNO-005 — Form-to-workflow:** A submission must create or update a typed
  domain process, assignment, message, or case; it must not become an isolated
  response sheet by default.
- **KNO-006 — Service catalog:** People must be able to request help through a
  plain-language service catalog that routes to the correct team with expected
  response and safe escalation.
- **KNO-007 — Handover learning:** Post-event lessons must be proposed,
  reviewed, linked to evidence, and accepted into a reusable template or
  knowledge item rather than copied as unverified folklore.
- **KNO-008 — Governed document library:** Public, ticketed, internal,
  department-confidential, restricted, and legally held documents must retain
  owner, purpose, applicability, classification, immutable versions, approval,
  effective and review dates, supersession, retention, download policy, and
  acknowledgements where required. NDAs, policies, event-type guidance,
  department runbooks, venue documents, and internal records use the same
  library without exposing confidential source files through public
  renditions. Search, API delivery, and exports must enforce the viewer's
  current scope and field policy at request and download time.
- **KNO-009 — Typed application portfolio:** Editions must configure multiple
  versioned application types from the shared form vocabulary, each with a
  plain-language purpose, owning departments, eligibility, cardinality,
  deadline, applicant and staff edit windows, field-level writer and audience,
  review workflow, decision states, retention, and target-domain adapter.
  Answers retain schema version, provenance, editor, and revision history.
  Generic response sheets are not the source of truth after a submission
  advances into its typed programme, commercial, artwork, workforce, document,
  or service record.

### Workflow automation and responsible assistance

- **AUT-001 — Event-driven automation:** Authorized users must define triggers,
  conditions, delays, and typed actions over documented domain events.
- **AUT-002 — Safe execution:** Automations require edition scope, service
  identity, permission ceiling, idempotency, run history, rate limits, and
  retry or dead-letter behavior.
- **AUT-003 — Test and preview:** An automation must support sample-data tests,
  impact preview, draft mode, and clear explanation before activation.
- **AUT-004 — Human checkpoints:** Financial, access, disciplinary, safety,
  publication, and other configured high-impact decisions must preserve
  required human approval.
- **AUT-005 — Explainable assistance:** Recommendations and generated drafts
  must disclose relevant inputs, uncertainty, and source state; a person remains
  accountable for consequential use.
- **AUT-006 — No hidden profiling:** Models must not infer protected or intimate
  traits, opaque volunteer worth, misconduct propensity, or eligibility from
  unrelated activity.
- **AUT-007 — Reversible rollout:** Automations must be versioned, pausable,
  observable, and deployable to a rehearsal edition before production use.

### Live operations and service delivery

- **OPS-001 — Common operating picture:** Authorized live operators must see
  current programme, staffing, venue, logistics, service demand, public
  communication, material issues, and data freshness from one projection.
- **OPS-002 — Run of show:** Programme and operational items must support call
  times, setup, cues, dependencies, owners, actual times, notes, and structured
  handover in a time-ordered view.
- **OPS-003 — Dispatch:** Work may be offered or assigned to an available,
  qualified duty role with acknowledgement, location, priority, escalation, and
  completion evidence.
- **OPS-004 — Queues and capacity:** Organizers must be able to represent
  capacity, entry windows, observed or estimated queues, closure, and
  attendee-facing advice without claiming false precision.
- **OPS-005 — Change impact:** A material live change must preview affected
  people, dependencies, outputs, and delivery destinations before publication
  unless emergency authority records an override.
- **OPS-006 — Shift handover:** Active roles and desks must have structured
  open work, recent decisions, known hazards, asset custody, and acknowledgement
  at handover.
- **OPS-007 — Lost and found:** Items, distinguishing details, claims, custody,
  controlled release, risky-item procedure, and disposition must be managed
  without publishing the ownership proof.
- **OPS-008 — Rehearsal:** Editions must support drills or simulations using
  production-like configuration without notifying real audiences or corrupting
  production history.

### Privacy, compliance, and participant control

- **PRI-001 — Data inventory:** Every stored field and derived data class must
  have purpose, owner, sensitivity, subject, source, access policy, retention,
  export, and deletion behavior.
- **PRI-002 — Controller boundaries:** The platform must record which
  organization controls or receives data for each process and must not turn one
  platform identity into unannounced joint access.
- **PRI-003 — Consent correctness:** Consent must be specific, informed,
  versioned, withdrawable where applicable, and separated from processing that
  uses another lawful basis.
- **PRI-004 — Subject rights:** Identity verification, access, correction,
  portability, restriction, objection, and deletion requests must have
  documented, tracked procedures and scoped exports.
- **PRI-005 — Minor and guardian policy:** Editions that admit minors must
  configure age bands, guardian relationships, permissions, visibility,
  communication, check-in, and safeguarding rules for their jurisdiction.
- **PRI-006 — Data residency and vendors:** Deployments must inventory
  processors, regions, transfers, agreements, subprocessors, and exit or export
  capability.
- **PRI-007 — De-identification:** Analytics and edition comparison should use
  aggregate or de-identified data where person-level data is unnecessary, with
  small-group and re-identification controls.
- **PRI-008 — Communications preference:** Optional marketing, operational
  service messages, direct conversations, and emergency communication must have
  distinct purpose and preference behavior.
- **PRI-009 — Correction, minimization, and disposal evidence:** Current data
  may be corrected without rewriting historical submissions. Post-edition
  corrections require proposal and review; retention actions must use approved,
  versioned policy and create a receipt while preserving required finance,
  safety, and audit evidence.

### Integration and extension platform

- **INT-001 — Stable API:** Supported domain capabilities must be available
  through documented, versioned APIs with generated schemas and consistent
  authorization, pagination, errors, idempotency, and deprecation policy.
- **INT-002 — Webhooks and event feed:** Authorized consumers must receive
  signed, replayable, scoped domain events with sequence, delivery state, retry,
  and secret rotation.
- **INT-003 — Connector isolation:** External systems must use replaceable
  adapters with credential vaulting, least privilege, health, rate-limit,
  reconciliation, and disablement behavior.
- **INT-004 — Scoped applications:** Third-party applications require explicit
  organization approval, declared scopes, install owner, data-use description,
  access review, and revocation.
- **INT-005 — Import safety:** Imports must support mapping, validation,
  preview, duplicate strategy, partial-error reporting, provenance, and
  reversible staging before authoritative application.
- **INT-006 — Extension boundary:** Extensions may register typed views,
  actions, fields, workflow handlers, report sources, and connectors only
  through versioned contracts; they may not read arbitrary module tables.
- **INT-007 — Exit capability:** An organizer must be able to export supported
  records, files, schemas, configuration, audit manifests, and identifiers in a
  documented form before ending service.
- **INT-008 — Credentialed read projections:** Website, timetable, signage, and
  other read consumers must use least-privilege, organization- and
  edition-scoped credentials with declared projection type, expiry, rotation,
  revocation, health, and access evidence. Raw secrets are shown only at issue
  or rotation time and must not become durable application data or routine URL
  content.

## Cross-cutting requirements

- **NFR-001 — Thorough testing:** Critical workflows, permission boundaries,
  tenant isolation, concurrency, migrations, exports, and recovery must be
  automatically tested according to `docs/quality/testing-strategy.md`.
- **NFR-002 — Living documentation:** Product, architecture, API, operations,
  security, and role-specific user documentation are deliverables.
- **NFR-003 — Checkpoint continuity:** Every material change must leave a
  repository checkpoint that allows a new maintainer or agent to resume safely.
- **NFR-004 — Observability:** Requests, jobs, integrations, delivery attempts,
  and domain failures must be traceable without logging unnecessary personal
  data.
- **NFR-005 — Degraded operation:** Critical on-site flows must define behavior
  for slow, intermittent, or unavailable network access.
- **NFR-006 — International operation:** Data and interfaces must support
  Unicode, localization, edition time zones, and European address and payment
  realities.
- **NFR-007 — Data portability:** Organizers and users must have documented,
  permission-controlled export and deletion processes.
- **NFR-008 — Recoverability:** Backups, restoration, reconciliation, and
  disaster procedures must be tested rather than assumed.
- **NFR-009 — Explicit input contracts:** Every operator, participant, import,
  and API input must have a documented type, format, length or range, null and
  blank meaning, normalization, classification, writer policy, lifecycle rule,
  and actionable validation error. Domain services repeat security-critical
  validation inside transactions and databases enforce durable invariants
  where practical. Unknown fields, tenant identifiers supplied in place of
  trusted scope, unsafe files, ambiguous local times, impossible containment,
  and silent truncation must be rejected.
- **NFR-010 — Pinned database execution boundary:** Runtime database
  connections and security-critical functions must resolve trusted catalogs,
  relations, and internal functions through a code-owned schema order. Caller
  DSN options, temporary objects, per-user schemas, or stale pooled sessions
  must not shadow tenant, authority, audit, migration, or cutover state.
  Production must name and use a dedicated login role that cannot inherit
  administrative attributes or predefined roles; own the database, a user
  schema, relation, or function; create database/schema objects or temporary
  tables; or trigger, truncate, or maintain application tables. Ordinary DML
  must be positively available alongside database connection and user-schema
  usage, except that provenance marker/latch controls and materialized views
  are SELECT-only. Sequences permit use/read but never update. The login must
  have no reachable membership admin option, database/schema/relation/column/
  sequence/function grant option, explicit effective PostgreSQL parameter
  setting ACL, or persistent non-origin `session_replication_role` setting;
  the live setting must be `origin`. Non-system functions must be closed to
  `PUBLIC`; only the explicit versioned runtime policy/trigger-helper closure
  may be executable by the application role.
  Activation must prove the future named role even when connected as the
  controlled migration/cutover owner, while that owner's live trigger setting
  remains safe. Public production readiness must additionally prove that
  `CURRENT_USER`, `SESSION_USER`, and the backend's authenticated identity all
  equal the dedicated login; role switching or session-authorization
  impersonation is insufficient. The reserved provenance-activation audit may
  be inserted only as the exact same-transaction companion to the marker and
  latch transition. Production readiness must fail closed
  without disclosing identifiers when the role, effective runtime boundary, or
  supported database-major contract is not the rehearsed one.
- **NFR-011 — Protected repository and supply-chain integrity:** Changes must
  enter protected branches through independently recorded exact-commit
  acceptance without a routine bypass. Dependency manifests and lockfiles,
  external automation references, and repository security rules must have a
  reviewed checked-in desired state with automated drift detection. External
  Actions must use immutable revisions and an exact minimal allowlist;
  dependency-security automation and code scanning must use documented risk
  thresholds. Cheap lock and automation-policy checks must fail before
  expensive acceptance work. External repository settings require separate
  authorization, a pre-change read, and post-change reconciliation that does
  not silently adopt undocumented or server-managed response fields. Routine
  maintenance, security-update handling, release evidence, and drift recovery
  must remain documented.
- **NFR-012 — Ethical fictional examples and research boundaries:** Named
  conventions, organizations, people, contacts, screenshots, fixtures,
  tutorials, generated contracts, and other repository-controlled examples
  must use Maru-owned fictional identities, synthetic people, and RFC-reserved
  example domains. They must not fetch, copy, snapshot, or translate a real
  convention roster, people directory, organization chart, people-to-role
  mapping, brand, or source-derived operating taxonomy into example data.
  Public material may inform generalized requirements only through documented,
  reviewed synthesis that does not retain unnecessary branding or imply
  affiliation. A partner-specific import requires an explicit purpose,
  authority or lawful basis, provenance, minimization, correction, access,
  retention, and removal contract. This restriction does not erase necessary
  attribution for software, standards, dependencies, licenses, security
  advisories, or an organizer's authorized use of its own identity in a
  governed deployment.
- **NFR-013 — Progressive modular adoption:** An organization must be able to
  adopt one complete Maru workflow without enabling registration, payments,
  attendance, or unrelated modules. Each adoption profile must declare its
  required shared foundations, enabled destinations, purpose-specific roles
  and accounts, records and side effects, integration and coexistence
  boundaries, import/export/print/manual fallbacks, and upgrade or removal
  behavior. Unadopted modules must not create records, navigation,
  notifications, authority, or operational dependencies. A purpose-specific
  account such as a bidder, event host, volunteer, or communications operator
  must not imply attendance, purchase, payment, or broader participation and
  data collection. Cross-module automation may begin only after deliberate
  adoption of every participating capability.

## Explicit non-goals

- Maru is not a general-purpose social network.
- Maru is not a replacement for an emergency-services communication system.
- Maru will not store payment-card details.
- Maru will not reproduce every feature of Telegram or Discord.
- Maru will not begin as a collection of microservices.
- Cross-convention identity will not become cross-convention surveillance.
