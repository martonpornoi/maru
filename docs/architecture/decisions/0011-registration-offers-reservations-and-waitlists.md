# ADR 0011: Registration offers, reservations, and waitlists

- Status: Accepted
- Date: 2026-07-28
- Requirements: REG-001, REG-003 through REG-006, REG-008, REG-010,
  AUD-001, AUD-003, PRI-008

## Context

Conventions commonly open registration in phases: an accepted-volunteer offer,
an early-bird public offer, and normal admission. Scarce capacity cannot be
held indefinitely while a person decides whether to pay. When capacity is
full, an organizer needs a fair, understandable waitlist and reliable
notification of a later offer.

Testers and staff also need safe ways to rehearse payment or handle a genuine
exception. An unrecorded “ignore payment” control would make financial state
unreconcilable and could accidentally reach production.

## Decision

An admission product is an edition-owned, versioned offer.

- A product may define a sale opening, sale closing, price, capacity, active
  participation-capacity eligibility codes, attendee-facing eligibility
  explanation, waitlist policy, and payment-window override.
- Volunteer pre-registration is an offer restricted to an active,
  server-owned volunteer capacity. An attendee cannot self-declare that fact.
- Early-bird and normal admission are separate products with independent
  prices and sale windows. Their exact product, price, and currency are
  snapshotted at submission.
- A selected available paid place enters `payment_pending` and receives a
  concrete payment deadline. It occupies capacity until confirmed, cancelled,
  or expired.
- A full eligible offer enters `waitlisted` only when both edition and product
  policy allow it. A waitlisted person does not pay and does not occupy
  capacity.
- Automatic promotion is first-in by `waitlisted_at`, then stable identifier,
  under row locks. A promoted person receives a new payment deadline. A
  no-cost offer confirms immediately.
- Automatic offers stop when the applicable product or registration period
  closes. Remaining waitlist entries close without payment.
- Expiry releases capacity and triggers the next automatic offer in the same
  transaction. Scheduled processing is repeatable and safe after interruption.
- An authorized operator may set a future payment deadline with a reason.
  Every change creates append-only adjustment evidence, audit, domain event,
  and attendee-visible timeline entry.
- An authorized payment waiver confirms admission but records
  `confirmation_basis=waiver`; it never creates false provider-payment
  evidence.
- Local and test environments may enable the deterministic demo payment
  adapter. Production cannot use it. Rehearsal uses synthetic accounts and
  products, not an untracked bypass.
- An inactive platform account cannot submit or pay. Lifecycle processing
  cancels its open reservation or waitlist entry. A confirmed or checked-in
  registration is flagged for human review because refund, entitlement,
  credential, safety, and appeal consequences must not be silently guessed.
- State changes publish durable events. The personal timeline is immediately
  available; email, inbox, or other delivery adapters consume those events
  idempotently and report delivery separately from canonical state.

For phased pricing, early or restricted products should normally disable their
waitlist unless the organizer has explicitly decided how an unfulfilled
discounted queue ends. The final normal-admission offer is the usual waitlist
owner.

## Consequences

Capacity becomes observable and time-bounded. Staff can distinguish provider
payment, free admission, and waiver. People know whether they have a
reservation, are waiting, have a deadline, or lost an expired offer.

The scheduled lifecycle processor must run frequently and be monitored.
Provider webhooks, external notifications, refunds, transfers, disputes, and
receipts remain separate follow-on work. Product rollover between different
prices is not automatic because changing a person's price requires explicit
notice and acceptance.

## Alternatives considered

- Keep unpaid registrations indefinitely: rejected because it silently blocks
  capacity.
- Charge while joining the waitlist: rejected because payment would not
  correspond to an allocated place.
- Random waitlist promotion: deferred for domains that need a versioned lottery
  or allocation round; ordinary admission uses explainable FIFO.
- Automatically move an early-bird waitlist to a higher-priced product:
  rejected because it changes price without explicit attendee acceptance.
- Add a temporary “ignore payment” button: rejected because it destroys
  reconciliation. A reasoned waiver or non-production demo adapter covers the
  legitimate use cases.

