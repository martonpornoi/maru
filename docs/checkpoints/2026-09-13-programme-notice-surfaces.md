# Programme change-notice surfaces and bounded discovery

Date: 2026-09-13. Issue #104, inside #48's existing delivery decomposition.
Branch: `codex/programme-change-communication`, based on protected PR #106.
This is local implementation/component evidence, not protected delivery or
PostgreSQL workflow certification.

## Outcome

- A page contract precedes dormant shared-shell organizer and personal adapters.
  Ordinary strict forms call existing preview, preparation, independent
  approval/rejection, manual handoff and exact-person acknowledgement boundaries.
- Personal forms accept no alternate recipient or organizer reason. Commands
  preserve the submitted source/version/key; redirects return to freshly checked
  detail rather than resubmitting a mutation. Invalid input retains bounded safe
  field values; stale/conflict and dependency failures disclose no old package.
- The manual message is a copyable recipient-only link, not the organizer page
  or its rationale. Copying, review, handoff and acknowledgement remain distinct.
  No provider delivery, accepted work, attendance or profile activation is implied.
- Inventory candidates are exact-edition and bounded to 256, optionally narrowed
  by release. Personal candidates filter actual recipient and approval in SQL.
  Every detail recomposes current purpose; stale/denied entries expose no hidden
  identifiers or counts. Source failure or overflow prevents partial output.
  This is not a delivery-completeness report. Repeated final candidate admission
  precedes disclosure. Outer transactions are rejected to avoid accumulating
  differently ordered person locks across complete owner queries.
- Current timetable/run-sheet links authorize again. #108 owns integrating the
  labelled reference controls with normal authorized task selection; this
  component does not assert that a coordinator should discover database UUIDs.

## Verification actually performed

- Full non-database suite: **5,549 passed in 34.44 seconds**, two existing URLField
  warnings, before the final small presentation/link-message refinement.
  `.tools/issue104-notice-ui-all.xml` retains this run.
- Final focused form/HTTP/discovery set: **45 passed in 1.35 seconds**, including
  shared-shell reuse isolation, personal rationale exclusion and link-only handoff.
- Strict mypy: 576 sources passed before the final presentation refinement.
  Ruff format/lint passed across 1,112 files; semantic docs checked 598 sources.
  Documentation structure checked 478 Markdown files before this checkpoint.
- `test_programme_operator_outputs.py`: 14 tests **collected only** in 0.61s;
  no database fixture or PostgreSQL suite was executed. Its maintained lifecycle
  assertions now also cover forged native facts, pre-approval handoff denial,
  personal discovery and competing reviews. Two independent connections use
  15-second lock, 30-second statement, 10-second barrier and 45-second future
  bounds. These timeouts are safeguards, not measured passing timings.

## Synthetic browser evidence and fixes

Used a loopback-only fixture, `.tools/issue104_notice_browser.py`, with real
Django forms/templates/CSRF and deliberately simulated domain queries/commands.
No database, real identities, actual grant changes, provider or production route
was used. Ports 51383, 53392, 52004 and finally 56874 were successive temporary
instances, each superseded fixture stopped before replacement.

Observed organizer preview, whitespace-reason validation and successful form
recovery, preparation with no self-approval button, independent reviewer approval,
manual link handoff, personal acknowledgement through Enter, and acknowledgement
before handoff in an earlier fixture pass. The personal page excluded organizer
rationale and other actor identifiers. Validation focused `notice-message` and
kept the field error linked. These role/state simulations do not prove real
database authorization or concurrency.

Reflow observations at 320, 390, 768, 958, 1024, 1280 and 1920 CSS pixels had
document scroll widths of respectively 305, 375, 753, 943, 1009, 1265 and 1905:
no page-level horizontal overflow. Checked pages had one H1/main and no duplicate
IDs; personal browser warning/error logs were empty in the final observation.
Visible screenshots exposed low-contrast inherited H3 colors; the owning CSS now
uses the theme foreground, observed as `rgb(7, 27, 58)` in light mode. Raw changed
field labels were replaced with readable labels such as Delivery starts/ends.

The initial fixture reused one mocked shell context and revealed cross-request
context accumulation. The view now copies shell context before composing each
response, with a regression test that a later denial carries no prior detail.
An initial browser POST failed CSRF because test settings admitted only
`testserver`; only the fixture's exact loopback host was admitted for the corrected
run. CSRF protection was not disabled. Normal application settings are unchanged.

## Remaining gates and next action

Run one clean exact-head deferred-mode certification and protected PR delivery
before closing #104. PostgreSQL workflow, native negatives/races, runtime roles,
migration reverse/reapply and populated recovery remain unexecuted #102 debt.
The earlier approved schema-only metadata observation is separate evidence and
was not repeated. Keep #97 logical recovery, #92 genuine human/zoom/screen-reader
and #109 integrated synthetic acceptance open. No automated role simulation
substitutes for those gates. Continue to #107 continuity and #108 guided surfaces
only after #104's intended protected delivery is verified.
