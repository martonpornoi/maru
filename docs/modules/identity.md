# Identity module

Status: Verified identity lifecycle, explicit platform administrators, human
login handles, session controls, safe activity labels, scoped restrictions,
strict platform account-invitation HTML/API adapters, the repository-verified
User accounts first experience slice, and an author-verified retention-v10
corrective candidate; complete rendered owner acceptance, independent retention
acceptance, production policy activation, and writer cutover remain gated
Last updated: 2026-08-31

## Purpose and requirements

`maru.identity` owns the authentication-facing platform account and assurance
boundary for IDN-001, IDN-006 through IDN-008, IDN-010, IDN-011, IDN-013,
AUD-002, PRI-001, and UX-029. It does
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
- bounded abuse counters for public identity flows;
- versioned platform account invitations, command receipts, single-use
  challenge lineage, encrypted durable delivery, reconciliation, retention
  assessment/disposition, and fair scheduler evidence; and
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
- `deactivate_person_account_for_platform_emergency(...)`, an internal,
  platform-only identity command called inside a domain-owned outer
  transaction after every open relationship has been contained;
- `account_display_labels(account_ids)`, a bounded internal read projection
  returning display name or the generic `Maru account` fallback without email,
  login handle, authentication state, or contact data;
- `active_person_account_display_labels(account_ids)`, the narrower bounded
  Organization structure adapter that returns a minimized display label only
  while the already-authorized relationship points to an active `person`
  account;
- `resolve_active_verified_account_reference(account_id, lock=False)`, the
  identifier-only principal seam for cross-module commands and sensitive
  queries; it returns an immutable UUID reference only while the exact account
  is currently active and email-verified, and can lock that identity row inside
  a caller-owned transaction without releasing an account model or contact
  data;
- `create_platform_account_invitation(...)`,
  `reissue_platform_account_invitation(...)`,
  `revoke_platform_account_invitation(...)`, and
  `accept_platform_account_invitation(...)`, the sole invitation domain
  writers used by both HTML and API adapters;
- `load_platform_account_inventory(...)` and
  `load_platform_account_invitation_detail(...)`, the bounded, version-fenced,
  mandatory-audit invitation projections;
- `activate_configured_invitation_retention_policy(...)`, the migration-owner
  control that pins one reviewed environment-policy digest;
- `place_invitation_retention_hold(...)` and
  `release_invitation_retention_hold(...)`, the platform-administrator legal/
  security hold boundary; and
- `run_platform_invitation_retention(...)`, the bounded, policy-bound cleanup
  worker for exact abandoned invitation identities;
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
GET  /api/v1/platform/accounts
POST /api/v1/platform/account-invitations
GET  /api/v1/platform/account-invitations/{invitation_id}
POST /api/v1/platform/account-invitations/{invitation_id}/reissue
POST /api/v1/platform/account-invitations/{invitation_id}/revoke
POST /api/v1/public/account-invitations/accept
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

Every invitation API mutation requires a canonical lower-case UUID in the
`Idempotency-Key` header and rejects retry metadata in JSON. Protected adapters
resolve fresh active platform-administrator authority, and production step-up
for mutations, before parsing that header or the closed JSON body. Creation
returns `201`, while replay returns the original minimized resource with a
replay indicator. Expected invitation versions govern reissue and revocation;
all failures use RFC 9457 problem details with non-disclosing stable codes.

The platform account inventory API authorizes fresh active platform oversight
before parsing its closed query. It exposes only bounded identity and current
invitation summaries, supports exact/prefix search plus account kind and state,
uses a version-bound signed cursor with a caller-selected page size of at most
100, and appends the required sensitive-read audit before releasing any name.
Stale cursors, projection overflow, and audit or dependency failure return no
partial identity data.

Public acceptance is deliberately independent of any ambient Django session:
the single-use invitation challenge is the authority, and an unrelated signed-
in cookie is ignored. This keeps the JSON bearer flow CSRF-independent without
turning session ownership into invitation authority. It accepts JSON only,
never accepts a token in path or query, requires two matching recipient-entered
password fields, applies the configured password validators and abuse limits,
and never reflects the token, password, or invited identity in an error.
Exact-origin credentialed CORS includes `Idempotency-Key`; unapproved origins
receive no CORS grant.

Staff restrictions are created, revoked, and appealed through edition-scoped
APIs. A restriction contains only an attendee-safe message in ordinary self
views; internal safety or conduct evidence remains behind its own boundary.
Due consequences cancel open registration, suppress a public profile, revoke
credentials where applicable, and retain paid/history evidence for human
finance review.

The due-restriction scheduler owns Identity evidence, so an edition-scoped
candidate must first match an exact profile that adopts Identity; global
organization restrictions remain explicitly edition-neutral. Registration and
Accreditation then enforce their consequences independently through
`registration.identity-restriction-consequence@1` and
`accreditation.identity-restriction-consequence@1`. A profile such as
`workforce_only@1` may therefore apply and publish the Identity restriction
exactly once while leaving any retained Registration or credential rows
unchanged. A requested account notification is also omitted unless that exact
profile pins the notification effect route.

## User accounts management experience

ADR 0055 presents the platform inventory as **User accounts** and indexes
stable identity-task vocabulary such as `users`, `staff`, and `volunteers` in
the shared code-owned navigation search. This is presentation metadata only;
it does not enumerate hidden accounts, add keywords from record values, or
change the inventory's platform-administrator authorization and mandatory
sensitive-read audit.

The inventory leads with bounded search results and one contextual **Invite
account** action. Invitation detail remains version-fenced and status-aware,
then explains the next valid action: reissue or revoke where allowed, return to
User accounts, or—only after acceptance—continue to an explicitly chosen
organization's Board setup. Account creation still grants no organization
membership, participation, registration, workforce role, or authority.

The shared responsive drawer and page primitives are owned by `maru.core`.
Identity's focused HTML matrix covers the User accounts, invitation creation,
and invitation-detail presentation; the complete authenticated ADR 0055
width/zoom, keyboard, screen-reader, state, and owner matrix remains open.

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

The workforce structure projector may call
`active_person_account_display_labels(...)` only after bounding its holder set
and validating each linked RoleAssignment's current exact lineage. Identity
then owns the final active-person filter. Inactive accounts, platform
administrators, invalid role evidence, and missing identities release no
holder label; login handles and email are never part of this projection.

## Retention and archive

Account deletion cannot cascade into organizer or event records. Subject-rights
and retention workflows route each domain relationship according to its
controller and policy without deleting required finance, safety, or audit
evidence.

Revoked and expired invitation identities use a narrower anonymization path,
not account deletion. It requires exact sole-invitation provisioning origin,
an inactive unverified person with no usable password, closed C4 delivery,
only terminal invitation challenges/security events, no hold, and no other
account relationship or sibling invitation. Both Django and PostgreSQL fail
closed on current and future relationships. The candidate processes arbitrary
legitimate challenge history in bounded chunks and records one versioned,
value-minimized current assessment even when a candidate is blocked or held,
so neither a blocked nor held oldest row can starve later eligible work. Held
rows advance the fair cursor and appear in the heartbeat's held count, but
remain excluded from the actionable readiness backlog until audited release.

A successful transaction writes the policy receipt and exact system audit,
tombstones account/challenge contact and every non-empty delivery, attempt, and
late-outcome provider reference with one-way non-routable values, replaces
terminal lookup digests, and preserves append-only lifecycle/security history.
Permanent receipt-aware PostgreSQL guards prevent later account, challenge,
membership, delivery, provider-reference, receipt, or assessment forgery. The
one receipt-bound raw-provider-to-tombstone transition is followed by complete
parent-delivery immutability, and a disposed assessment is terminal. Policy,
hold, receipt, assessment, scheduler, and cursor evidence uses the PostgreSQL
clock; public services accept no evidence-time override, policy JSON rejects
duplicate members, and retention sources are exactly `operator` or
`scheduler`. A disposed assessment is permanently bound to the exact immutable
receipt policy digest that authorized its disposal, even after a supported
later policy activation. New non-disposed assessments continue to require the
currently activated policy digest. Accepted accounts never enter this
workflow.

Emergency account deactivation is global: it marks the person inactive,
revokes every inventoried session, appends a minimized security event, and
records one organization-neutral privileged audit. The calling domain must
close all scoped authority and relationship rows first in the same transaction;
identity deliberately does not import organizer models or invent that scope.

## Tests

PostgreSQL and API tests cover normalization, duplicate prevention,
verification, recovery non-enumeration, invalid/expired challenge behavior,
session inventory/revocation, privileged step-up, rate limits, append-only
security history, scoped restriction issue/revoke/consequence, appeal decision,
authorization, and cross-tenant denial. `identity_delivery` durably delivers
pending challenges and reports success/failure for supervision.
Organization structure integration tests additionally prove that identity labels are not
queried until authorization has retained current role evidence and that
inactive or platform-classified accounts are omitted.
The focused Registration setup and account onboarding API suite additionally proves closed/server-owned-field
rejection, authorization and step-up before parsing, canonical idempotency,
safe replay/conflict behavior, audited bounded inventory/detail projections,
cursor and page-size limits, random-versus-revoked non-enumeration, adversarial
password-validator message minimization, throttling, JSON media type, ambient-
session independence, exact-origin CORS, and closed OpenAPI schemas.
The retention suite additionally proves strict no-default policy parsing,
monotonic owner activation, hold/release evidence, due and bounded disposal,
privacy/group/security/future-relationship blocking, strict database-time and
source guards, arbitrary challenge history, permanent tombstones, complete
provider-reference disposal, assessment/receipt binding, fair cursor
wraparound, rollback on audit failure, concurrent worker idempotency, exact
origin races, test-only reset isolation, populated-v7 upgrade, and the live-
data downgrade fence. The populated-upgrade rehearsal explicitly proves that
a v7 receipt created under policy v1 still upgrades after the control advances
monotonically to policy v2, without rewriting the historical policy evidence.

## Limitations

Email/password, email challenge, session inventory, and password-confirmation
step-up form a complete local boundary but are not passkeys or phishing-
resistant MFA. Production must configure and supervise email delivery, tune
distributed rate coordination for its topology, define platform suspension and
duplicate-account merge procedures, and complete security review. Restriction
records are not a substitute for a restricted conduct-case system.
Registration setup and account onboarding invitation routes remain production-gated until the accepted retention
schedule, delivery-worker heartbeat, stopped-writer generation, deployment
recovery rehearsal, and full readiness contract pass; route reachability is not
that cutover evidence.
