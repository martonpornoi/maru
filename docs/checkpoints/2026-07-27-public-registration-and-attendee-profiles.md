# Checkpoint: Public registration and attendee profiles

- Date: 2026-07-27
- Phase: V03 interaction foundation; registration vertical
- Related requirements: IDN-006, REG-001, REG-002, REG-003, REG-005,
  REG-007, REG-009, REG-010, REG-011, REG-012, REG-013, PRI-001, SEC-001
- Related ADRs: 0002, 0003, 0007, 0008, 0009

## Outcome

Maru now offers `Register for a convention` on the local landing page. A
visitor without an account can choose an open edition, create a platform
account, choose admission, complete fixed identity/contact fields plus the
edition's configured sections, and receive an edition-owned attendee profile.

Returning attendees use the same chooser to distinguish existing
registrations from other open editions. Their legal identity, contact,
emergency, fursuit, consent, and custom-answer records remain separate per
edition.

The attendee profile displays authoritative convention roles and benefits from
participation capacities and registration entitlements. It also supports a
separate paid-attendee-directory opt-in with a deliberately minimized
projection.

## Decisions

- Public registration may provision an account only as part of one valid,
  open-edition submission.
- Fixed profile data belongs to the registration edition, not the global
  account.
- Legal name, birth date, address, and emergency contact are restricted C3
  data governed by an explicit purpose and visibility registry.
- Volunteer departments and ticket-holder status are derived from
  authoritative capacities and entitlements; the attendee cannot self-assert
  them.
- Directory consent is explicit, versioned, and edition-specific. Only paid
  attendees of that edition can view opted-in display fields.
- Fursuit images use an authorization-checked private route and are not public
  media URLs.
- Public registration remains adult-only until a guardian and
  parental-consent workflow is designed.

These decisions are recorded in ADR 0009.

## Changed areas

- Added named configuration/template sections and per-configuration minimum
  age, including copy-on-write and immutable-version behavior.
- Added `AttendeeRegistrationProfile`, field policy inventory, protected upload
  storage, consent evidence, and model/database scope guards.
- Added the public convention chooser, account/registration form, profile,
  paid directory, protected image endpoint, responsive templates, and
  conditional-question JavaScript.
- Added bootstrap admin editing for draft sections and read-only,
  edition-scoped profile administration.
- Extended registration serializers/OpenAPI with sections and minimum age.
- Upgraded the synthetic fixture to v3 with sections and four complete
  privacy-safe attendee profiles.
- Added public-flow, privacy, tenant isolation, age, email-collision, derived
  fact, protected-file, section-copy, and immutability tests.

## Verification

- `ruff format --check .`: pass, 155 files.
- `ruff check src tests`: pass.
- `mypy src`: pass, 110 source files.
- Django system check: pass.
- Migration drift check: no changes detected.
- OpenAPI 3.1 generation and validation: pass.
- Staff Console API type generation, TypeScript typecheck, 11 tests, and
  production build: pass.
- Full PostgreSQL backend suite: 290 passed.
- Branch-aware coverage: 90.11%, above the 90% gate.
- Desktop and 390-pixel mobile browser walkthrough: landing link, anonymous
  account creation, complete submission, profile, and returning chooser pass
  with no browser console errors.
- Synthetic seed inspection: four fixture profiles and six draft sections.

## Data, migration, and deployment notes

Migrations `registration.0003` and `registration.0004` add the profile,
section, question-section relationship, minimum-age field, constraints, and
PostgreSQL guards. They applied successfully to the local database.

The seed command remains idempotent and does not reset existing fixture
passwords unless explicitly requested. The browser walkthrough added one
clearly synthetic `Juniper Lynx` payment-pending registration to local Danube
2026 data.

The schema additions preserve existing registration history. Reversing them
would drop attendee profile and form-section data, so rollback requires an
explicit export/recovery decision rather than an automatic production
downgrade.

## Known risks and incomplete work

- Public email is not verified; recovery, MFA, account linking/merge, rate
  limiting, bot defence, and production abuse controls remain.
- Guardian and parental-consent registration is not implemented.
- Attendees cannot yet correct a submitted profile or withdraw directory
  consent through self-service.
- Fursuit images lack malware scanning, metadata stripping, resizing, and
  thumbnail generation.
- The public flow can create a paid registration but production payment
  provider, webhook, refund, receipt, and reservation/expiry work remains.
- Bootstrap admin provides ordered section/question inlines, not a complete
  visual form builder.

## Recommended next actions

1. Add verified-email/recovery and profile/consent self-service.
2. Build the visual section and conditional-question editor with preview.
3. Add production image-processing controls.
4. Implement the real payment-provider and reservation/expiry boundaries.
5. Validate the public flow with a convention partner and privacy reviewer.
