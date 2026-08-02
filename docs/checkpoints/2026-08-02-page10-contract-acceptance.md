# Page 10 registration and account-invitation contract acceptance

Checkpoint status: Accepted product and architecture boundary; implementation
has started but no Page 10 schema, command, adapter, writer-cutover, browser, or
deployment completion is claimed here.

Date: 2026-08-02
Branch: `codex/full-platform-consolidation`
Decision: ADR 0047
Requirements: IDN-013, UX-026, REG-024 and the existing requirements cited by
the Page 10 contract

## Outcome recorded

Maru's next coherent convention journey is fixed before migration work begins.
Page 10 will use the existing shared `/admin/` shell and will not restore Quick
Start, a second registration shell, or a parallel React-owned builder.

An active platform administrator may optionally reserve and invite an inactive
person account. The recipient proves control of the invited address and chooses
their own policy-valid password. Creation, reissue, revocation, expiry,
delivery, and acceptance are versioned and audited, while the bearer token is
stored only as a digest plus an envelope-encrypted payload available to a
dedicated delivery worker. Invitation creates no organization, representation,
authority, participation, registration, application, workforce, entitlement,
order, or public-directory relationship.

Each convention edition receives one canonical Registration workspace. A draft
configuration starts explicitly from blank, an exact published template
version, or an exact eligible prior edition. Purpose-built commands govern
sections, questions, products, ordering, minor policy, activation, successors,
and C1/C2 post-submission profile-extension definitions. Active and published
meaning remains immutable. Zero custom questions is valid; an explicit invalid
value such as capacity zero is rejected rather than silently inherited.

HTML and versioned APIs are adapters over the same exact-scope commands. The
boundary requires closed inputs, positive expected versions where state can be
stale, scope-bound idempotency, minimized audit, durable downstream effects,
and failure atomicity. Direct Django-admin, fixture, and ORM writers retire only
through a documented additive/backfill/common-command/stopped-writer sequence.

## Evidence recorded

- The complete Page 10 page contract is accepted at
  `docs/product/page-contracts/10-registration-setup-and-account-invitations.md`.
- ADR 0047 records the durable delivery, command, immutability, authorization,
  migration, recovery, and retirement decisions.
- IDN-013, UX-026, and REG-024 provide stable requirement identifiers.
- Current identity, registration, navigation, API, admin, fixture, migration,
  and test surfaces are being inventoried against the contract before code
  changes.

Documentation validation is required before this checkpoint is committed. It
does not substitute for implementation, migration, test, browser,
accessibility, load, recovery, or owner-rehearsal evidence.

## Known gaps and risks

- Existing identity challenges use reconstructable secrets and query-string
  delivery links; they are not the invitation implementation in ADR 0047.
- Registration configuration currently lacks the Page 10 aggregate command
  version and receipts, allows direct draft writers, rejects a valid
  zero-custom-question configuration, and uses truthiness for imported
  capacity.
- Current registration profile staff access is coupled to assisted
  registration; dedicated view/update capabilities must be introduced.
- Existing routes and backend functionality are not proof of a coherent
  same-shell browser journey.
- SMTP/worker supervision, representative deployment, secrets and key
  management, accessibility, load, recovery/PITR, and owner evidence remain
  external release gates.

## Smallest continuation

1. Implement the invitation aggregate, encrypted durable delivery, recipient
   acceptance, platform APIs/pages/navigation, and security tests.
2. Add registration aggregate controls and idempotent exact-scope commands,
   including explicit-zero rejection and zero-question activation.
3. Mount the edition workspace and builder, introduce dedicated profile-field
   capabilities, then retire direct writers through the ADR 0047 readiness
   boundary.
4. Build the fully synthetic educational smoke journey and complete browser,
   accessibility, deployment, load, recovery, and tutorial evidence.
