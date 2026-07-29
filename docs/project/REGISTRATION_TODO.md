# Registration implementation backlog

Status: Repository-controlled production-safety pass delivered; external approval and selected product gaps remain  
Last updated: 2026-07-28

This is the honest residual backlog after the registration production-safety
pass. Detailed operator and tester steps are in the
[registration runbook](../operations/registration-runbook.md).

States:

- **Delivered:** implemented and automatically verified in this repository.
- **Deployment gate:** infrastructure, credentials, external service, measured
  rehearsal, or accountable approval that cannot be completed in source code.
- **Product gap:** intentionally unavailable until its full user and integrity
  semantics are implemented.
- **Operational improvement:** usable through current APIs/admin, but a
  purpose-built interface would materially reduce staff error.

## Delivered repository boundary

### Identity and headless registration

- Email verification and recovery with expiring single-use challenges,
  non-enumerating recovery, bounded abuse counters, and durable email delivery.
- Session inventory/revocation, user-visible security history, and production
  privileged step-up.
- Organization/edition-scoped, reasoned, expiring restrictions with attendee
  notification, consequences, revocation, and appeal.
- Complete JSON account/session/submission path with CSRF, exact-origin
  credentialed browser policy, configuration version, policy acceptance,
  conditional validation, and idempotent command receipts.
- OpenAPI 3.1 and generated TypeScript contracts.

### Registration and attendee profile

- Edition-owned copy-on-write forms and immutable activation.
- Volunteer, early-bird, normal, free, and other separate product offers with
  authoritative eligibility, price snapshots, capacities, deadlines, and
  automatic FIFO wait-list.
- Explicit prior-profile suggestions and isolated edition snapshots.
- Maintained pronouns plus conditional Other, five ISO 639-1 languages,
  500-character bio, optional profile image, multiple optional fursuits, and
  self-service current-edition amendment.
- Minimized opt-in public attendee list and immediate consent withdrawal.

### Payment, finance, and communication

- Organization-scoped provider accounts, local payment intents, HTTPS host and
  return-origin allowlists, generic JSON hosted-checkout adapter, HMAC and
  timestamp verified webhooks, replay safety, and payment-exception queue.
- Append-only operational ledgers for provider payments, refunds, fees,
  disputes, chargebacks, and settlements plus attendee receipts.
- Dual-controlled cancellation and refund; entitlement revocation preserves
  immutable scope and evidence.
- Reconciliation separates provider money, waived face value, and free places.
- Canonical localized inbox, email projection, delivery preference,
  idempotency, retry, permanent-failure queue, and closure integration.

### Privacy, media, arrival, and closure

- Versioned minor/guardian policy and guardian-pending challenge flow.
- Image type/size/decode checks, ClamAV protocol, metadata stripping, safe
  rendition, safety receipt, moderated publication, exact reuse, and
  reference-aware disposal.
- Subject request intake/tracking, minimized export, post-edition correction
  proposal/decision, retention minimization, and disposal receipt.
- Revocable credentials, minimized self projection, signed bounded offline
  manifests, idempotent ingest, and conflict queue.
- Closure readiness counts, five independently evidenced gates, immutable
  manifest, stale-manifest prevention, and PostgreSQL restore rehearsal.
- Scoped machine-readable registration metrics and lifecycle heartbeat.

## Deployment gates before production personal data

### DEP-01 — Select and certify a payment provider

Requirements: REG-005, REG-017, REG-018, INT-003, FIN-007.

- Select the actual provider and implement or validate its concrete adapter
  against Maru's generic JSON hosted-checkout contract.
- Provision credentials/webhook secrets in a secret manager.
- Certify sandbox success, failure, abandonment, timeout, replay, reordered
  event, wrong amount/currency/account, late success, refund, dispute,
  chargeback, fee, and settlement statement behavior.
- Obtain provider, finance, security, and privacy approval.

Exit evidence: signed sandbox matrix, reconciliation export, credential
rotation/disable rehearsal, and owned escalation path.

### DEP-02 — Install production workers and monitoring

Requirements: MSG-007, REG-010, NFR-004, NFR-005.

- Supervise `identity_delivery`, `registration_lifecycle`, and required effects
  worker pools.
- Scrape registration/effects metrics and alert on heartbeat age, overdue
  reservations, capacity drift, exceptions, delivery failure, outbox
  quarantine, pending moderation/privacy/restriction/offline queues.
- Exercise worker crash, lease expiry, retry, pause, catch-up, and provider
  outage procedures.

Exit evidence: dashboards, alerts routed to named people, runbook drill, and
measured recovery.

### DEP-03 — Prove representative capacity and throughput

Requirements: REG-010, UX-004, NFR-001, NFR-005.

- Benchmark the forecasted registration launch with PostgreSQL contention,
  concurrent submission/payment/expiry, multiple lifecycle workers, provider
  degradation, and realistic tenant traffic.
- Verify no oversubscription or duplicate offer and record p95/p99 latency,
  database locks, saturation, backlog, and recovery.

The automated suite proves transactional correctness, including concurrent
database contention, but is not a production-size load certificate.

Exit evidence: dated load report against the edition forecast and an accepted
capacity/fallback decision.

### DEP-04 — Provision delivery, media, storage, and offline operations

Requirements: MSG-007, REG-019, REG-020, ACC-005, PRI-009.

- Configure SMTP reputation/bounce handling and manual fallback.
- Deploy ClamAV and protected/safe-rendition object stores with backup and
  lifecycle policy.
- Provision relay devices, rotate the offline-manifest secret, package the
  relay client, and test actual scanners/printers and loss/revocation.
- Connect disposal to storage-provider evidence where required.

Exit evidence: failure drills, device/stock custody, media safety sample,
delivery sample, and storage/disposal receipt.

### DEP-05 — Approve policy and ownership

Requirements: PRI-001 through PRI-009, REG-019, REG-020, NFR-008.

- Approve controller register, field purposes, retention periods, guardian age
  bands/consent, refund/cancellation, restriction/appeal, financial evidence,
  public directory, and support policies for the jurisdiction.
- Provision active retention policies through a reviewed, dual-controlled
  process. Bootstrap admin is intentionally read-only.
- Assign owners and response targets to every queue.
- Complete restore, secret rotation, provider disable, mail outage, network
  outage, and closure rehearsal.
- Record privacy, finance, operations, security, and
  jurisdiction/safeguarding readiness decisions.

Exit evidence: all five edition gates approved with references and a formal
go/no-go.

### DEP-06 — Certify each seasonal frontend

Requirements: REG-002, REG-014, INT-001, UX-007.

- Register exact production origins and no wildcard.
- Run the headless conformance matrix for definition, verification, sign-in,
  submission, idempotency, profile, image upload, payment status, waiting, and
  error handling.
- Complete WCAG 2.2 AA, keyboard, assistive-technology, mobile, localization,
  security-header, CSRF, abuse, and browser tests.

Exit evidence: generated-schema version, test report, rollback, and owner.

## Product gaps that remain intentionally unavailable

### PROD-01 — Admission transfer

Implement recipient invitation/acceptance, identity verification, eligibility,
capacity, price/tax, fraud, consent, credential, refund, and rejection/expiry
semantics. Until then the API returns
`financial_operation_workflow_unavailable`.

### PROD-02 — Product change and price adjustment

Implement attendee acceptance for increased price, capacity reservation,
refund/additional payment, entitlement replacement, receipt/credit-note, and
wait-list interaction. Do not repurpose deadline or waiver controls.

### PROD-03 — Broader catalog

Discounts, vouchers, memberships, bundles, donations, instalments, taxes,
multi-currency accounting, merchandise, hotel, meal, and volunteer benefits
must remain distinct domain concepts.

### PROD-04 — Platform-global privacy and identity

Add a platform-controller workflow for requests not belonging to one
organization, duplicate-account merge/split, passkey or phishing-resistant
MFA, and platform suspension. Organizer restrictions must not expand into
cross-convention surveillance.

### PROD-05 — Physical fulfilment

The Reports workspace and minimized, audited badge-data CSV are implemented.
Build badge-layout/version, printer adapter, stock custody, reprint,
merchandise handover, zone policy, and distributable relay-client interfaces
over the existing credential/offline evidence boundary.

## Operational usability improvements

### UX-REG-01 — Friendly form studio

- Drag-and-drop sections/questions;
- safe conditional-rule editor;
- desktop/mobile/accessibility preview;
- phase timeline, source comparison, and activation checklist;
- inline time/currency/capacity/eligibility diagnostics.

### UX-REG-02 — Staff registration on behalf

Create an explicit command with distinct actor and attendee, source, reason,
notice/invitation, and the same identity, validation, capacity, price,
deadline, payment, and audit services. Never expose raw confirmed-state insert.

### UX-REG-03 — Purpose-built work queues

Add searchable/saved views and assignment for payment exception, delivery
failure, overdue, wait-list, guardian, moderation, restriction/appeal,
privacy, refund, settlement, offline conflict, and closure. Current APIs,
Staff Console action projection, and read-only admin are functional but not the
final low-friction workspace.

### UX-REG-04 — Attendee service

Add permitted registration-answer amendments, cancellation/refund request,
payment retry, wait-list leave, transfer when implemented, notification
delivery status, downloadable receipt artifact, and clear support
conversation. Preserve explicit language: waiting is not reserved; waived is
not paid; browser return is not confirmation.

## Smallest sensible sequence

1. Choose the first partner, provider, jurisdiction, owners, and forecast.
2. Complete DEP-01 through DEP-05 in rehearsal.
3. Certify the chosen seasonal frontend under DEP-06.
4. Build UX-REG-03 first if the pilot team cannot safely operate the API/current
   Staff Console queues.
5. Prioritize PROD-01 through PROD-05 only from partner need; do not weaken the
   implemented evidence boundaries to simulate them.

No repository result substitutes for external review or an edition go/no-go.
