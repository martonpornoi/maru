# Identity module

Status: Verified identity lifecycle, explicit platform administrators, human
login handles, session controls, safe activity labels, and scoped restrictions
implemented
Last updated: 2026-08-01

## Purpose and requirements

`maru.identity` owns the authentication-facing platform account and assurance
boundary for IDN-001, IDN-006 through IDN-008, IDN-010, IDN-011, AUD-002,
and PRI-001. It does
not own organizer profiles, participation, applications, HR, orders, finance,
or conduct cases. ADR 0013 defines verified identity and scoped restrictions.

## Owned data and invariants

- opaque UUID account ID;
- normalized case-folded email and optional human login handle;
- explicit `person` or `platform_administrator` account classification;
- display name and preferred language;
- active/staff state and Django authentication timestamps;
- password verifier and Django permission relations required for bootstrap
  administration; and
- append-only account security events for safe user-visible history;
- expiring, single-use verification and recovery challenges;
- session inventory and revocation evidence;
- bounded abuse counters for public identity flows; and
- organizer/edition-scoped restrictions with consequence and appeal evidence.

Email is non-empty and case-insensitively unique at the PostgreSQL boundary.
The optional login handle is also case-insensitively unique, is stripped before
storage, and rejects control characters while retaining printable public
handles. Local sign-in accepts either exact email or handle without changing
email's role as the account bootstrap/recovery address. Missing and ambiguous
identifiers follow the same password-hasher timing path.
The string representation does not expose email by default.

All application superusers are explicitly classified as platform
administrators, and that classification requires staff and superuser
privileges. Existing superusers are migrated to it. The classification is not
inferred from account age, email, or display name. Platform administrators may
be attributed actors for platform work, but subject models reject them as
organization members, convention authority recipients, participants,
registrants, volunteers, onboarding subjects, or workforce assignees.

## Public contracts

- `Account`
- `AccountManager.create_user`
- `AccountManager.create_superuser`
- `AccountSecurityEvent`
- `account_display_labels(account_ids)`, a bounded internal read projection
  returning display name or the generic `Maru account` fallback without email,
  login handle, authentication state, or contact data;
- `GET /api/v1/me/security-history`

Successful sign-in and sign-out signals append safe event type, outcome, source
channel, and trusted timestamp. The self API returns only the authenticated
account's events and excludes email, raw IP, user agent, and credential detail.

Public and self contracts include:

```text
POST /api/v1/public/accounts
POST /api/v1/public/accounts/verify-email
POST /api/v1/public/accounts/recovery
POST /api/v1/public/accounts/recovery/complete
POST /api/v1/public/sessions
GET  /api/v1/me/security-history
GET  /api/v1/me/sessions
POST /api/v1/me/sessions/{session_id}/revoke
POST /api/v1/me/step-up
GET  /api/v1/me/restrictions
POST /api/v1/me/restrictions/{restriction_id}/appeals
```

Public account bootstrap normalizes and case-insensitively checks email,
validates the password, creates a verification challenge, and returns the same
safe shape where enumeration would be harmful. Verification is required for a
capacity-holding submission in production. Recovery never reveals whether the
address exists. Challenges expire, are consumed once, and expose raw test
tokens only under explicit non-production settings.

Staff restrictions are created, revoked, and appealed through edition-scoped
APIs. A restriction contains only an attendee-safe message in ordinary self
views; internal safety or conduct evidence remains behind its own boundary.
Due consequences cancel open registration, suppress a public profile, revoke
credentials where applicable, and retain paid/history evidence for human
finance review.

## Permissions and sensitivity

Email and authentication state are C2. Password verifiers, challenge digests,
and session digests are C4. Django admin is bootstrap-only and security
evidence is read-only there. Operational restriction commands require explicit
tenant/edition capabilities; privileged changes require recent step-up in
production.

The specialist account list identifies people by display name or login handle
with email as a fallback, supports direct display-name/handle/email search and access-state filters,
and keeps UUID and authentication timestamps in a collapsed technical section.
It does not expose Django groups or per-user Django permissions as an
alternative to Maru's scoped authority model.

The activity module may use `account_display_labels(...)` only after its own
tenant/resource authorization and domain-event filtering. The query is a safe
label adapter, not permission to enumerate accounts; missing/deleted actors
remain a generic label and raw account identifiers are not rendered.

## Retention and archive

Account deletion cannot cascade into organizer or event records. Subject-rights
and retention workflows route each domain relationship according to its
controller and policy without deleting required finance, safety, or audit
evidence.

## Tests

PostgreSQL and API tests cover normalization, duplicate prevention,
verification, recovery non-enumeration, invalid/expired challenge behavior,
session inventory/revocation, privileged step-up, rate limits, append-only
security history, scoped restriction issue/revoke/consequence, appeal decision,
authorization, and cross-tenant denial. `identity_delivery` durably delivers
pending challenges and reports success/failure for supervision.

## Limitations

Email/password, email challenge, session inventory, and password-confirmation
step-up form a complete local boundary but are not passkeys or phishing-
resistant MFA. Production must configure and supervise email delivery, tune
distributed rate coordination for its topology, define platform suspension and
duplicate-account merge procedures, and complete security review. Restriction
records are not a substitute for a restricted conduct-case system.
