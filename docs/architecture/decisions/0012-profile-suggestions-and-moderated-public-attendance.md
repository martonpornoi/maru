# ADR 0012: Edition profile suggestions and moderated public attendance

- Status: Accepted
- Date: 2026-07-28
- Requirements: IDN-006, PRI-001, PRI-003, PRI-005, REG-002, REG-012,
  REG-014, REG-015, REG-016, UX-006, UX-007
- Supersedes: the confirmed-attendee-only directory rendition in ADR 0009

## Context

Returning attendees should not have to retype stable contact and profile data
every year. At the same time, a new registration must not rewrite a closed
edition, silently share an organizer's data, carry publication consent into a
new context, or turn the platform account into a global organizer profile.

An attendee can bring more than one fursuit. Profile and fursuit images need a
review boundary before public display, while making an attendee wait again for
the exact same already-approved file adds no safety. Spoken languages need
interoperable structured values for future badge rendering. Pronouns need a
helpful predefined vocabulary without pretending that a closed list can
describe every person.

The convention also wants a public opt-in attendee list, not a private social
directory available only after another attendee pays.

## Decision

Keep one independently versioned `AttendeeRegistrationProfile` per account and
edition.

- The newest prior profile in the same organization may be returned as a
  read-only suggestion when its edition starts before the target edition.
  Maru displays the source edition and a notice. Nothing is persisted until
  the attendee explicitly submits the target registration.
- Submission copies values into a new target-edition profile. Later edits
  update only that current profile. The immutable registration submission and
  every earlier edition profile remain unchanged.
- Public-list consent is edition-specific, off in suggestions, versioned, and
  immediately withdrawable while the target profile remains editable.
- Pronouns use a code-owned presentation vocabulary plus `Other pronouns`.
  Custom text is accepted only when `other` is selected. This is an
  interaction aid, not an exhaustive identity taxonomy.
- Spoken languages use the ISO 639-1 alpha-2 list maintained by the Library of
  Congress coding authority, with unique ordered selections and a maximum of
  five. This is the credential/badge input contract; badge rendering itself is
  separate work.
- `brings_fursuits` controls an edition-owned collection of zero to ten active
  fursuits. Each has name, optional species, and optional independently
  moderated image. Removed entries are deactivated rather than erased from
  history.
- Profile and fursuit images use `none`, `pending`, `approved`, or `rejected`.
  A new or replaced file is private and pending. An authorized moderator must
  record approve/reject and a reason. The attendee sees the result in their
  timeline and profile.
- The exact approved file may be referenced by a later same-organization
  profile owned by the same account, preserving its approval evidence. A new
  byte sequence always returns to pending. Cross-account and cross-organization
  reuse are denied.
- A public attendee rendition includes only confirmed or checked-in,
  edition-consenting profiles. It may expose display name, pronouns, bio,
  spoken languages, fursuit names/species, and approved images. It never
  exposes login email, legal name, date of birth, address, emergency contact,
  phone, Telegram, registration answers, product, price, or payment evidence.
- The HTML attendee list is a reference client. The minimized JSON list,
  profile contract, authenticated suggestion, self-profile update, and media
  upload APIs are the content-backend interfaces.

Image review is content moderation, not malware scanning. Production publication
still requires scanning, safe decoding/rendition generation, storage lifecycle,
and an incident/removal process.

The pronoun vocabulary incorporates useful choices from reviewed public
convention material and adds name-only, ask-me, and conditional write-in
behavior. The language contract follows the
[Library of Congress ISO 639 guidance](https://www.loc.gov/standards/iso639-2/langhome.html).
The conditional write-in and optional-answer design also follows the practical
direction in Georgetown University's
[inclusive forms guidance](https://lgbtq.georgetown.edu/creating-inclusive-forms/).

## Consequences

Returning registration is faster without creating mutable cross-edition shared
state. Historical convention records remain explainable, while the most recent
attendee correction naturally becomes the next suggestion.

Media moderation becomes an edition-scoped operational queue with explicit
authority, sensitive-read audit, reasoned decisions, attendee-visible
consequences, and exact-file reuse. Storage references can outlive the profile
that first uploaded them, so retention must use reference-aware disposal rather
than deleting a file when one profile changes it.

The attendee list is deliberately public. Opt-in wording, withdrawal behavior,
search-engine policy, retention, and local law therefore need convention review
before production.

## Alternatives considered

- Put current address and profile fields on `Account`: rejected because it
  would create silent organizer sharing and mutable historical meaning.
- Automatically copy prior values and consent: rejected because the attendee
  would not review the new purpose/context.
- Keep one fursuit on the profile: rejected because the real relationship is
  one-to-many and per-image moderation is required.
- Re-review an unchanged approved file every year: rejected because approval
  concerns exact content; replacement bytes still require review.
- Allow arbitrary language text: rejected because spelling and locale variants
  are unsuitable for interoperable badge metadata.
- Claim an exhaustive pronoun list: rejected because no finite platform
  vocabulary can do so honestly; a conditional write-in remains required.
- Keep the attendee list behind another paid registration: superseded because
  the desired product is a public, minimized, explicitly consented attendance
  rendition.
