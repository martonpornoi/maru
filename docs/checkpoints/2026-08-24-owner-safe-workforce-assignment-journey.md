# Owner-safe Workforce assignment journey milestone

Date: 2026-08-24

Phase: Production consolidation and management-experience recovery

Requirements: HR-007, HR-008, HR-010, HR-013, IAM-005, IAM-012, IAM-013,
UX-020, UX-029, AUD-001, AUD-005, INT-001, NFR-001 through NFR-004, and
NFR-008

Decision: ADR 0076

## Outcome

Maru now has one coherent owner-facing **Assignment management** journey after
Organization structure and Position management. A current controller starts
from an exact-edition Position, chooses a relationship-bounded known person,
records an effective interval and inspectable reason, and proposes rather than
silently grants responsibility. Proposed assignments reserve approved
headcount.

A genuinely different current controller may approve or reject the proposal
after fresh step-up authentication. Approval rechecks current Position,
headcount, person, onboarding, edition, RoleBundle provenance, and controller
authority before activating the exact role and participation capacities in one
transaction. Rejection grants nothing. A current revocation controller may end
an active assignment, revoke its linked role, complete only capacities no other
active assignment still needs, and retain the full decision history.

The purpose-built overview, proposal, detail, approval, rejection, and ending
pages share the same commands as the strict versioned API. **My Workforce** is
a separate minimized subject view. Staff Console and Position management point
to the same workflow. Availability and Shifts retain truthful places in the
journey but remain labelled **Not available yet**.

Living documentation now uses purpose names for management surfaces. Numeric
filename prefixes remain only for stable ordering and incoming links; they are
not user-facing page or journey names.

## Decisions

- Proposal creates no role, capacity, participation, capability, or schedule,
  so incomplete onboarding may be visible at proposal time. Approval is the
  grant boundary and fails closed unless every current prerequisite passes.
- Decision actors are derived from separate authenticated sessions. Neither
  browser nor API input can select an approver, and the proposer cannot decide
  their own proposal.
- Step-up and authorization happen before decision input parsing or scoped
  record disclosure.
- Assignment reasons and controller evidence belong beside the authorized
  organizer workflow. The subject view deliberately omits them.
- Intended expiry is not revocation. An overdue active assignment remains
  **Expired - ending required** until the explicit ending command succeeds.
- Assignment is responsibility and authority evidence; it does not imply a
  person's availability or a scheduled shift.

## Changed areas

- Workforce application commands, query projections, closed inputs, forms,
  HTML views, strict API adapters, serializers, routes, services, effects, and
  inspection-only specialist administration;
- PositionAssignment lifecycle evidence, immutable command receipts, database
  guards, runtime trigger/readiness fingerprints, and migration `0011`;
- relationship-bounded candidate lookup and minimized personal assignment
  projection;
- Staff Console and My Maru continuations, generated browser assets, OpenAPI,
  and generated TypeScript schema types; and
- product requirements, page contracts, module and architecture guidance,
  roadmap, current handoff, and ADR 0076.

## Verification

- five assignment command/browser-adapter/API/database integration cases passed
  in 71.28 seconds; the direct lifecycle case passed again in 54.01 seconds;
- the executable database-role and hardening gate passed 264 tests in 543.23
  seconds, including exact trigger readiness and runtime-role containment;
- the canonical unit suite passed 1,990 tests;
- Staff Console Vitest passed 28 tests; TypeScript checking and the production
  Vite build passed, and the generated host asset was refreshed;
- OpenAPI regenerated and validated with zero schema errors; the existing 18
  enum-name collision warnings remain visible, and generated TypeScript API
  types were refreshed;
- Django system check passed with only expected local `identity.W001`;
  migration `0011` applied cleanly and `makemigrations --check` reported no
  drift;
- whole-tree Ruff formatting and lint, pydoclint, the custom Python
  documentation policy over 367 source files, strict mypy over 357 source
  files, and whitespace validation passed; and
- documentation policy passed for 325 Markdown files and 204 unique
  requirement identifiers, and the warning-fatal Sphinx/AutoAPI build
  succeeded.

A fresh authenticated visual-browser pass is not recorded. The local server
started cleanly, but the available in-app browser rejected localhost
navigation under its URL policy after its initial connection-refused page. The
automated browser-adapter case uses distinct authenticated proposer and
approver clients and verifies the step-up redirect, self-decision exclusion,
private responses, and minimized subject view; it is not represented as
two-human visual acceptance.

## Data, migration, and deployment notes

Migration `0011_owner_assignment_commands` is additive for internally
consistent legacy rows and installs a stopped-writer transition boundary.
Governed assignment rows may move only `proposed -> active`, `proposed ->
rejected`, and `active -> ended`, each with exactly one matching next-version
receipt and state evidence. Direct deletion, immutable proposal changes,
skipped states, malformed linked-role evidence, and receipt mutation are
rejected even when ORM validation is bypassed.

After the first governed write, recovery fixes forward or restores the complete
database to a mutually consistent pre-write point. The assignment guard is not
reversed independently. This milestone is local repository evidence, not a
production migration, deployment, recovery certification, or authority cutover.

## Known risks and incomplete work

- A two-human, two-browser owner rehearsal and the complete UX-029 width, zoom,
  keyboard, screen-reader, empty, failure, stale, read-only, and mutation-role
  matrix remain release work.
- Qualifications, person-owned availability, shifts, time records, assignment
  replacement and bulk operation, approval notifications, and onboarding-review
  orchestration remain absent.
- Representative stopped-writer cutover, rollback/fix-forward rehearsal,
  restore/PITR, deployment, worker supervision, load, telemetry, privacy,
  safeguarding, operator training, and external acceptance remain production
  gates.

## Recommended next actions

1. Perform the fresh two-owner visual rehearsal, including narrow layout,
   keyboard focus, stale submission, incomplete onboarding, and subject-view
   privacy.
2. Specify the person-owned Availability contract against HR-009, SCH-001, and
   SCH-005 before adding controls: visibility, recurrence, exceptions, time
   zone and daylight-saving behavior, privacy, retention, concurrency, and
   recovery.
3. Implement the smallest useful Availability slice in **My Workforce** and a
   minimized organizer projection, then design transactional Shift demand,
   claim, confirmation, removal, completion, and publication.
