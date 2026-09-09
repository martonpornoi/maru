# ADR 0092: Build one dormant, progressively enhanced timetable editor

- Status: Accepted
- Date: 2026-09-08
- Extends: ADRs 0026, 0055, 0081 and 0088
- Requirements: SCH-003, SCH-004, SCH-007 through SCH-011, PRG-008,
  UX-005 through UX-008, UX-029, AUD-001, AUD-003 and NFR-013
- Parent: [#48](https://github.com/martonpornoi/maru/issues/48)
- Child: [#85](https://github.com/martonpornoi/maru/issues/85)

## Context

The delivered Scheduling kernel preserves immutable alternatives and explicit
physical reservations but has no planner-facing projection or editor.
Programme Operations must provide an accessible editor before its staffing,
release, continuity and guided activation children can be accepted. Neither
current adoption manifest admits these capabilities, and Scheduling runtime
relations remain SELECT-only. Exposing a convenient route would not establish
the missing authority, runtime containment or end-to-end workflow.

## Decision

Build a server-owned planning projection and command adapters, plus a
progressively enhanced editor in the existing management-shell grammar.
Ordinary labelled forms are the complete interaction path. Pointer placement
and movement prefill that same form and require explicit preview/save; they
never become a second writer. Stable occurrence identities and immutable
candidate revisions remain the source of comparison, recovery and conflict
evidence. The browser holds transient unsaved input only and never becomes a
schedule or availability source of truth.

Private labels and inspector layers come through independently authorized,
bounded owner queries. History and conflict reads have their own Scheduling
field ceilings. Preview evaluates the exact proposed draft using current
declared owner sources without storing or reserving it. Save rechecks the
existing command preconditions; a preview is not permission, an availability
lock or a guarantee that sources have not changed. Show unsupported checks and
old evaluation evidence explicitly.

The [page contract](../../product/page-contracts/programme-timetable-planning.md)
owns task behavior, states, routes, field boundaries and accessibility evidence.
This child does not mount a production route, expose navigation, add a profile,
widen current manifests or grant runtime writes. A test-only composition may
exercise real owner commands behind the existing isolated-test admission
guards. It must be unreachable from production routing and must be described
as synthetic domain/component evidence, not provisioned runtime acceptance.
The guided integration child must provide genuine runtime containment and the
complete exact-version profile before mounting the accepted route.

## Consequences

The editor can be tested and delivered coherently without advertising an
incomplete Programme product. Native forms keep pointer and keyboard paths
equivalent and avoid a new frontend dependency. Domain tests and browser
rehearsals can prove their respective contracts, but production profile and
runtime-role activation remain explicitly unproved until their later child.
Existing Scheduling mutations, history and Venue ownership are reused; no
schema change is required merely to draw or edit a draft.

## Alternatives considered

- Activate Programme Operations early: rejected because mandatory continuations
  and runtime/continuity acceptance are missing under ADR 0081.
- Expand `full_convention@1` or add a temporary editor profile: rejected because
  this silently changes adoption meaning or introduces an unsupported workflow.
- Make drag-and-drop the primary writer with a separate keyboard implementation:
  rejected because validation, recovery and accessibility could diverge.
- Save a draft on every pointer move: rejected because preview, reason and
  version consequences must be deliberate and accountable.
- Treat owner-login browser tests as runtime proof: rejected because they bypass
  the database-role boundary that the activation child must actually verify.
