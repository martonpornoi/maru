# Page 10 registration configuration lifecycle core

Date: 2026-08-03

This checkpoint records the focused Page 10 configuration lifecycle application
core. It does not claim that lifecycle HTML/API adapters are mounted, that
compatibility or direct writers have been retired, that successor/retirement
commands exist, or that Maru is production ready.

## Outcome

- `maru.registration.configuration_lifecycle` provides an exact-scope,
  transactionally locked validation preview plus separate explicit review and
  activation commands.
- Preview recomputes the exact configuration digest and any complete published-
  template or active prior-edition source digest. It projects ordered sections,
  questions, products, semantic activation issues, and attendee/staff answer
  validation through the canonical registration answer validator.
- Preview appends one minimized sensitive-read audit before returning protected
  labels. It creates no account, registration, submission, reservation,
  wait-list entry, payment attempt/intent, entitlement, guardian consent,
  domain event, outbox message, or setup/configuration change. Audit failure
  returns no projection and leaves no state or effect evidence.
- Review evidence is authoritative only when one immutable review receipt target
  matches the exact configuration, current setup aggregate version, and fresh
  content digest. The legacy `review_required` value remains a display-
  compatibility field and cannot be forged into review proof.
- Activation requires current review evidence, the exact case-sensitive edition
  name, and all bounded configuration/product/condition/capacity/payment/
  wait-list/minor-policy invariants. At least one admission product is required;
  zero custom questions is valid.
- Activation refuses another active configuration and never silently retires
  it. A future retirement or successor command must make that lifecycle change
  explicit.
- Each successful review or activation advances the setup aggregate exactly
  once and atomically appends its scoped retry receipt/target, minimized audit,
  registered domain event, and outbox message. Same-key retries replay the
  original result; changed intent conflicts. Same-key and distinct-key
  activation races commit one transition.
- Authorization is checked before protected input parsing and again under the
  locked organization, series, edition, persisted actor, setup, and
  configuration scope. Draft mutation is limited to editable organization and
  Draft/Preparing edition lifecycles.

## Schema and recovery

No lifecycle-core schema migration is required. Registration migrations `0032`
and `0033` already provide the setup control, receipt actions, targets, version
stamps, content/source digests, and provenance fields used here.

Review and activation state plus all evidence are one PostgreSQL transaction.
Receipt, target, audit, domain-event, or outbox failure rolls the complete
command back. Recovery is therefore an exact retry with the original key and
payload after the dependency is healthy; operators must not edit status,
version, or evidence rows to manufacture success.

## Verification

- Focused lifecycle matrix: **25 passed in 30.04 seconds** on PostgreSQL.
- Fresh-database combined matrix: **73 passed in 95.13 seconds**, comprising
  the 25 lifecycle cases and 48 adjacent setup-start, section-command,
  definition-command, and legacy configuration cases.
- The matrix covers exact blank, complete published-template, and active prior-
  edition sources; source-version/digest mismatch; zero questions; every
  content-class review invalidation; semantic issue projection; malformed minor
  review evidence; exact confirmation/version failures; authorization-before-
  parsing; preview audit failure; review/activation evidence rollback;
  historical replay; active-version refusal; and same/different retry races.
- Ruff format/check passes for the lifecycle service and focused integration
  tests. Strict mypy passes for the lifecycle service.
- The concurrent profile-field lifecycle slice owns registration migration
  `0034`; this work did not create a competing migration. With `0034` present,
  Django's final migration-drift check reports no changes.

## Open boundary

- Mount strict closed-input browser and canonical v1 API adapters for preview,
  review, and activation, including RFC 9457 mappings and OpenAPI evidence.
- Implement explicit configuration successor, retirement, and active-version
  replacement choreography without weakening immutability.
- Reconcile compatibility APIs, public registration readers, model admin,
  fixtures, and every repository-owned writer before installing stopped-writer
  database guards.
- Complete browser, 390-pixel, keyboard/screen-reader, throughput, deployment-
  readiness, recovery/PITR, and owner tutorial evidence before any production
  claim.
