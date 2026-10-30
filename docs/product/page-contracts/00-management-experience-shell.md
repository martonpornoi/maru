# Cross-cutting contract: Management experience shell

- Status: Focused shell hierarchy, page framing, personal-surface separation,
  User accounts-to-Board continuity, owner-rehearsed Registration desk, and the
  Workforce journey through Shift planning and My shifts implemented; full mutation-role,
  state-matrix, width/zoom, and release accessibility evidence remains pending
- Canonical authenticated route: `/admin/`
- Requirements: UX-001 through UX-013, UX-019, UX-020, UX-024, UX-026, UX-027,
  UX-029, UX-031, and NFR-001 through NFR-004
- Decisions: ADRs 0026, 0027, 0039, 0040, 0049, 0055, and 0116

## Purpose and boundaries

The management shell gives each authenticated operator a small, teachable set
of authorized tasks without creating a second administration product. It
retains the canonical `/admin/` route family, server-owned authorization,
selected organization and edition context, purpose-built workflows, and
authorized Django advanced records.

Presentation never grants authority. Every link is resolved and authorized on
the server before disclosure, every destination authorizes again, and selected
context remains a convenience rather than an access-control decision. The
shell introduces no new account kind, organization relationship, capability,
writer, audit boundary, or client-side source of truth.

## Task-oriented navigation and home

The default navigation prioritizes durable, role- and context-relevant
destinations. The administration home offers a small set of links from that same
live authorized registry, including reauthorized pins, without repeating the
exhaustive Django model directory or reconstructing permission from an adoption
profile. Labels, descriptions and exact URLs stay owned by the registry.

With a selected supported event, the home says **Work on <event>** and presents
available tools. It does not infer unfinished setup, completion, deadlines or a
best next action from event existence or lifecycle. **Setup steps** is secondary
and appears only when the current registry admits its destination. A supported
event with no admitted home tools gets a neutral access explanation, never an
all-clear or hidden-record count. An unknown profile gets the existing unavailable
explanation without work links. Without a selected event, the home asks the user
to choose one; only admitted platform links offer organization/account management.
Scoped users get a safe organizer-access handoff, not a platform setup link.

Django admin log entries are not an operational activity feed and are omitted
from the home: they neither cover governed service/API outcomes nor establish
current object disclosure. No new history query, analytics or task database is
introduced. Existing advanced records remain behind their authorized gateway.
The finite entry point and first owner-projected continuation below address
part of issue #35. Other module contributions, full Workforce operation and
governed recent outcomes remain separate acceptance outcomes.

## First owner-projected continuation: Workforce setup

UX-032 and [ADR 0126](../../architecture/decisions/0126-owner-projected-workforce-home-guidance.md)
add one **Team setup** panel for the selected exact Workforce-only version 1
edition. Other profiles and missing-workspace recovery keep their existing
behavior. Core reads no Workforce models; the public owner query derives
one minimized step and optional target identifier.

| Current owner state | Home continuation | Separate management authority absent |
| --- | --- | --- |
| No current Departments | Set up your Departments; open exact team structure. | Waiting for a team organizer; review structure only. |
| Departments, no current Positions | Prepare the team's Positions; check templates on Positions. | Waiting; review structure only. |
| A current draft opportunity | Prepare a volunteer opportunity; open that exact Position. | Waiting; review structure only. |
| Every current non-closed Position has published opportunity copy | Published; review Positions and their application windows. | Published; review team structure through its read-only destination. |
| Closed Positions or withdrawn/closed opportunities | Review existing Positions; no ready/published promise. | Review; use the read-only team structure destination. |
| Read-only organization or edition stage | Review retained team structure. | Same authorized read destination. |
| Overflow, incomplete owner state, persistent version movement or dependency/audit failure | Unavailable; refresh and retain permitted tools below. | No private facts or primary action. |

The provider requires complete structure-read field authority and checks
management separately. Missing read authority omits the contribution. Exact
organization/edition policy precedes state queries and is repeated before
existing minimized structure-read audit permits disclosure. No Department name,
Position title, holder, count, private rationale or personal calendar is loaded.
Bounds include retained records; retirement cannot hide an oversized structure.
Check retained Positions even when no active Department remains. A view-only
continuation always uses the read-only structure route, including Published and
Review states; the state itself is preserved.
The repeatable-read/version fence rejects moving state after at most one retry.

The panel has a text state, heading, purpose and one ordinary link when authorized.
Checked-at time names its time zone; refreshing observes later changes. No
automatic action, background polling, mutable task record or activity feed is
introduced. The home response is private and no-store. The destination
reauthorizes current scope and validates lifecycle/version independently.

Publication covers copy only. Application windows, Assignments, Availability,
Shifts, staffing and whole-event readiness remain outside the check; the panel
says so and retains Team workspace. Templates and actual publication remain on
their established owner pages. Existing rows do not prove overall completion.

Synthetic component checks cover seven CSS widths, text semantics and keyboard
continuation. Native tests separately cover query, policy, lifecycle and the
actual home-to-owner route. Neither supplies genuine 200% browser zoom,
representative screen-reader/person, restricted-runtime or #42 account acceptance.

## Workforce operating-home milestone

UX-032 and [ADR 0128](../../architecture/decisions/0128-workforce-operating-home.md)
extend the exact Workforce-only home through the existing operating workflow.
One owner-derived primary continuation leads a bounded attention list, with at
most one contribution from setup, Assignments, shared Availability and Shifts.
Each contribution is admitted independently using the complete authority of its
existing destination. Every destination authorizes again.

| Checked area | Representative continuation |
| --- | --- |
| Proposed Assignment | Review an exact proposal, or wait for another authorized organizer when independent approval is required. |
| Expired active Assignment | Review ending retained authority; explain the separate revocation authority where absent. |
| No retained Assignments after setup | Open Assignment planning; no staffing or onboarding readiness is inferred. |
| Missing or private-draft Availability | Waiting for volunteers to share; read-only review only, with no draft details. |
| Withdrawn or shared-empty Availability | Review the shared consequence; no reminder, editor impersonation or automatic replacement. |
| Changed Shift eligibility | Review the exact Shift using existing current Position/Availability rules. |
| Pending Shift claims | Review independent confirmation, or wait for another organizer for one's own claim. |
| Open underfilled or ended work | Review coverage or reconcile the ended open demand; no automatic risk acceptance. |
| Ended locked work | Review planned-work completion through the existing command and history. |
| Future or running locked work | Explain the retained schedule and localized next boundary without a new mutation. |
| Completed/cancelled work only | Review retained history; no whole-event all-clear. |
| Closing/read-only stage | Explain cleanup or retained review according to current owner lifecycle, without fabricated setup work. |
| Source movement, overflow or dependency/audit failure | Unavailable for that area; refresh while other admitted work remains usable. |

Operating risks and ended work precede pending decisions, setup and informational
history. No private name, hidden count, rationale, document value or exact
Availability period is loaded or shown. The response remains private/no-store.
Policy and owner/action state are repeated after required audit and at final
aggregate release. Those checks compare the complete bounded owner-source
signature again, including after another area's preparation or audit. The next
relevant Assignment expiry or Shift start/end also fences a prepared action;
crossing it during the final source probe requires refresh. Setup editability is
checked after all operating-area checks through the existing private-planning
and organization lifecycle projections. Lost editability returns read-only setup
without a target or management hint; unavailable evidence stays unavailable.
Setup-only recheck failure does not suppress another independently admitted area.
Checked times and decision boundaries name the time zone. Ordinary links, text
states, headings and list semantics remain usable by keyboard and without color.
This milestone adds no attendance, actual-time, generic task store or activity
feed. Maintained fictional scenarios cover ongoing and future work; existing
previews, human acceptance and other profiles remain separate.

Navigation items have code-owned labels, descriptions, stable task keywords,
and one of these presentation kinds:

- durable destinations are visible in their relevant group and may be pinned;
- contextual actions, including creation commands, live beside their owning
  resource, remain discoverable in the **Actions** search group, and are not
  pinnable; and
- authorized technical destinations remain searchable and appear behind one
  collapsed **Advanced records** disclosure and one home-page gateway.

Search matches tokens across labels, descriptions, and generic task keywords.
Ordinary vocabulary such as `users`, `accounts`, `staff`, `volunteers`, and
`board` must find the relevant authorized destination. Keywords contain no
tenant, person, or record values. Search and pins never expose a destination
that the current request is not authorized to load. Search leads with matched
tasks and reports authorized technical-record matches separately; the
**Advanced records** results stay collapsed until the operator asks for
them. Escape clears the current query. Pin and unpin controls are hidden behind
**Customize navigation** until requested, and search state is not persisted as
an accidental future filter.

## Surface separation and shared page frame

**My Maru** contains personal, self-owned work. **Administration** contains
organizer and platform work. Each renders only its own navigation registry and
pins, with one explicit surface switch where the account may use both. My Maru
leads with registration, applications, schedule, and **My Workforce**, then
presents lower-frequency personal destinations under **More from Maru**. My
Workforce remains one searchable and pinnable **Work** destination throughout
its Positions, Availability, and Shifts continuations. It does not show
Platform, Advanced records, or administrative context as personal menu
groups.

Every converted page has one `main` landmark, one H1, purpose guidance where
the task needs it, and one compact **Access** disclosure immediately after the
heading. The collapsed line names the resolved scope and policy kind; expanded
content explains the current principal's permitted actions and source without
turning the page into a manually maintained ACL. The embedded React workspace
owns this disclosure inside each active view so the Django host does not render
a duplicate before the application root.

A fixed-policy summary says **Rules for this page**. It explains the existing
owner's rules, without claiming that the page cannot offer its own approved
access-request, decision or removal actions. Only the unresolved-scope fallback
uses **This page** and explains that access cannot be changed from that page;
it reveals no guessed organizer label or generic management link.

## Plain language and purpose groups

ADR 0116 groups the existing authorized registry into Overview, People & teams,
Registration & shop, Applications, Places & equipment, and Settings. Account
controls and Advanced records are secondary. Empty groups are omitted; the current
group opens automatically. Native disclosure headings remain operable without
JavaScript. Search reveals matching ordinary tasks and preserves its separate
advanced-record disclosure. Clearing search restores the normal menu state.
Pins remain independently reauthorized shortcuts, never a second scope selector.

Use Team workspace for the Workforce overview and Application forms for generic
form setup. Activity intake uses Collect activity ideas, Ask for activity ideas,
Suggest an activity, and Activity idea. Old domain words remain search synonyms.
A new organizer must be able to understand the next action from the label and a
short concrete explanation. Domain identifiers and API names are unchanged.

Optional technical identifiers, versions, and policy evidence belong in labelled
advanced details. Required inputs, errors, consequential choices, and approval
responsibilities remain visible. A failed form must expose its invalid section;
progressive disclosure never hides required unresolved work. Links may use button
styling for primary navigation while retaining anchor semantics. Buttons perform
commands or change interface state. Do not add tab semantics to unrelated links.

The embedded Team workspace and Setup guide use the same language. The enabled
workflow label remains available under Technical setup details rather than leading
the ordinary setup instructions. Browser testing must distinguish actual selected-
event pages from template-only synthetic menu fixtures.

## Context and responsive shell

The organization/edition context control is a compact, shrinkable selector
that remains subordinate to the current page. Its label, value, and actions
must wrap or reflow without forcing page-level horizontal scroll. Embedded
Convention work uses that host control as its only visible selector. If the
host has no selected edition, the client submits its authorized initial edition
through the existing server-owned context action before rendering scoped work;
it does not show a contradictory client-only selection.

The shell has two implemented navigation presentations around a 1,100 CSS-pixel
threshold:

- above 1,100 pixels, the sidebar remains persistent; and
- at 1,100 pixels and below, it becomes a closed-by-default overlay drawer.

The drawer has a labelled open control, visible close control, backdrop,
`aria-expanded`, `aria-controls`, Escape-to-close, focus containment,
background-scroll locking, inert/`aria-hidden` background content, and focus
return. Motion respects the user's
reduced-motion preference. Content, forms, and record lists reflow within the
viewport; only an explicitly labelled data region may scroll horizontally.
Server-rendered mutation failures place keyboard focus on one summary alert,
then keep associated field errors and safe entered values in the owning form.

People, attendee, and access side workspaces use one modal-drawer contract:
labelled `dialog`/`aria-modal` semantics, initial focus on the close control,
Escape handling, a contained Tab sequence, inert and accessibility-hidden
background content, body scroll locking, backdrop close, and focus return to
the exact opener. A visual side panel is not treated as a passive
`complementary` landmark when it blocks the underlying page.

The acceptance matrix is 320, 390, 768, 958, 1,024, 1,280, and 1,920 CSS
pixels plus 200 percent browser zoom. Source and focused integration tests do
not replace authenticated rendered inspection at every width.

## Registration desk orientation

The high-frequency attendee-service destination is **Registration desk**. Its
first content is a bounded attendee queue with name/reference search, lifecycle
filter, count, pagination, and preserved detail-drawer context. Low-frequency
registration configuration follows the queue, while **Registration setup**
links to the canonical edition-owned Registration setup and account onboarding workspace. The canonical setup
destination is simply **Registration**; capacity policy remains a separate
**Capacity & waitlist** task. This naming keeps serving an attendee distinct
from changing the edition's configuration.

At narrow widths the attendee rows become labelled record cards containing the
attendee, reference, admission, state, and explicit open action. Desktop keeps
the semantic table. Neither presentation changes the API or authorization
decision.

The setup guide links organization, series, edition, registration, Workforce,
access, and readiness to their purpose-built routes. Programme & schedule,
Team inbox, and Live operations have one **Planned capabilities** panel labelled
**Not available yet**; they are not links until their workflow and authorization
contracts exist. Availability and Shifts instead have an explicit place in the
Workforce sequence below, where their dependency on real positions and
assignments can be understood.

## Workforce journey orientation

**Workforce** is one durable Convention work destination and the Registration
desk's handoff for team operations. It consumes the existing exact-edition,
bounded `workforce/structure` projection and presents one ordered sequence:

```text
Structure -> Positions -> Assignments -> Availability -> Shifts
```

Structure, current Position definitions, approved headcount, vacancies, and
active minimized holders are available read steps. The canonical Department management
structure route remains the only Department writer. A non-staff owner receives
purpose-built links only and is never directed into a specialist Django model
screen they cannot open; independently authorized Django staff may still use
clearly labelled temporary Position and assignment record links.

Availability is an implemented person-owned continuation. A person may keep a
private draft or deliberately share one complete exact-edition statement;
independently authorized organizers receive only the minimized current
planning consequence. It is never inferred from assignment. **Shift planning**
now lets an independently authorized organizer create Position demand, publish
suitable work, review claims, lock coverage, recover, cancel, and complete.
**My shifts** lets the person compare suitable open work and retain only their
own instructions and commitment state. The
[Shift planning and My shifts](shift-planning-and-my-shifts.md) contract keeps
claims distinct from confirmation and names check-in, timekeeping, broader
qualification, maximum-hours, lone-work, accommodations, notifications, and
schedule publication as later work.

## First continuous journey

The first corrected journey is:

```text
Administration home -> User accounts -> find or invite person
  -> invitation outcome -> Representation & access
```

**User accounts** is the durable identity destination. **Invite account** is
its contextual/search action, and **Invite a user account** is the inventory's
primary action; neither is an equal-weight permanent navigation row. Search
uses both account terminology and the common people/staff/volunteer synonyms.

Every invitation result explains that the new account is identity only. It
creates no organization membership, Board appointment, capability,
participation, registration, volunteer application, or payment. Where the
viewer is authorized, the outcome directs them to choose an organization and
continue through **Representation & access** rather than implying that the
account already belongs to a convention.

The Board page presents the existing command lifecycle as a visible three-step
progression:

1. create the Executive Board root;
2. invite at least two exact eligible controllers and wait for each response;
3. activate only after the existing two-controller and all-responses rules pass.

ADR 0040 remains authoritative for eligibility, disclosure, invitation,
response, cross-approval, activation, and audit behavior. This contract changes
only how an authorized user finds and understands that workflow.

## Verification and open evidence

Each converted journey requires empty, populated, denied, validation, stale,
dependency-failure, and success states; keyboard completion; automated
accessibility analysis; and rendered evidence across the acceptance matrix. A
top task must be reachable from its relevant home in no more than two
navigation decisions without a direct URL.

Focused source, frontend, integration, and authenticated browser coverage now
includes the responsive drawer and breakpoint, background isolation, task-
first search and customization, personal/administrative separation, shared
page framing, User accounts and invitation presentation, Board progress,
purpose-built setup links, the owner-role Registration desk, modal focus and
Escape return, the Workforce read journey, non-staff specialist-link exclusion,
denial non-disclosure, and automated axe checks for the Registration and
Workforce views. The Shift journey additionally passes an authenticated owner-
and-volunteer rehearsal at 1,280 and 390 CSS pixels, including task discovery,
drawer background isolation, focus return, one H1 and one `main`, no duplicate
identifiers, and no horizontal overflow. The complete rendered width/zoom and state matrices,
representative screen-reader evidence, mutation-role rehearsals, and release
accessibility acceptance remain open gates.

### Narrow navigation opener

At drawer widths the Menu opener occupies its own row before page content. It
must not float over fields or submit buttons. Opening still uses the existing
modal drawer, focus containment, Escape and return-focus behavior; without
scripts native navigation remains available.

## Typed dates and coherent setup actions

Under UX-007, UX-016, UX-029 and UX-031, creation is visible beside its owning
inventory and one ordinary task label is reused in its navigation, breadcrumb,
page heading and action. The volunteer setup task is **Set up a volunteer team**.
Dynamic record titles still identify their exact organization or edition.

Browser date fields are directly editable as `YYYY-MM-DD`; local date/time
fields use 24-hour `YYYY-MM-DD HH:mm:ss`, with no browser-dependent AM/PM picker.
Existing split application controls keep a typed ISO date and labelled 24-hour
minute clock. Owning fields retain precision, time-zone, DST and error rules;
minute-precision workflows accept zero seconds and reject nonzero seconds.
API UTC/offset serialization is unchanged. Invalid input remains correctable.
Access sharing and replacement show a field-associated parsing error before any
request, retain the entered expiry and reason, and allow correction and resubmission.
Choice groups expose legends and individual labels, with the control beside
its text. Theme-aware action colors apply to visited and unvisited links.
Panel count/status badges use a matching theme-aware foreground and background.
Existing volunteer workspaces distinguish provisioning setup from suspended
accountable access: suspended work points to review and the approved recovery
process, without offering initial invitation/activation instructions or implying
that the workspace may resume. Active workspaces retain their team destination;
missing or unknown accountable state is unavailable.
