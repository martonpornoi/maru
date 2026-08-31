# Experience and information architecture

Status: Focused unified shell, truthful Representation & access handoff,
guided Workforce-only adoption, profile-scoped navigation, owner-rehearsed
Registration desk for full-convention editions, and governed Position,
Assignment, Availability, and Shift management locally verified; complete
mutation-role, state-matrix, width/zoom, and release accessibility evidence
pending
Last updated: 2026-08-26

## Current executable experience

ADR 0030 established the two-page baseline. ADRs 0031–0038 and M1 restored the
first executable setup journey. ADR 0039 moves it into the richer
record-oriented administration grammar without creating another product. ADR
0040 defines the next selected-organization handoff. ADR 0041 defines, but does
not yet implement, exact department/resource access; ADRs 0042 and 0043 make
the educational data synthetic-only and add emergency controller containment.
The canonical route design
is:

1. Sign in at `/accounts/login/`.
2. Enter the permission-filtered shared shell at `/admin/`.
3. Open API-backed Convention work at `/admin/workspace/` or
   permission-filtered specialist records through the same sidebar.
4. To adopt only volunteer management, open
   `/admin/platform/setup/workforce/`, reuse the highest existing foundation,
   and supply only the missing organization/convention identity plus edition
   name, dates, and time zone.
5. Open the active-platform-administrator-only organization inventory at
   `/admin/platform/organizations/`.
6. Create a complete optional Draft organization at
   `/admin/platform/organizations/new/`.
7. Maintain its profile and nested convention-series inventory at
   `/admin/platform/organizations/<slug>/`.
8. Open Representation & access at
   `/admin/platform/organizations/<slug>/representation/`, provision the
   truthful Executive Board or Maru-operator root, invite at least two exact
   existing verified person accounts, let each answer their own invitation, and
   activate the organization under cross-approval.
9. Create a series at
   `/admin/platform/organizations/<slug>/series/new/` and maintain it at the
   nested series record.
10. Create an idempotent Draft edition below that series, deliberately choose
    its immutable adoption profile, and revisit its nested record/activity page
    with explicit POST-only working-context selection.

The shared Platform administration section remains one **Organizations** row
with adjacent compact **+ Add**. Convention series stays nested beneath its
accountable tenant and does not become a second global website/menu. The pages
explain that the administrator operates Maru but does not participate in a
convention. Series creation requires only the recurring brand name, keeps
organization and slug code-owned, and does not create a dated edition or people
relationship. Edition creation likewise creates identity and evidence only.
Representation & access is the explicit exception that creates invited/active
accountable-operator relationships for the exact people who accept; it never
enrolls the platform administrator or claims a Board title that is not real.

For `workforce_only@1`, the shell releases Today, Workforce, purpose-matched
Setup, Security, and one explicit specialist-record disclosure. It omits People
attendance, Registration, payments, Reports and badges, and unrelated planned
module pressure. The complete owner path is Structure → Positions →
assignments → Availability → Shifts. A Workforce account and assignment do not
manufacture Participation or attendance. Backend policy applies the same
boundary before platform oversight or stored grants, so this is not merely menu
customization.

An exact Workforce-only edition in the current route drives both the menu and
workspace selector even when the session has no saved edition context. A fresh
organization can create one independently approved, code-owned Volunteer
Position starter after its first Department; this supplies minimal reusable
role meaning without granting access or creating a Position or person record.
Public volunteer pages use a Volunteer-only shell that disclaims attendee
Registration, attendance, and payment. Personal Workforce routes focus the
Personal and Work groups on My Maru and My Workforce rather than advertising
unadopted or unrelated personal workflows.

The `platform` segment is reserved for purpose-built platform pages and avoids
collisions with Django application-label routes. The administration home,
Convention work, platform spine, and specialist records share one collapsible
sidebar, platform identity, and record-oriented visual grammar. Public and
personal journeys may remain outside `/admin/` by purpose; they do not become a
second staff shell. Health and versioned APIs remain authoritative contracts.

Every active account may enter the Maru shell. Platform administration home and Create organization remain platform setup.
Effective organization/edition grants and role assignments allow ordinary non-
staff accounts to reach only their scoped the organization-scoped setup and representation surfaces and Convention work;
invitees see only their own governance invitations. Specialist model records
remain separately Django staff/model-permission gated.

Current backend tests verify changed default routes, profile-scoped navigation,
scoped shell access, both Representation & access types, bounded sensitive
reads and denials, assignment evidence matched to adoption, and database-level
platform-subject exclusion. The focused recovery pass also
verifies task-first search and pin customization, separate personal and
administrative registries, one compact context control, one page-local access
summary, purpose-built setup links, and a queue-first Registration desk.
The current owner pass also verifies one host-owned selected-edition context,
modal detail-drawer focus/Escape behavior, and a Workforce sequence over the
existing structure projection. Frontend type checking, 29 Vitest tests,
production build, local populated/
fresh migration and restore evidence, desktop/390-pixel browser review, and
the 1,100/1,101-pixel drawer breakpoint pass. A final broad suite and complete
keyboard, failure-state, width/zoom, mutation-role, and representative
screen-reader matrix remains open under UX-013; the focused Registration and
Workforce views now have automated axe coverage.

Every later page requires UX-013's page contract and evidence. ADR 0037 groups
dependent pages into executable milestones instead of requiring a separate
owner pause after each isolated page. ADR 0039 permits preserved visual and
interaction grammar to be reused, but preserved source does not make a page
current or authoritative.

## Preserved target model

The material below remains product evidence and a possible future direction,
not a description of currently mounted pages. Maru is one platform expressed
through focused surfaces and must not become one enormous menu containing every
department's nouns.

## Experience model

```text
One identity and notification center
|
+-- My Maru             personal participation and actions
+-- Administration      setup, specialist records, access, and operations
+-- Now Mode            live, time-critical execution
+-- Public Experience   programme, information, registration, content
+-- Focused clients     check-in, kiosk, signage, scanner, relay
```

All surfaces use the same domain APIs, authorization decisions, messages,
published schedule, and activity trail. A focused client is not a separate
account or source of truth.

## Platform identity and annual themes

Maru's stable operational shell uses the owned navy, gold, and ivory identity
documented in [`platform-brand.md`](platform-brand.md). The same identity
connects Convention work, specialist records, local account entry, and the
bundled public reference client without implying that every convention must
look alike.

An annual convention website is a replaceable client. Its team may change
artwork, color, layout, interaction, and editorial presentation while
consuming the same versioned APIs. It must preserve accessible semantics and
cannot override Maru's authorization, availability, price, capacity, payment,
or lifecycle decisions. Edition artwork is convention content, not a mutation
of the platform identity.

## Public registration

The local entry page offers `Register for a convention` without requiring an
account first. The registration surface follows a short, explicit journey:

```text
choose an open convention
  -> sign in or create an account
  -> choose admission
  -> complete fixed identity/contact fields and convention-defined sections
  -> review the edition-owned profile and operational status
```

A returning attendee sees their registrations separately from other open
conventions and deliberately selects the next edition. The newest earlier
same-organization profile may appear as a clearly labeled, editable suggestion.
Submitting it creates a new edition snapshot; older profiles and convention
answers remain unchanged, and public-list consent is never carried forward.

The bundled form is a neutral reference and fallback client. A convention may
replace its artwork, page structure, animation, and seasonal theme by consuming
the versioned public registration definition. Maru remains authoritative for
opening times, eligibility, price, capacity, required answers, reservations,
waitlists, and payment state; a frontend cannot grant itself a discounted or
paid outcome.

The submitted profile separates restricted identity/contact data, structured
pronouns and languages, optional bio/profile image, optional multiple fursuits,
convention-defined answers, and authoritative roles or benefits. New images
remain private for review; an unchanged approved file may be reused within its
owner and organizer boundary. Volunteer departments derive from assigned
capacities and ticket-holder labels derive from entitlements.

A separate public attendee list includes only confirmed or checked-in people
who consented for that edition. Its HTML and JSON renditions expose only
display name, pronouns, bio, spoken languages, fursuit name/species, approved
images, an optional separately entered public country, and broad authoritative
attendee/volunteer/sponsor/guest labels. Status is written as text with color
as a redundant cue. The list disappears when the edition is archived or
cancelled; legal/contact/emergency/product/price/payment data never enters it.

## Global context

The persistent context switcher shows:

`Organization / Convention series / Event edition / Surface`

The edition name, state, local time, and live/draft/archive status remain
visible. Switching context never silently broadens access. Links carry durable
resource identity and resolve safely for authorized viewers.

Archived editions are visually distinct and read-only by default. A correction
requires a separate, reasoned action rather than an ordinary edit button.

ADR 0039 reuses the pre-reset shell's explicitly selected event-edition
grammar. Edition-owned lists, details, counts, normal relationship choices, and
new-record defaults follow that context. Specialist records also offer
`All foundation data` for first-time platform setup. The migration must prove
that this context remains a query/display aid rather than authority.
Cross-edition reuse appears only in purpose-named workflows such as
registration template or source-edition selection; it never silently mixes
routine operational rows.

The unified `/admin/` home leads with current work and a small set of durable
tasks. It retains the complete permission-filtered alphabetical model directory
through one collapsed, searchable **Specialist records** gateway rather than
placing every implementation noun in the default menu. ADR 0027 removed the
former global Quick Start strip.
Organization, series, edition, Chair identity, guarded first authority,
registration, workforce, and readiness guidance is contextual inside
Convention work's **Setup guide**. An eligible workspace-less superuser
completes the password-confirmed, exact-scope-confirmed leadership ceremony
there; after completion it becomes a read-only explanation rather than a
permanent action. The guide is not a readiness checklist and ordinary
navigation never grants access or marks work complete.

The selected `/admin/` shell has one task-first sidebar. Convention work is
immediately visible, while Convention tools, Organizations, Platform, and
Specialist records are progressively disclosed according to current scope.
Pin controls appear only inside **Customize navigation**. Search reports task
matches first and keeps technical-record matches collapsed. Embedded
workflows do not render another global navigation or workspace selector; their
headings, modules, fields, tables, buttons, and responsive spacing follow the
same language as specialist record pages. Convention work's Today page keeps
published form-driven
workflows in a separate Forms section rather than scattering registration,
volunteer applications, and onboarding documents through unrelated menus.
Existing model pages remain inside the same `/admin/` hierarchy and use the
same sidebar. `/manage/`, `/staff/`, and `/admin/records/` are removed rather
than redirected. Setup guide also presents the current edition lifecycle,
valid next states, consequences, reason entry, and stronger confirmation for
terminal transitions; registration opening remains separate.

## My Maru

The personal surface belongs to the user, not to one department.

The current personal home separates its high-frequency **Start here** tasks
(registration, applications, and schedule) from **More from Maru**. Its menu
contains only Personal and Work destinations; Platform and Specialist records
remain on Administration. An authorized person may switch surfaces explicitly,
but pins and navigation groups do not cross that boundary.

Inside a Workforce-only personal journey, purpose focus takes precedence over
the broad future-state home catalog: My Maru and My Workforce remain available,
while Registration & tickets, Shop & orders, My applications, My schedule, and
Equipment offers are absent. A non-staff organizer with administrative
authority sees the explicit label **Convention workspace** for that surface;
the link does not imply platform employment or Django staff status.

### Home

- Next best action
- Deadlines and blockers
- Upcoming schedule and reporting locations
- Unread direct or official messages
- Material changes requiring acknowledgement
- Registration, application, order, and onboarding status
- Quick access to pass or check-in credential

### Events

- Current and upcoming editions
- Invitations and incomplete applications
- Past participation and opted-in achievements
- Receipts, certificates, and permitted retained documents

### My schedule

Programme interests, shifts, host appearances, rehearsals, setup, travel,
breaks, and private calendar blocks appear together with clear visibility
labels. Maru explains conflicts and never publishes a private calendar entry.

### Inbox

Direct conversations, application and service threads, department messages,
official notices, and mentions use one inbox with filters and notification
preferences. Promotional content cannot masquerade as an operational notice.

### Profile and privacy

Global identity attributes, organizer-specific relationships, edition answers,
public profile, emergency or accommodation data, consents, linked identities,
sessions, exports, and deletion requests are visibly separated.

## Administration and Convention work

ADR 0039 selects one administration shell and collapsible global menu. Its
route, authorization, frontend, and responsive integration is locally verified:

- **Platform administration:** the organization -> representation -> series ->
  edition record spine under `/admin/platform/`;
- **Convention work:** Today, People, Workforce, Organization structure, My
  registration, Registration desk, Reports & badges, Setup guide, Security history, and
  Manage access, with canonical edition Registration and Capacity & waitlist
  tasks named separately; and
- **Specialist records:** the complete permission-filtered Django record
  directory, with its existing model routes.

Convention work is embedded inside this shell. The Django header provides
edition context and account actions without a second menu or duplicated
selector. Modules may
register actions, search providers, dashboard cards, and permission
requirements without creating another global navigation.

Converted pages share one compact frame: one H1, purpose guidance where needed,
then an **Access** disclosure naming the current scope and computed policy. The
expanded content carries allowed actions and authority sources without
duplicating the page title or presenting a manually maintained ACL. The React
workspace renders this disclosure inside its active view; the Django host does
not mount another copy before the application.

### Initial organization representation

The selected organization exposes **Representation & access** before
department-owned work. Representation & access uses a distinct, ordered handoff rather than a
generic role editor: an active platform administrator provisions the fixed
Executive Board root, authorized management exact-matches existing active
verified person accounts, each invitee accepts or declines their own versioned
invitation, and a platform administrator activates at least two accepted
controllers under non-self cross-approval. Activation atomically moves the
organization from Draft to Active.

Appointment email and the controller directory are visible only to an exact
organization-scoped manager; an invitee sees only their own open appointment.
The header explains platform oversight, invitation ownership, and active root
assignments without presenting the platform administrator as a member. This is
the first computed relationship slice, not the final department/resource/field
effective-access view. Expiry, replacement, ending, suspension, invitation
notification delivery, routine term ending/replacement, quorum recovery, and
legacy active-organization reconciliation remain open and prevent a
production-ready claim. ADR 0043's platform-only emergency path may end all of
one compromised person's Board relationships and suspend Boards that lose
quorum; it is not a routine lifecycle editor.

### Access sharing

Every active Convention work page offers **Manage access** only when the
operator holds role-management authority in the selected edition. The same
entry is present in the administration sidebar. The sharing workspace resembles
familiar collaboration tools while retaining Maru's stronger invariants:

- a person is exact-matched by an existing active account email and shown by
  display name plus email;
- familiar groups such as Front Desk, Registration, Board, Treasurer, and
  department roles are immutable scoped role bundles, not Django Groups;
- current page context may recommend groups but never creates a page-local ACL;
- add and change require a reason, optional expiry, and distinct authorized
  approver;
- change is an atomic revoke-and-reassign operation;
- removal is immediate, reasoned, and available only with revocation authority;
  and
- names, labels, slugs, and references lead the UI while UUIDs remain internal
  transport identities unless exact technical evidence is necessary.

Sharing a group grants system capabilities only. A formal volunteer or staff
appointment still uses the workforce position workflow so NDA evidence,
headcount, reporting hierarchy, capacities, and official convention role
remain connected.

### Workforce continuity

The durable **Workforce** task connects the exact-edition Department projection
to the human operating sequence **Structure -> Positions -> Assignments ->
Availability -> Shifts**. It shows current Position purpose, reporting,
headcount, vacancies, and minimized active holders from the existing bounded
structure API. Department changes continue through canonical Department management, and
the Registration desk uses one Workforce handoff instead of sending an owner to
several staff-only model screens.

Authorized managers continue from Positions into the purpose-built Position
workspace. Creation deliberately chooses an immutable organization template,
exact Department, responsibility, headcount, and optional reporting Position;
editing separates operational details from immutable role meaning. Opportunity
publication is a distinct applicant-facing action, and protected closure names
its dependencies instead of silently deleting assignments, reports, or access.
Each Position retains its directly inspectable organizer reasons.

Assignment management continues from a Position into a relationship-bounded
known-person proposal, visible onboarding readiness, and a genuinely different
controller's stepped-up approval or rejection. Proposal reserves headcount but
grants nothing; approval atomically activates the role and only the evidence
required by the immutable edition profile. Full-convention editions retain
their Participation projection, while Workforce-only approval and ending touch
no Participation evidence and keep the assignment pointer null. Ending revokes
linked authority and retains its reason. **My Workforce** gives the subject a
separate reason-minimized state and dates view. Non-staff owners see
purpose-built continuations rather than inaccessible specialist links.

Availability is now a person-owned continuation in **My Workforce** and a
separately capability-scoped organizer projection. A person may keep a private
draft, explicitly share their complete exact-edition periods, report an empty
set as unavailable, or withdraw current exact periods. Organizers see only
open-assignment people, operational Position labels, current shared
consequences, and submitted periods; absent and draft plans are both **Not
shared**. The UI does not infer Availability from assignments.

**Shifts** is now a distinct, governed planning stage. Organizers create
Position-specific demand, open it for claims, review named coverage, confirm or
remove commitments with accountable rationale, lock a deliberate coverage
decision, and complete or cancel the demand. People use **My shifts** to see
only suitable open demand and their own claims or commitments, with briefing,
break, rest, supervision, and handover instructions retained. A claim is never
presented as organizer confirmation, personal withdrawal requires explicit
confirmation but no private explanation, and neither a Position nor an
Availability period is presented as scheduled work. Broader qualifications,
maximum-hours policy, publication, reminders, check-in, and timekeeping remain
later extensions rather than implied behavior.

The implemented Reports destination starts with one purpose-built
registration preset: attendance totals, country and attendee-level
breakdowns, a badge-data preview, and a minimized CSV export. It is edition
scoped, capability gated, audited, filterable, and explicit about excluded
private fields. It is the first role-oriented report, not yet the general
saved-question/query-builder experience.

### Surface orientation

Every active page places one short purpose statement directly below its main
title. It says why the page is useful, what can be done there, and gives one or
two concrete examples. The same guidance remains present in empty, denied, and
failure states so a user is not left to infer the page's purpose from controls
or implementation terminology.

### Department cockpit

Each department receives the same structural view:

- current readiness and evidence;
- assigned and unowned work;
- people and coverage;
- inbox and service level;
- schedule and dependencies;
- spaces, assets, and budget position;
- risks, decisions, changes, and live issues; and
- handover and post-event work.

Domain-specific cards may extend the cockpit without creating a second home
page.

### Object workspace

Opening a person, session, shift, order, case, room, asset, or project presents:

1. identity and current state;
2. important actions;
3. role-specific summary;
4. details grouped by purpose;
5. relationships and dependencies;
6. conversation;
7. files and generated artifacts; and
8. authorized activity timeline.

A side context panel lets an operator inspect a related object without losing
the list, filters, selection, or scroll position.

## Search, query, and command

The current shell search is navigation-only. It matches authorized code-owned
task labels, descriptions, and generic keywords, distinguishes task matches
from technical records, clears on Escape, and never indexes tenant or person
values. It is not yet the object-search or command-palette capability described
below.

The command palette supports navigation and permitted actions. Global search
uses human identifiers, aliases, fuzzy matching, and typed results. It never
leaks the existence of unauthorized objects through counts, suggestions, or
timing where practical.

Operational lists share:

- query chips and an explainable natural-language summary;
- visible column and sensitivity metadata;
- saved and shareable views;
- bulk selection across pages with explicit scope;
- preview and undo for reversible bulk actions;
- background execution for large operations; and
- deep links that preserve context.

Natural-language assistance may propose a query but cannot bypass the safe
field catalog or authorization policy.

## Now Mode

Now Mode is an edition-wide operational projection optimized for time pressure,
touch use, unstable connectivity, and rapid handover.

### Personal Now

- current and next assignment;
- check-in or acknowledgement;
- exact place and route hint;
- concise briefing and attachments;
- duty contact and escalation;
- affected changes; and
- `I need help`, `I am delayed`, and `Cannot attend` actions.

### Department Now

- staffed posts and gaps;
- active work queue;
- rooms, assets, and dependencies;
- service demand and ageing;
- live issues, changes, and handover notes; and
- next 30, 60, and 180 minutes.

### Event command

- common operational picture;
- material alerts and accepted risks;
- programme and venue deviations;
- capacity and queue signals;
- welfare and accessibility tasks without overexposure;
- public communication state;
- decision log;
- incident command roles; and
- degraded-mode and recovery status.

Now Mode must avoid decorative dashboards. Every signal identifies its source,
age, owner, consequence, and available action.

## Attention model

Maru uses a common attention object rather than module-specific notification
noise.

| Level | Meaning | Delivery expectation |
| --- | --- | --- |
| FYI | Useful context, no action | Inbox or digest |
| Action | The recipient owns a next step | Action center and chosen reminder |
| Blocking | Another commitment cannot proceed | Prominent to owner and dependency |
| Urgent | Time-sensitive operational harm | Immediate configured channels |
| Emergency | Life safety or major incident protocol | Predefined command procedure |

Urgency is a permissioned action. It expires, may require acknowledgement, and
is audited. Users can tune optional notifications but cannot accidentally mute
properly authorized emergency channels.

## Change impact and publication

Before applying a material change, Maru previews:

- affected people and roles;
- schedule, room, resource, and staffing conflicts;
- public and internal views that will change;
- signage, calendar, API, print, and external-channel consequences;
- acknowledgements or approvals required; and
- integrations currently unable to receive the update.

The operator may revise, schedule, publish, or cancel the change set. Emergency
authority can accelerate the flow while retaining the evidence trail.

## Responsive and accessible interaction

- WCAG 2.2 AA is a release criterion, including staff interfaces.
- Complete keyboard operation is required for high-volume desk workflows.
- Touch targets and contrast support poor light and hurried on-site use.
- Status is never communicated only by color.
- Times always show edition time zone when ambiguity is possible.
- Tables have compact and comfortable density settings.
- Narrow high-frequency record tables become labelled cards when that preserves
  row context better than panning; any retained data-region scroll is explicit.
- Draft input survives navigation and recoverable network failure.
- Essential tasks work at 200% zoom and on a narrow mobile screen.
- Motion is optional and never carries operational meaning alone.

## Speed budgets

With representative edition data and warm application caches:

- navigation shell feedback: within 100 ms;
- common filtered list response: p95 under 500 ms server time;
- object workspace useful content: p75 under 1.5 seconds on supported networks;
- typeahead first useful results: p95 under 300 ms server time;
- local acknowledgement in Now Mode: immediate, with sync state visible; and
- expensive export or planning work: asynchronous with progress and safe retry.

Budgets are targets for validation, not promises that justify hiding failure.

## Avoiding clicking hell

- Put the next permitted actions beside the state they change.
- Keep the previous result set and context after an action.
- Permit inline changes when validation and consequences are local.
- Use reusable command and bulk-action patterns.
- Pre-fill known, purpose-compatible data and explain its source.
- Turn validation errors into linked actions.
- Make ownership transfer one explicit operation.
- Use defaults inherited from reviewed edition templates.
- Prefer one composite workflow over a chain of unrelated CRUD pages.

## Customization boundary

Organizers may configure terminology, fields, pipelines, forms, views,
templates, automation, and brand. They may not configure away tenant isolation,
audit, accessibility semantics, historical integrity, or core lifecycle
invariants.
