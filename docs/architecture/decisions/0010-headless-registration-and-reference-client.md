# ADR 0010: Headless registration and reference client

- Status: Accepted
- Date: 2026-07-28
- Requirements: REG-001, REG-002, REG-006, REG-011, REG-012, REG-014,
  INT-001, NFR-006

## Context

Each convention may replace its public website and visual theme every year.
Registration rules, prices, capacity, privacy boundaries, submissions, payment
state, and participation history must nevertheless remain consistent. A
server-rendered form is useful for fallback operation and testing, but it must
not become the only executable specification or force every convention to use
Maru's presentation.

Staff also need to register a person on their behalf. A separate unrestricted
admin model form would bypass the same validation and history used by an
attendee.

## Decision

Maru's versioned API and published registration definition are authoritative.
Public, personal, staff, kiosk, and future mobile surfaces are clients of the
same domain commands and queries.

- The public definition exposes edition identity, version, sections,
  questions, conditions, products, price snapshots, sale windows, purpose
  notices, and explainable availability.
- A client may arrange those semantics into any accessible visual journey.
  Layout, animation, artwork, and seasonal theme are not registration-domain
  state.
- A client may evaluate declared conditions for immediate feedback, but Maru
  validates every command again and remains authoritative for eligibility,
  capacity, price, deadlines, policy acceptance, and payment.
- The bundled server-rendered registration surface is a neutral reference and
  fallback client. It is not the contract.
- OpenAPI, generated types, examples, synthetic fixtures, and conformance tests
  are the frontend-developer contract.
- Staff registration-on-behalf uses an explicit command with separate actor and
  subject identities, permission, source, reason, and exception evidence. It
  does not insert a second kind of registration.
- Browser authentication, origin policy, CSRF, and future application scopes
  are part of the API boundary. A separate frontend build may initially share a
  domain or reverse proxy without becoming coupled to Django templates.

The first delivered public API exposes open editions and their registration
definitions. The existing authenticated self-registration API and the
server-rendered public client remain while anonymous account/profile submission
is moved behind the complete API contract.

## Consequences

Conventions can redesign the attendee journey without changing financial or
historical records. The reference client provides an accessible minimum and a
test oracle, while independent clients remain free to use different
interaction patterns.

Maru must maintain compatibility and deprecation policy for published
definitions. A frontend cannot safely hard-code prices, eligibility, required
questions, or sale dates. Full independent anonymous clients still require
production identity, upload, abuse-control, and application-origin contracts.

## Alternatives considered

- Treat Django templates as the product contract: rejected because seasonal
  public experiences would require backend forks.
- Store a general visual page-builder document in registration: rejected
  because layout is not domain state and arbitrary presentation schemas become
  difficult to validate or keep accessible.
- Let every frontend implement registration rules: rejected because price,
  capacity, privacy, and historical meaning would diverge.
- Give staff direct model creation: rejected because it bypasses lifecycle,
  authority, audit, and attendee-visible consequences.
