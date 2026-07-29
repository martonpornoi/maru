# ADR 0014: Hosted payments and operational finance

Status: Accepted  
Date: 2026-07-28

## Context

Maru must determine whether a reservation is paid and explain provider money
without storing card data or trusting a browser redirect. Provider callbacks
can be duplicated, reordered, late, forged, or inconsistent. Refunds and
cancellations also require accountable authority and immutable evidence.

## Decision

- Maru records a provider account and local payment intent before requesting a
  provider-hosted checkout. Adapter URLs are restricted to configured HTTPS
  hosts.
- The browser return is status only. Confirmation comes from an HMAC-verified,
  timestamp-bounded provider event tied to the expected account, intent,
  registration, amount, and currency.
- Raw callback bodies are represented by a digest and idempotency key. Duplicate
  delivery is safe; conflicting or uncertain delivery enters an owned payment
  exception queue.
- Provider payments, refunds, fees, disputes, chargebacks, and settlements
  append operational ledger evidence. Receipts reference ledger evidence.
- Cancellation and refund use proposal and independent approval. The proposer
  cannot approve the same operation. Provider refund completion is recorded
  separately from approval.
- Admission entitlements may transition from active to revoked with immutable
  scope; they cannot be edited or deleted otherwise.
- Transfer, product change, and price adjustment are rejected until
  recipient-acceptance, capacity, pricing, and fulfilment semantics exist. The
  API must not represent them as successfully queued.
- Maru's ledger supports operational reconciliation and export; it is not a
  statutory accounting ledger.

## Consequences

A hosted provider can be replaced without changing registration truth. Staff
can distinguish paid, free, waived, refunded, disputed, and settled value.
Production still requires a selected provider adapter, sandbox certification,
credentials, and finance approval. Cross-person transfer and repricing remain
explicit product blockers.

## Alternatives considered

- Trusting the return URL was rejected because the attendee controls it.
- Storing only the latest payment state was rejected because it destroys
  reconciliation evidence.
- Enabling every financial-operation enum before safe fulfilment existed was
  rejected because an approved-but-unfulfilled state is misleading.

## Requirements affected

REG-003 through REG-008, REG-010, REG-017, REG-018, FIN-002, FIN-007,
FIN-008, INT-003, SEC-004.
