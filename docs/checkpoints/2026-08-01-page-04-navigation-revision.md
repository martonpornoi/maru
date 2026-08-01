# Checkpoint: Page 4 progressive navigation revision

Date: 2026-08-01
Branch: `codex/page-04-create-convention-series`
Requirements: IDN-011, UX-013, UX-017, UX-018, UX-019, PRI-001
Decision: ADR 0036

## Outcome

Before inspecting Page 4, the product owner requested that every mounted page
be reachable from the shared menu and that the sidebar stop sitting behind a
large left margin. The preserved pre-reset administration shell was used as a
behavior and spacing reference.

The global menu still presents **Organizations** with its adjacent **+ Add**.
When an authorized view has an organization, a second section names that
organization and exposes **Organization record** plus **Convention series**
with its scoped **+ Add**. Page 3 marks its record destination current. Page 4
marks its series add action current. A Closed organization retains navigable
record and series-section destinations but omits the unavailable creation
action. Pages 1 and 2 do not invent organization context.

The administration grid now takes the available width and uses bounded page
padding. Its content column remains readable while the sidebar starts near the
viewport edge. The existing narrow breakpoint stacks the menu and content.

## Scope and safety

This revision does not add a global Convention series collection. The
organization is supplied only by the already-authorized Page 3 or Page 4 view;
the navigation neither queries another tenant nor grants authority, accepts a
parent selector, or changes creation behavior. No model, migration, API,
service, audit, or lifecycle rule changed.

No form was submitted during browser verification. Read-only database checks
show one platform account, one organization, zero series, zero editions, and
one original audit event in `maru_rebuild_empty`.

## Verification

- 79 focused Page 1–4 integration checks pass against PostgreSQL 17, including
  global-only and selected-organization menus, exact current state, scoped
  destinations, and Closed-parent omission.
- The complete backend, coverage, formatting, lint, strict typing, Django,
  migration drift, OpenAPI, generated client, preserved frontend, build, and
  documentation gates pass.
- At 1920 by 1080, Page 4's sidebar starts 40 pixels from the viewport edge,
  the content remains bounded, and document width does not exceed the viewport.
- At 390 by 844, the sidebar and content stack at 16-pixel page padding with no
  horizontal overflow.
- Browser semantics expose one Platform administration navigation, a named
  MaruCon region, all four destinations/actions, and exactly one current item.
  The scoped menu action successfully navigates from Page 3 to Page 4, and the
  browser reports no warnings or errors.

## Recovery and next gate

This is a Page 4 revision on the existing branch and introduces no database
recovery step. The pre-reset state remains at commit `548f15a` on
`codex/pre-reset-20260731`. The owner should now inspect Page 4. Page 5 remains
blocked on that acceptance.
