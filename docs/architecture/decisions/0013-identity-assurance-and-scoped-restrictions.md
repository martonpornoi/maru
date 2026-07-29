# ADR 0013: Identity assurance and scoped restrictions

Status: Accepted  
Date: 2026-07-28

## Context

Public registration can hold scarce capacity and privileged staff commands can
change admission or money. A global `is_active` flag cannot safely represent an
organizer ban: it is too broad, cannot express purpose or expiry, and gives no
appeal path. Seasonal frontends also need the same account-security boundary as
the bundled client.

## Decision

- Email verification uses expiring, single-use challenges. Production denies a
  capacity-holding submission until verification unless a separately reviewed
  provisional policy is enabled.
- Recovery returns a non-enumerating response. Challenge issue and consumption
  are rate limited and recorded in account security history.
- Every authenticated browser session is inventoried by a digest and may be
  revoked individually or as a set.
- Privileged identity, finance, registration-exception, privacy, accreditation,
  and closure commands require a recent step-up in production.
- Organizer restrictions are separate records scoped to an organization and
  optionally an edition. Their kind, effective period, attendee-safe message,
  internal reference, issuer, consequence application, revocation, and appeal
  evidence are durable.
- Registration, attendance, public-profile, credential, and communication
  consequences are enforced at the owning service boundary. Other organizers
  cannot discover the restriction or its rationale.
- Browser API use is cookie and CSRF based. Cross-origin seasonal clients are
  allowed only from an exact production allowlist; wildcard credentialed CORS
  is prohibited.

## Consequences

One account remains usable across organizers without turning one organizer's
decision into a platform-wide ban. Operators must run the durable identity
delivery command and own restriction/appeal queues. Account merge and
organization-independent platform suspension remain separate future
workflows.

## Alternatives considered

- Using only `Account.is_active` was rejected because its scope and consequence
  are not explainable.
- Letting each frontend implement authentication was rejected because it would
  split identity assurance and abuse controls.
- Wildcard CORS was rejected because authenticated cookies require explicit
  trusted origins.

## Requirements affected

IDN-001, IDN-004 through IDN-008, AUD-002, REG-011, REG-014, SEC-001,
SEC-003, INT-001.
