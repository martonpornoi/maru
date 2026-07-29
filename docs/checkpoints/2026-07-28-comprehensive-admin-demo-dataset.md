# Comprehensive admin demonstration dataset

Date: 2026-07-28  
Outcome: Every Maru admin area has representative synthetic data and
person-focused inspection dossiers

## Scope

The local/test-only demonstration fixture advances to
`maru-synthetic-two-convention-v4`. On a fresh database it creates sixteen
current-edition registrations across two independent organizers, covering
guardian pending, waiting, payment pending, confirmed, checked in, expired,
and cancelled states.

The fixture now also creates representative examples for all implemented
operational domains:

- phased volunteer, early-bird, normal, Infinity supporter, and guest offers;
- immutable submissions, profiles, multiple fursuits, guardian consent,
  entitlements, check-in, adjustments, and staff-only comments;
- hosted-payment accounts, intents, authenticated webhook evidence,
  exceptions, ledger movements, receipts, refund proposal, settlement, and
  allocation;
- notification preferences, successful and failed delivery, account security,
  recovery, session, abuse, restriction, and appeal;
- media safety, privacy request, post-edition correction, retention, and
  disposal evidence; and
- credentials, offline relay/manifest/conflict, readiness gates, closure
  manifest, and archive amendment.

Every one of the 55 Maru models registered in Django admin is non-empty after
the seed. Stable UUIDv5 identities and natural-key collision checks keep the
upgrade additive and idempotent. Existing demo registrations are never
repurposed to manufacture a new state; the v4 upgrade adds a separate stable
minor example so older v3 databases also receive guardian-consent data.

## Admin inspection behavior

The read-only registration dossier now separates attendee-submitted data from
organizer-managed facts:

- the exact question labels, answers, purpose, and visibility snapshot;
- account verification, active/restricted state, multiple role assignments,
  and convention capacities;
- ticket price, received and returned/disputed amounts, attempts, ledger
  movements, receipts, and finance operations;
- active entitlements and explicit Infinity-holder status;
- staff-only timeline comments; and
- direct links to submission, profile, fursuits, guardian consent, payment
  evidence, receipts, credentials, and timeline entries.

The account page adds a cross-convention organizer-relationship and
registration/payment history. The submission page renders its immutable JSON
as a readable table while retaining the exact source fields in a collapsed
technical section.

## Migrations and local data

No new persistence fields were required. Model-option migrations correct
human-facing admin plurals and check-in hyphenation:

- `accreditation.0003`;
- `communications.0002`;
- `privacyops.0005`; and
- `registration.0025`.

All migrations were applied to the local PostgreSQL database and the v4
fixture was reseeded with synthetic account password reset explicitly enabled.
The migration plan is metadata-only and has no data-loss or rollback
implication.

## Verification

- 369 backend tests pass against PostgreSQL 17.
- Branch-aware coverage is 90.09%, above the 90% gate.
- The focused demo/admin suite passes 20 tests.
- Ruff format/lint pass; strict mypy passes 153 source files.
- Django system check, migration drift, OpenAPI 3.1 validation, and
  documentation validation pass.
- The fixture passes create/rerun idempotency and a legacy fursuit-identity
  preservation test.
- The local database reports no empty Maru admin model.
- Browser QA verifies corrected admin labels, five rendered sponsor answers,
  Infinity and internal-comment display, `220.00 EUR` received, seventeen
  attached-record links, and the account registration-history row.

## Limits

This remains safe synthetic local/test data. Provider accounts are disabled,
hosts use `.invalid`, tokens are non-reversible placeholders, and no real
image, secret, payment, email, or personal data is included. The admin
dossiers are navigation and inspection surfaces; command-owned finance,
authority, restriction, credential, and history records remain read-only.
