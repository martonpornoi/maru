# Cross-cutting contract: Management experience shell

- Status: First shell, home, User accounts, invitation, and Board-continuity
  slice implemented and focused-test verified; full browser, accessibility,
  state-matrix, and owner evidence pending
- Canonical authenticated route: `/admin/`
- Requirements: UX-001 through UX-013, UX-019, UX-024, UX-026, UX-027,
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
that the current request is not authorized to load.

## Context and responsive shell

The organization/edition context control is a compact, shrinkable selector
that remains subordinate to the current page. Its label, value, and actions
must wrap or reflow without forcing page-level horizontal scroll.

The shell has two implemented navigation presentations around a 1,100 CSS-pixel
threshold:

- above 1,100 pixels, the sidebar remains persistent; and
- at 1,100 pixels and below, it becomes a closed-by-default overlay drawer.

The drawer has a labelled open control, visible close control, backdrop,
`aria-expanded`, `aria-controls`, Escape-to-close, focus containment,
background-scroll locking, and focus return. Motion respects the user's
reduced-motion preference. Content, forms, and record lists reflow within the
viewport; only an explicitly labelled data region may scroll horizontally.

The acceptance matrix is 320, 390, 768, 958, 1,024, 1,280, and 1,920 CSS
pixels plus 200 percent browser zoom. Source and focused integration tests do
not replace authenticated rendered inspection at every width.

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

The first slice has focused source and integration coverage for the responsive
drawer, task navigation/home, User accounts and invitation presentation, and
Board progress handoff. Broader management journeys, the complete rendered
width/zoom matrix, representative screen-reader evidence, and owner rehearsal
remain open release gates.
