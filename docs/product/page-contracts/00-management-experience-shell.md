# Cross-cutting contract: Management experience shell

- Status: Focused shell hierarchy, page framing, personal-surface separation,
  User accounts-to-Board continuity, owner-rehearsed Registration desk, and the
  Workforce journey through Shift planning and My shifts implemented; full mutation-role,
  state-matrix, width/zoom, and release accessibility evidence remains pending
- Canonical authenticated route: `/admin/`
- Requirements: UX-001 through UX-013, UX-019, UX-020, UX-024, UX-026, UX-027,
  UX-029, and NFR-001 through NFR-004
- Decisions: ADRs 0026, 0027, 0039, 0040, 0049, and 0055

## Purpose and boundaries

The management shell gives each authenticated operator a small, teachable set
of authorized tasks without creating a second administration product. It
retains the canonical `/admin/` route family, server-owned authorization,
selected organization and edition context, purpose-built workflows, and
authorized Django specialist records.

Presentation never grants authority. Every link is resolved and authorized on
the server before disclosure, every destination authorizes again, and selected
context remains a convenience rather than an access-control decision. The
shell introduces no new account kind, organization relationship, capability,
writer, audit boundary, or client-side source of truth.

## Task-oriented navigation and home

The default navigation prioritizes durable, role- and context-relevant
destinations. The administration home leads with current work and **Continue
setup**, then recent work and a small set of primary destinations. It does not
repeat the exhaustive Django application/model directory.

Navigation items have code-owned labels, descriptions, stable task keywords,
and one of these presentation kinds:

- durable destinations are visible in their relevant group and may be pinned;
- contextual actions, including creation commands, live beside their owning
  resource, remain discoverable in the **Actions** search group, and are not
  pinnable; and
- authorized technical destinations remain searchable and appear behind one
  collapsed **Specialist records** disclosure and one home-page gateway.

Search matches tokens across labels, descriptions, and generic task keywords.
Ordinary vocabulary such as `users`, `accounts`, `staff`, `volunteers`, and
`board` must find the relevant authorized destination. Keywords contain no
tenant, person, or record values. Search and pins never expose a destination
that the current request is not authorized to load. Search leads with matched
tasks and reports authorized technical-record matches separately; the
**Specialist records** results stay collapsed until the operator asks for
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
Platform, Specialist records, or administrative context as personal menu
groups.

Every converted page has one `main` landmark, one H1, purpose guidance where
the task needs it, and one compact **Access** disclosure immediately after the
heading. The collapsed line names the resolved scope and policy kind; expanded
content explains the current principal's permitted actions and source without
turning the page into a manually maintained ACL. The embedded React workspace
owns this disclosure inside each active view so the Django host does not render
a duplicate before the application root.

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
