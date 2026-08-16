# Catalog same-shell configuration and private discovery

Date: 2026-08-09
Requirement: REG-026
Status: implemented and focused verification green

## Outcome

The edition-catalog command boundary now has a shared-shell staff adapter for
draft creation, product policy, price and stock variants, activation, governed
stock adjustment, and purpose-scoped activity. It supports convention and
charity merchandise, stockless donations, and finite limited-supporter offers
without joining catalog lines to admission products.

Charity choices are confirmed selections from the exact organization and
edition and render only the partner public label. Sale windows are strict
edition-local minutes and reject whitespace, ambiguity, and nonexistent local
times. Mutations authorize before parsing and use closed forms, canonical retry
keys, current versions, and the existing audited/outbox-producing services.

The attendee index now authorizes scalar scope IDs before fetching labels, so a
denied foreign prefix cannot consume the bounded result or disclose its label.
All authenticated Catalog GET pages use private `no-store` cache controls.

## Verification

- Ruff passed for the Catalog source and focused tests.
- mypy passed for Catalog forms, views, and services.
- strict form unit matrix: 2 passed.
- PostgreSQL Catalog integration matrix: 6 passed, covering closed input,
  stale version, replay and changed-digest key reuse, exact charity scope,
  foreign object and unauthorized-before-parse handling, activation
  immutability, cache headers, shared navigation, discovery starvation,
  orders/payments, stock ceilings, evidence, and tenant isolation.
- Django setup, root URL import, and staff-template load passed.

## Recovery and remaining risk

No schema was added. Existing catalog and authorization downgrade fences remain
authoritative; active definitions and append-only evidence must not be rewritten
during recovery. Real provider authentication, unpaid-order expiry,
cancellation/refunds, fulfilment custody, shipping, accounting export, and
production monitoring remain outside this checkpoint.
