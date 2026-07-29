# Checkpoint: Reusable attendee profiles and moderated public attendance

- Date: 2026-07-28
- Phase: Registration vertical slice delivered ahead of full V08 completion
- Related requirements: IDN-006, PRI-001, PRI-003, PRI-005, REG-002,
  REG-012, REG-014, REG-015, REG-016, UX-006, UX-007
- Related ADRs: ADR 0009, ADR 0010, ADR 0012

## Outcome

Maru now treats attendee profile data as an edition-owned content-backend
contract. A returning attendee can review a clearly sourced earlier
same-organization profile suggestion, but a new submission creates an
independent edition snapshot. Current-edition profile changes and public-list
consent withdrawal do not rewrite an older convention or the immutable
registration submission.

The contract provides maintained pronoun choices with a conditional custom
entry, a 500-character bio, up to five ISO 639-1 spoken languages, optional
profile media, and an explicit fursuiting opt-in with up to ten fursuits. The
reference form and authenticated headless APIs share the same validation and
state transitions.

New profile and fursuit images remain private in `pending` until an authorized
moderator records an approval or rejection with a reason. The same account can
reuse the exact approved file in a later profile within the same organization;
cross-account or cross-organization reuse is rejected. Attendees can replace
or remove current images.

Confirmed or checked-in attendees can separately consent to an anonymous
public HTML/JSON list. It exposes only display name, pronouns, bio, spoken
languages, fursuit names/species, and approved media. Archived or cancelled
editions do not expose the list.

## Decisions

- Accepted ADR 0012 for explicit profile suggestions, edition snapshot
  isolation, structured public-profile fields, independently moderated media,
  exact-file reuse, and minimized public attendance.
- Pronoun choices are an interaction vocabulary, not a claim of exhaustive
  identity taxonomy; `Other pronouns` remains available.
- The language contract is ISO 639-1 with a maximum of five for interoperable
  future badge input.
- Profile media review is publication moderation, not malware scanning.
- Public-list consent is edition-specific, is not copied from history, and is
  withdrawable while the profile remains current.

## Changed areas

- Registration models, services, forms, migrations, authorization
  capabilities, events, APIs, OpenAPI, server-rendered reference views, and
  protected media delivery.
- Staff Console registration media-review queue and generated API client.
- Demo fixture migration compatibility and idempotent reseeding.
- Product requirements, ADR index, module/domain/security/experience/testing
  documentation, operator runbook, roadmap, prioritized registration backlog,
  and current handoff.

## Verification

- Ruff formatting/lint: pass, 162 Python files.
- Strict mypy: pass, 115 source files.
- PostgreSQL tests: 326 pass.
- Branch-aware coverage: 90.09%, above the 90% gate.
- Django system check and migration-drift check: pass.
- OpenAPI 3.1 generation/validation and generated TypeScript client: pass.
- Staff Console: 12 tests, TypeScript type-check, and Vite production build
  pass.
- Documentation validation: 77 Markdown files and 171 unique requirement
  identifiers.
- Browser QA: desktop and 390-pixel mobile registration/profile/public-list
  and moderation views; no horizontal overflow or console errors.
- Existing local demo database upgraded through registration migrations 0007
  to 0010 and reseeded without the migrated-fursuit collision.

## Data, migration, and deployment notes

- Migration 0007 maps legacy pronouns and a legacy single fursuit into the new
  profile/fursuit representation before removing old fields.
- Migration 0008 adds fursuit scope, archive, and retention guards.
- Migrations 0009 and 0010 add the independently versioned profile aggregate
  and PostgreSQL guard.
- Removed fursuits are deactivated; ordinary deletion remains protected.
- Approved-file reuse creates another storage reference. Disposal must be
  reference-aware.
- No production personal data was used. Tests, browser QA, and migration
  rehearsal used synthetic data.

## Known risks and incomplete work

- Production upload safety still needs malware scanning, safe decode/re-encode,
  metadata stripping, controlled renditions, incident removal, and
  reference-aware disposal.
- Post-edition correction needs a separate reasoned workflow.
- Public search/cache removal receipts and configurable retention execution are
  not implemented.
- Complete anonymous headless submission, verified identity/recovery/abuse
  controls, real payment provider/webhooks, external notifications,
  refunds/transfers/disputes, credentials, offline arrival, and archival close
  remain pilot blockers.

## Recommended next actions

1. Finish the production identity/abuse boundary and anonymous headless
   submission contract.
2. Add safe media processing, storage lifecycle, and downstream removal
   receipts.
3. Implement a production payment intent/webhook adapter and service
   notification delivery.
4. Add reasoned post-edition correction and configurable retention execution.
5. Stress reservation, expiry, payment, and waitlist concurrency before public
   sales.
