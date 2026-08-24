# Governed Position management milestone

Date: 2026-08-23

Phase: Production consolidation and management-experience recovery

Requirements: HR-007, HR-010, HR-011, HR-012, UX-020, UX-029, AUD-001,
AUD-005, INT-001, NFR-001 through NFR-004, and NFR-008
Decision: ADR 0075

## Outcome

Maru now has one purpose-built, owner-facing **Position management** workflow
for an exact event edition. An authorized structure manager can create a
responsibility from a published Position template, completely replace its
operational details, manage its separately publishable volunteer opportunity,
inspect the reasons for changes in place, and close a dependency-free Position
without entering a generic Django model form.

The Workforce journey presents Structure, Positions, Assignments,
Availability, and Shifts in their real dependency order. Position management
is the first mutation-capable continuation. Assignments remain a separate
dual-control outcome; Availability and Shifts remain clearly labelled as not
available rather than appearing as broken controls.

Living documentation and product copy now name management surfaces by purpose,
including **Organization structure**, **Position management**, and
**Registration setup and account onboarding**. Stable numeric filename prefixes
remain only for document ordering and incoming links. Accepted decisions,
append-only checkpoints, and frozen ledgers retain their original terminology
as historical evidence.

## Product and integrity boundary

One creation transaction writes the planned Position, private draft
opportunity, exact typed resource binding, shared structure version, immutable
reasoned receipt, minimized audit, domain event, and outbox message. Template,
RoleBundle, Department, scope, code, and capacity mapping are immutable.
Reporting remains same-edition and acyclic; headcount cannot undercut proposed
or active assignments.

Opportunity draft, publication, temporary closure, republication, and final
withdrawal are explicit. Browser opening and closing times use the edition's
IANA time zone and reject daylight-saving gaps or ambiguities. API timestamps
require an explicit UTC offset. Publication grants no participation,
assignment, role, capability, or schedule commitment.

Position closure requires the exact current title and a retained reason. It is
one-way and refuses proposed or active assignments, current direct reports, and
current or future Position-scoped authority. Related history is retained, and
the opportunity closes unless already closed or withdrawn.

Workforce migration `0010_position_structure_commands` installs the version,
closure, receipt, trigger, and evidence contract. It preflights every existing
Position/template/RoleBundle pairing. Internally consistent legacy rows keep an
unknown creation version and begin governed evidence only at their first real
change. The preserved empty-organization recovery bootstrap uses this same
Position command; its sole provenance exception is constrained to the first
Convention Chair at structure version 1 and is not exposed through HTML or API.

Position and Volunteer opportunity Django records are inspection-only. Shared
HTML and strict API adapters repeat authorization and call the same commands.
The runtime readiness catalog fingerprints the new functions and exact trigger
attachments, including both conditional receipt routes.

## Verification recorded for the milestone

- governed Position command/API/HTML, exact-edition lock, service, inspection-
  only admin, and clean-onboarding focus: 27 passed in 122.23 seconds;
- broad Workforce integration/unit regression gate, including authorization,
  scope, receipts, migrations, runtime readiness, onboarding, assignments,
  shifts, and availability: 361 passed with 3,916 unrelated tests deselected in
  1,384.74 seconds;
- exact structure/readiness catalog and tamper matrix: 61 passed;
- shared server-rendered validation-focus asset plus Position HTML follow-up:
  7 passed in 58.68 seconds;
- OpenAPI regenerated and validated with zero schema errors; the existing 18
  enum-name collision warnings remain visible;
- generated TypeScript API types refreshed; type check passed; Vitest passed
  28 tests; production Vite assets rebuilt;
- Django system check passed with only the expected local invitation-encryption
  warning; migration drift reported no changes;
- Ruff and pydoclint passed; mypy found no issues across 353 source files;
  repository whitespace validation passed;
- the warning-fatal documentation build and documentation policy passed for
  322 Markdown files and 204 unique requirement identifiers;
- authenticated Chrome as the non-staff Convention Chair rendered the complete
  purpose-named Position overview/detail path with one H1, one `main`, and no
  desktop horizontal overflow. A deliberately invalid update changed no data
  and moved keyboard focus to its summary alert.

## Remaining boundaries

This milestone does not implement assignment proposal, independent approval,
assignment ending or replacement, onboarding review orchestration, person-owned
availability, shifts, timekeeping, notifications, or Position-template
authoring. The next highest-impact product outcome is an owner-safe assignment
journey with a genuinely separate approver session and directly inspectable
prerequisites and reasons.

Production deployment, stopped-writer cutover, representative restore and
point-in-time recovery, complete responsive/zoom/keyboard/screen-reader states,
and external owner acceptance remain release gates.
