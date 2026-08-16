# ADR 0050: Governed admission upgrades, capacity, and edition commerce

- Status: Accepted
- Date: 2026-08-09
- Clarifies: ADRs 0011 and 0014
- Requirements: REG-003 through REG-006, REG-008, REG-010, REG-017,
  REG-018, REG-025, REG-026, FIN-007, FUR-005, and FUR-006

## Context

An attendee may want to upgrade an already confirmed admission, while an
organizer needs live capacity changes and controlled wait-list batches. The
same edition may also sell merchandise, convention-support items, charity
support, donations, and a small number of special supporter items. Treating
these as arbitrary edits to a paid registration would rewrite financial and
capacity history. Treating merchandise as ticket entitlements would couple
fulfilment and beneficiary rules to admission.

## Decision

An upward admission change is a held tier replacement, not an edit to the
source registration. It is owned by the same attendee, targets one higher
priced admission product, reserves target capacity, and charges exactly the
positive difference between the configured source and target prices. The
source product and entitlement remain effective until authenticated payment
evidence succeeds. Reconciliation then atomically records the price evidence,
swaps the product and entitlement, and leaves exactly one active admission.
Expiry releases only the target hold. This path cannot transfer admission,
downgrade it, choose an arbitrary amount, or treat a browser return as payment.

Configured capacity is accompanied by an optional hard ceiling. Current
overall and per-product limits are projections of the initial limit plus an
append-only adjustment ledger. An adjustment is expected-versioned, audited,
and rejected if it exceeds the ceiling or invalidates existing reservations.
Wait-list review accepts a count, never selected person identifiers; the
command locks the relevant configuration and products and offers the next
eligible people in strict FIFO order. Holds, adjustments, offers, expiries,
payments, exceptions, actors, and timestamps appear in the purpose-limited
commerce activity projection.

Non-admission commerce lives in a separate edition-owned `catalog` bounded
context. Products and variants snapshot beneficiary, price, sale/preorder,
fulfilment, per-order, and stock rules. A charity beneficiary resolves to an
exact currently confirmed edition charity selection. Finite stock changes only
through append-only adjustments bounded by a hard ceiling. Order lines are
immutable snapshots, and catalog payment intents and provider events cannot
change admission entitlements. Catalog evidence is an operational ledger, not
a statutory accounting or charity-settlement system.

## Consequences

- An attendee can pay only the upgrade difference without risking their
  current place while payment is pending.
- Capacity can grow during sales while retaining a configured safety boundary
  and a complete decision history.
- Operators can choose batch size but cannot silently skip the queue.
- Admission, merchandise fulfilment, charitable beneficiary reporting, and
  finance reconciliation remain connected through explicit evidence rather
  than one overloaded order aggregate.
- Refunds, statutory accounting, charity settlement, and fulfilment adapters
  remain separate workflows and must not be inferred from a paid catalog row.

## Alternatives considered

### Cancel and repurchase the registration

Rejected. It can release the attendee's existing place before the replacement
payment succeeds and obscures the reason for the price difference.

### Let operators select people from the wait list

Rejected. A nominal FIFO queue with person-by-person exceptions is not fair or
auditable. Controlled exceptions belong to a separate reasoned command.

### Put merchandise and donations in registration products

Rejected. Stock, fulfilment, beneficiaries, preorders, and repeat orders have
different lifecycles from one-per-edition admission.
