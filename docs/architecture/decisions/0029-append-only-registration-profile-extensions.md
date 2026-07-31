# ADR 0029: Append-only registration profile extensions

- Status: Accepted
- Date: 2026-07-31
- Extends: ADR 0007 copy-on-write registration configuration and ADR 0009
  purpose-partitioned edition profiles
- Requirements: REG-001, REG-002, REG-012, REG-013, REG-015, REG-021,
  REG-022, KNO-004, PRI-001, PRI-003, PRI-009, NFR-001 through NFR-003

## Context

An active registration form and every submitted answer snapshot must remain
immutable. Real organizers nevertheless discover missing current information
after people register. Requiring a new registration or rewriting its original
schema would either burden attendees or destroy historical meaning.

Fields also have different writers. An attendee may supply a newly requested
address detail, registration staff may record an internal verification, and
some current fields may be maintained by either. A generic editable JSON blob
cannot enforce that policy or retain amendment evidence. Staff-owned outcomes
such as Infinity admission must not become self-asserted checkboxes.

## Decision

Add an edition-owned registration-profile extension catalog separate from the
immutable registration submission.

- A field version records stable key, label, help, type, options, purpose,
  C1/C2 classification, attendee visibility, writer policy (`attendee`,
  `registration_staff`, or `attendee_and_staff`), requiredness, ordering,
  source template/prior-edition provenance, review state, and active or retired
  lifecycle.
- Field versions are immutable after activation. A changed definition is a new
  version retaining the stable key and supersession link.
- A target-edition field version may retain approved-template or prior-edition
  provenance. It remains an independent definition and cannot become active
  until reviewed in the target edition.
- A value write appends a revision containing the exact field version, typed
  value, subject registration, actor, source channel, server time, and a
  mandatory reason for staff-on-behalf changes.
- Current values are projections of the latest revision; original
  `RegistrationSubmission.schema_snapshot` and answers never change.
- Self-service returns only active attendee-visible fields and accepts only
  attendee-capable writer policies for the authenticated registration owner.
- Staff operations require exact tenant/edition scope and registration-service
  authority, return staff-visible fields, enforce writer policy, and audit
  reads and writes without copying values into audit metadata.
- Retiring a field stops new ordinary writes but preserves definitions and
  revisions under retention policy.
- Authoritative roles, capacities, products, entitlements, payment facts, and
  restrictions remain derived domain facts. They cannot be implemented as
  extension answers.

The existing registration-question visibility is also enforced at every
bundled form and service boundary: attendee submissions cannot see, satisfy,
or send registration-staff-only questions.

## Consequences

Organizers can ask for missing current information without mutating the
historical registration. Attendees and staff see one profile-completion area
with explicit purpose and ownership, and audits show who changed which field
without logging the value.

The extension catalog is deliberately narrower than the future general form
builder. It supports current C1/C2 registration-profile information only.
Restricted C3/C4 data still needs a purpose-specific typed domain and access
policy.

## Alternatives considered

- Edit `RegistrationSubmission.answers`: rejected because it rewrites
  historical meaning and breaks the immutable evidence boundary.
- Activate a new registration configuration and silently attach old
  registrations to it: rejected because prices, agreements, eligibility, and
  questions would acquire meaning the attendee never submitted.
- Store current additions in one profile JSON object: rejected because field
  purpose, writer policy, validation, history, and retention would be opaque.
- Add an attendee-editable Infinity checkbox: rejected because admission
  benefit remains an organizer-controlled product entitlement.
