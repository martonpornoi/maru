# Checkpoint: Phased registration offers, reservations, and waitlists

- Date: 2026-07-28
- Phase: Registration lifecycle milestone delivered ahead of full V08
- Related requirements: REG-001 through REG-014, AUD-001 through AUD-003,
  PRI-008, INT-001 through INT-003, NFR-001, NFR-004
- Related ADRs: 0005, 0007, 0009, 0010, 0011

## Outcome

Maru can model accepted-volunteer, early-bird, normal, free, and other
edition-specific admission phases as separate immutable products. Each offer
can define a sale window, active participation-capacity eligibility,
attendee-facing explanation, product capacity, waitlist behavior, and
payment-window override.

An available paid submission reserves capacity until a concrete deadline. A
full eligible product can place the person on a no-payment FIFO waitlist. The
repeatable lifecycle processor expires overdue reservations, releases capacity,
offers the oldest eligible waitlisted person a fresh deadline, closes remaining
waiting records at the applicable sale close, and cancels open records for
inactive accounts.

Staff can make a reasoned future-deadline change or payment waiver from the
Staff Console. Finance can distinguish provider-paid amount, waived face value,
free confirmations, pending reservations, waitlisted, expired, and cancelled
records. The registration definition is publicly readable for replaceable
seasonal frontends; the bundled form is the neutral reference and fallback
client.

## Decisions

- The versioned API/schema is authoritative; visual theme and page layout are
  replaceable client concerns.
- Volunteer, early-bird, and normal prices are separate versioned offers rather
  than a frontend discount switch.
- Only active server-owned participation-capacity codes satisfy restricted
  product eligibility.
- Paid reservations occupy capacity; waitlisted records do not and are not
  charged.
- Ordinary admission waiting is stable FIFO. Cross-product rollover to a
  different price requires future explicit attendee acceptance.
- Payment deadline changes and waivers are explicit privileged commands with
  append-only evidence. A waiver never becomes fake provider payment.
- Local/test demo payment stays disabled by default and in production.
- Inactive-account open records close automatically; paid/checked-in records
  require human review rather than silent historical erasure.

## Changed areas

- Registration models, availability policy, application services, API
  serializers/views/routes, admin, public reference forms, demo fixture, event
  registry/handlers, capability catalog, and Staff Console.
- Public registration-definition and finance-reconciliation APIs.
- Lifecycle management command with edition filter and non-mutating dry run.
- Append-only `RegistrationAdjustment` and expanded registration aggregate
  state/timestamp/evidence fields.
- ADRs 0010/0011, requirement REG-014, module/product/security/operations
  documentation, step-by-step registration runbook, and prioritized
  registration backlog.

## Verification

- Ruff format and lint pass for 160 Python files.
- Strict mypy passes 114 source files.
- 303 PostgreSQL-backed backend tests pass.
- Branch-aware coverage is 90.11% against the 90% gate.
- Eleven Staff Console tests, generated OpenAPI types, TypeScript typecheck, and
  production build pass.
- Django system and production deployment checks pass.
- Migration apply and drift checks pass.
- OpenAPI 3.1 generation/validation passes.
- Documentation validation passes 75 Markdown files and 169 referenced
  requirement identifiers.

Registration-focused tests cover phased availability, volunteer eligibility,
capacity and no-wait outcomes, payment deadlines, late payment, expiry, FIFO
promotion, waitlist close, inactive-account cancellation, deadline/waiver
success and denial, missing targets, finance projection, command dry run, and
append-only database guards.

Local browser QA verifies the public convention chooser, attendee status and
payment-deadline presentation, and Staff navigation at desktop and a
390-pixel mobile viewport with no horizontal overflow or console errors.

## Data, migration, and deployment notes

- Migration `registration.0005_registrationadjustment_and_more` adds product
  phase/eligibility fields, configuration lifecycle policy, registration
  timestamps/basis/states/indexes, and adjustment evidence.
- Migration `registration.0006_registration_lifecycle_guards` backfills
  concrete deadlines for existing payment-pending rows and explicit
  confirmation basis for confirmed rows, then replaces the database aggregate
  trigger with the new constrained transitions.
- Rollback across the guard/backfill boundary requires a deliberate data
  compatibility review. Financial and attendee history must not be dropped.
- Deployment must schedule `registration_lifecycle` at least once per minute
  while reservations or waitlists exist and alert on missed/failing runs.
- Existing durable events require the effects worker. External email delivery
  is not installed.

## Known risks and incomplete work

- No production provider intent/authenticated webhook, refund, transfer,
  dispute, receipt, fee, or settlement workflow.
- No external notification adapter or delivery-failure queue.
- No production lifecycle scheduler/metrics/alerts in the repository.
- No full anonymous headless write contract, production identity/recovery/abuse
  controls, or staff-on-behalf workflow.
- Capacity correctness needs concurrency, crash/retry, and multi-worker load
  proof.
- Scoped reasoned account restrictions, attendee amendment/privacy operations,
  credentials/offline arrival, and archive closure remain.
- The Staff Console form studio is not yet a complete visual editor.

## Recommended next actions

1. Deliver production identity/abuse controls and the full headless submission
   contract.
2. Implement provider intent/webhook reconciliation and notification delivery
   with owned exception queues.
3. Add finance changes/settlement and high-concurrency lifecycle proof.
4. Add privacy/restriction operations and the friendly form studio.
5. Complete credentials, offline arrival, edition closure, and restore
   rehearsal.
