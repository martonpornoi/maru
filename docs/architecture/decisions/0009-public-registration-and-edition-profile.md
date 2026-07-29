# ADR 0009: Public registration and purpose-partitioned edition profiles

- Status: Accepted
- Date: 2026-07-27
- Requirements: IDN-001, IDN-002, IDN-006, REG-001, REG-002, REG-011,
  REG-012, REG-013, KNO-004, PRI-001, PRI-003, PRI-005

## Context

Registration must be a public entry point rather than requiring staff to
pre-create every account and participation. A returning attendee also needs to
choose the edition they are joining instead of inheriting an unrelated staff
workspace.

Registration needs contact, address, legal-name, birth-date,
emergency-contact, character, and optional media data. Some of these fields are
C2 personal data; the legal-name link, full date of birth, and emergency
contact are C3 restricted. Putting them on the global platform account would
silently share one organizer's collection with another. Treating volunteer
department or a special ticket as attendee-entered profile text would also
duplicate and weaken authoritative operational state.

## Decision

Provide one public registration entry and edition picker backed only by active,
currently open registration configurations.

- An anonymous person may choose an open edition, create one platform login,
  and submit registration in one transaction. Existing-account collisions use
  a generic sign-in path and do not modify the account.
- An authenticated returning person sees open editions and whether they are
  already registered. Registration creates the edition participation when it
  does not yet exist.
- Registration profile data belongs to the resulting registration and edition,
  not the platform account. It is never reused into another edition without a
  future compatible-purpose review and explicit attendee action.
- Typed registration-profile fields carry fixed purpose, classification,
  visibility, and retention notice. C3 values are excluded from Front Desk,
  attendee-directory, search, audit payloads, logs, and ordinary registration
  projections.
- The optional attendee directory is a separate, specific consent. It exposes
  only display name, pronouns, species, fursuit name, and an optional protected
  fursuit image to other confirmed or checked-in attendees of the same edition.
  Address, legal name, birth date, emergency contact, email, phone, and Telegram
  handle are never part of that rendition.
- Organizers can create ordered, versioned form sections and assign
  configurable questions to them. Sections copy with editions and templates
  under ADR 0007.
- Volunteer department comes from participation capacity or future workforce
  assignment. Special or “infinity” ticket-holder status comes from admission
  entitlements. Self-service views may present those derived facts as profile
  sections, but attendees cannot assert them through registration answers.
- Uploaded fursuit media is private by default, type/size constrained, and
  served only through an authorization-checking endpoint. It is not placed
  under an unrestricted media URL.

The initial implementation records collection and retention notices but does
not claim jurisdiction-specific legal approval. Deploying organizations must
review those notices and age/guardian policy before production.

## Consequences

Public onboarding can create the account, edition relationship, profile, and
registration without a staff-only prerequisite. Tenant and edition scope stay
explicit, historical submissions remain versioned, and optional publication is
separate from service processing.

Full birth dates and emergency contacts introduce a restricted-data boundary.
Their ordinary read workflows remain deliberately narrow until capability,
step-up, audit, retention execution, and jurisdiction-specific minor policy are
implemented. Bootstrap superuser database access remains a residual
operational risk and is not a production profile-management workflow.

## Alternatives considered

- Store all fields on `Account`: rejected because organizer-specific collection
  would become a global profile and violate controller boundaries.
- Model every profile field as an unrestricted form answer: rejected because C3
  fields require a typed restricted boundary and cannot safely appear in
  generic answer projections.
- Publish every opted-in field to the attendee directory: rejected because
  consent must be specific and contact or legal data is unnecessary.
- Let attendees enter department or ticket status: rejected because capacities,
  assignments, products, and entitlements are authoritative.
- Require staff to create accounts first: rejected because registration itself
  is a primary public acquisition and service workflow.
