# Registration operations and tester runbook

Status: Repository-controlled safety workflows implemented; deployment approval required  
Last updated: 2026-07-30

This is the step-by-step operating procedure for preparing, opening, running,
testing, closing, and archiving one Maru registration edition. The built-in
pages are an accessible reference client. A colorful annual website may use
the same APIs; Maru remains authoritative for identity, form meaning,
eligibility, price, capacity, deadlines, payment, admission, and audit.

Never edit active configuration, registration state, payment evidence,
entitlements, credentials, or closure evidence directly in the database.

For the no-demo-database journey from first administrator through Chair,
staff-assisted attendee registration, reviewed NDA/media, workforce hierarchy,
position assignment, and access verification, follow the
[clean convention onboarding walkthrough](clean-convention-onboarding-walkthrough.md).

## 1. Assign owners before configuration

Name the people responsible for:

- Registration configuration and attendee service;
- volunteer eligibility;
- Finance and payment-provider reconciliation;
- communications and the delivery-failure queue;
- identity restrictions and appeals;
- media review;
- privacy and retention;
- safeguarding and minor policy;
- Front Desk, credentials, and offline devices;
- technical workers, monitoring, backup, and restore; and
- final go/no-go and closure.

Grant only edition-scoped capabilities. Finance, restriction, privacy,
credential, and closure actions require a recent step-up in production.
Cancellation and refund require two different authorized people.

## 2. Prepare the edition

### 2.1 Select the working edition

In the `/admin/` shell, select the exact organization and edition. The edition
context helps navigation but is never authorization.
Confirm:

- edition name, time zone, currency, locale, and lifecycle;
- registration open and close instants in edition-local time;
- overall capacity and expected peak load;
- support contact and escalation route; and
- retention, privacy, safeguarding, payment, refund, and conduct policies.

Use synthetic data in rehearsal. Never clone unrestricted production personal
data.

### 2.2 Create a draft

Create one registration configuration:

- from blank;
- from an immutable approved template; or
- by copying a prior edition within the same organization.

Copying creates independent rows and records provenance. It does not link the
old and new forms. Review every copied question, policy reference, date, price,
capacity, language, and product before activation.

### 2.3 Build the form

For every configurable question, set:

- stable key and attendee-facing label;
- ordered section;
- short/long text, yes/no, integer, single-choice, or multiple-choice type;
- required and conditional-display rules;
- purpose;
- C1/C2 classification and staff visibility; and
- choices where applicable.

While the configuration or reusable template is draft, remove obsolete
sections, questions, and products with their inline **Delete** checkbox and
save. Review the result before activation. Once a configuration is active or a
template is published, these rows are intentionally immutable; create a new
version instead.

Maru rejects unknown answers and answers to hidden conditional fields. Do not
use free text for a staff-owned fact such as volunteer department or discount
eligibility.

Review the fixed profile contract:

- legal name, date of birth, contact/address, and emergency contact are
  edition-owned and purpose-restricted;
- telephone fields pair country initials, flag, and calling prefix with the
  entered number, then validate and store canonical E.164;
- pronouns use the maintained list; `Other` alone reveals and requires
  `Other pronouns`;
- bio is optional and limited to 500 characters;
- spoken languages use the supplied ISO 639-1 vocabulary, maximum five;
- public-attendance consent is separate, optional, and never copied as selected;
- profile image is optional and private until safety processing and approval;
- `brings fursuits` is opt-in; when enabled, up to ten independently editable
  fursuits may have name, species, and image.

A returning attendee may receive the latest compatible same-organization
profile as a clearly labelled suggestion. They accept, change, or reject it.
Submission makes a new edition snapshot. Later edits affect only the current
edition; previous conventions and the immutable submitted answer snapshot do
not change.

### 2.4 Configure price phases

Create separate immutable admission products, not one product whose price is
edited over time:

| Phase | Eligibility | Example behavior |
| --- | --- | --- |
| Volunteer presale | Active configured participation-capacity code | Lowest price; invisible or unavailable to others with a safe explanation |
| Early bird | Anyone meeting public rules during its sale window | Lower public price and its own capacity/payment window |
| Normal | Anyone meeting public rules during its later window | Higher price, preserved as a separate snapshot |
| Complimentary/free | Explicitly configured zero price | Confirms with basis `free`, never `provider` |

For each product set code, name, entitlement code, price in minor units,
currency, sale start/end, product capacity, wait-list policy, eligibility, and
optional payment-window override. Set the configuration's overall capacity,
default payment window, global wait-list switch, and automatic FIFO-promotion
switch.

Do not change the price of an active offer to create a phase. An accepted
registration retains product, price, currency, and configuration snapshots.
Maru does not automatically move someone to a more expensive product.

### 2.5 Prepare volunteer eligibility

Before the volunteer window:

1. create the volunteer capacity/role in the participation module;
2. assign it only after the volunteer decision is authoritative;
3. configure the offer to require that capacity code;
4. test an accepted volunteer, an ordinary account, an anonymous visitor, an
   expired assignment, and a different edition.

Attendees cannot self-assert volunteer status in a form answer.

### 2.6 Configure minor admission

Keep the minimum age adult-only unless safeguarding and legal owners approve a
minor policy. If minors are admitted, activate one versioned policy with age
bands, guardian relationship, consent text/version, expiry, communication, and
check-in rules. Test dates on every boundary.

A registration needing consent enters `guardian_pending`; it does not reserve
paid capacity or ask for payment. The guardian accepts the exact policy version
through the expiring link. Invalid, expired, mismatched, or repeated acceptance
does not advance the registration.

### 2.7 Configure providers and delivery

For a selected hosted payment provider, create an organization-scoped provider
account containing:

- stable provider code and adapter name;
- HTTPS API base URL on `MARU_PAYMENT_PROVIDER_HOSTS`;
- the names—not values—of the credential and webhook-secret environment
  variables; and
- disabled state until sandbox certification passes.

Secrets stay in the deployment secret manager. The generic JSON adapter is a
contract, not proof that a chosen vendor is certified.

Configure SMTP and the from address. Verify registration service mail reaches
test inboxes and that the canonical Maru inbox still works with email disabled
or failing. Assign the permanent delivery-failure queue.

Configure ClamAV, protected object storage, safe public-rendition storage, and
retention lifecycle. Uploaded images must receive safety evidence before
moderation.

### 2.8 Activate

Run the review checklist:

- source and reviewer reason recorded;
- open/close and every sale/payment time checked in edition-local time;
- purpose/visibility shown for every field;
- required agreements and versions correct;
- volunteer, early-bird, normal, free, capacity, and wait-list cases tested;
- minor policy either approved and tested or adult-only;
- provider amount/currency/webhook/replay/error sandbox matrix passed;
- inbox/email/failure queue tested;
- image scan/moderation/publication tested;
- headless and bundled clients return the same definition/outcomes;
- scheduler, effects workers, metrics, alerts, backup, and restore ready.

Activation freezes the configuration. Correct a mistake by creating and
reviewing a new version; never rewrite the active version.

## 3. Build or validate the seasonal frontend

The API is the frontend developer's reference. Start with:

```text
GET  /api/v1/public/csrf
POST /api/v1/public/accounts
POST /api/v1/public/accounts/verify-email
POST /api/v1/public/sessions
GET  /api/v1/public/editions
GET  /api/v1/public/editions/{edition_id}/registration
POST /api/v1/public/editions/{edition_id}/registration/submissions
```

The frontend renders the returned products, purposes, fields, choices,
conditional rules, profile vocabulary, policy versions, availability reasons,
price/currency, payment window, and wait-list consequence. It sends the exact
configuration version and policy acceptances plus a UUID idempotency key.
Maru recalculates everything; a client-supplied price or eligibility claim is
never trusted.

For cookie-authenticated browser use:

1. serve only through HTTPS in production;
2. add the exact origin to `MARU_REGISTRATION_CLIENT_ORIGINS`;
3. add it to `MARU_CSRF_TRUSTED_ORIGINS`;
4. fetch the CSRF token and send it on unsafe requests;
5. use credentials with requests; and
6. never use a wildcard credentialed origin.

Changing the visual site each year does not require copying domain rules.
Version `v1` URLs are stable; regenerate the OpenAPI client and run the
conformance scenarios before deployment.

## 4. Open and operate registration

Registration becomes discoverable only when the edition and active
configuration are open and the selected offer is in its own window.

An authorized registration lead may deliberately create a registration
outside those windows through Convention work → Registration. Maru exact-matches an
active account by normalized email. If none exists, staff sees a warning and
must explicitly supply the new account's display name and temporary password.
Transfer that password through a separate secure channel; the new account is
unverified until the identity workflow completes. An inactive or concurrently
created identity is never overwritten.

Staff must record why they are acting for the attendee. This exception ignores
only public sale timing: it cannot bypass restrictions, active-version review,
age/answers, eligibility, price, capacity, duplicate protection, payment, or
waiting-list behavior. Confirm that paid staff-assisted registrations remain
payment pending, admin shows their source/actor/reason, and a newly created
identity has its own privileged audit event.

During an active window, continuously run supervised:

```powershell
uv run python src/manage.py registration_lifecycle
uv run python src/manage.py identity_delivery
uv run python src/manage.py effects_worker --pool interactive
uv run python src/manage.py effects_worker --pool delivery
```

Run lifecycle at least once per minute. Run identity delivery frequently enough
for the verification/recovery objective. Effects workers are long-running
supervised processes; configure the pools required by the deployment.

Inspect registration metrics for one tenant/edition:

```powershell
uv run python src/manage.py registration_metrics `
  --organization ORGANIZATION_UUID `
  --edition EDITION_UUID
```

Alert on stale lifecycle success, command failure, oldest overdue reservation,
candidate backlog, capacity drift, open payment exceptions, permanent delivery
failure, outbox quarantine, pending media, open appeals/corrections, and offline
conflict.

## 5. Registration outcomes

Submission under database locks produces one of:

- `confirmed`: zero-price admission, basis `free`;
- `payment_pending`: capacity is held until the shown deadline;
- `waitlisted`: no capacity is held and no payment is requested;
- `guardian_pending`: no payment until required guardian consent; or
- a safe rejection explaining closed, ineligible, full-without-wait-list,
  unverified, restricted, invalid, or stale configuration.

Reusing the same idempotency key and identical request returns the same command
receipt. Reusing it with different content is rejected. Retrying must not create
a second registration or hold.

## 6. Payment and verification

### 6.1 Attendee flow

1. A `payment_pending` attendee requests a payment intent with a return origin
   from the exact allowlist.
2. Maru snapshots amount, currency, provider account, registration, deadline,
   and idempotency key before calling the provider.
3. The client redirects to provider-hosted checkout. Card data never enters
   Maru.
4. The return page reads intent/registration status. It must say “processing”
   until an authenticated webhook confirms payment.
5. Maru verifies signature and timestamp and reconciles provider account,
   intent/reference, amount, currency, state, and event identity.
6. A valid success confirms the registration, appends payment ledger/receipt,
   activates entitlement, and creates inbox/email notification.

### 6.2 Exceptions

Wrong amount/currency/account/reference, conflicting duplicate, late success,
unknown intent, malformed state, dispute, refund mismatch, or settlement drift
must enter the payment-exception or finance queue. Do not manually mark the
registration paid. Resolve through the scoped API with a reason after comparing
provider evidence.

Browser return, bank screenshot, attendee claim, and successful HTTP response
are not payment proof.

### 6.3 Deadlines

The deadline is submission time plus the product override or configuration
default. A wait-list promotion gets a fresh full window from promotion time.

Authorized staff may change a pending deadline to a future time with a reason.
The API records append-only adjustment, audit, timeline, event, and
notification. This is the supported manual modification; do not edit the row.

When the deadline passes, lifecycle expires the reservation, releases capacity,
and may promote the oldest eligible wait-listed account. A late provider event
does not silently resurrect admission; it becomes an exception for finance and
registration to resolve.

## 7. Wait-list behavior

Wait-list order is oldest eligible entry first. A wait-listed person:

- does not occupy hard capacity;
- is not asked to pay;
- can see that they are waiting, not reserved;
- receives a canonical inbox notice and optional email when offered a place;
- gets a fresh payment deadline; and
- loses no money automatically.

Lifecycle runs promotion transactionally whenever expiry, cancellation, or
other release creates capacity. Concurrent runs use row locks and idempotent
state transitions. At the offer's sale close, remaining wait-list entries are
cancelled without payment.

Product rollover is not automatic. If an early-bird queue remains while only a
higher normal price is available, staff must not move people without a future
explicit acceptance workflow.

## 8. Notifications and delivery failure

Each important event creates a localized canonical message in
`GET /api/v1/me/notifications`. Email is a projection. Operational service
messages are distinct from marketing, and an attendee can configure the email
projection without losing the inbox record.

Notifications include edition, status, edition-local deadline where relevant,
price/currency, safe action, and support path. They exclude protected profile
data and internal restriction reasons.

Transient email failure retries through the outbox. Permanent failure appears
at:

```text
GET /api/v1/organizations/{organization_id}/editions/{edition_id}/communication-delivery-failures
```

Assign an owner to contact the attendee through the approved fallback and
record resolution outside protected free-text fields. Sending failure never
changes canonical registration state. Pending and permanently failed delivery
block closure.

## 9. Banned, restricted, or inactive accounts

Do not use a global platform deactivation as an organizer ban. Issue a scoped,
reasoned restriction with kind, edition/organization, attendee-safe message,
effective/expiry time, internal reference, and notification choice.

Consequences depend on kind:

- registration restriction blocks new submission and cancels open
  guardian/wait-list/payment-pending records when due;
- public-profile restriction removes the public rendition;
- credential restriction revokes applicable credentials;
- communication restriction affects the scoped communication boundary;
- attendance restriction creates the admission/credential consequence without
  deleting finance or historical evidence.

A paid, confirmed, or checked-in registration is never erased. Staff review
refund, entitlement, credential, safety, and legal consequences. The attendee
can view the safe restriction and submit one appeal; an independently
authorized decision records whether it is upheld or changed. Other organizers
cannot see it.

`Account.is_active` remains a platform-level emergency/security control. If it
is disabled, lifecycle cancels open reservations and wait-list rows; confirmed
history is retained for urgent human review.

## 10. Cancellation, refund, receipts, and settlement

The attendee receipt endpoint lists operational receipts for their
registration. The finance projection answers who paid, for which snapshotted
product, how much, in which currency, through which provider evidence, and what
later movements occurred.

Use:

```text
GET /api/v1/organizations/{organization_id}/editions/{edition_id}/registration/reconciliation
GET|POST /api/v1/organizations/{organization_id}/editions/{edition_id}/registration/settlements
GET|POST /api/v1/organizations/{organization_id}/editions/{edition_id}/registrations/{registration_id}/financial-operations
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/registration/financial-operations/{operation_id}/approve
```

Cancellation:

1. authorized person proposes with reason;
2. a different authorized person approves;
3. Maru cancels eligible registration, revokes active admission entitlement,
   releases capacity, records evidence, and promotes wait-list if configured;
4. any money return is a separate refund operation.

Refund:

1. propose an amount no greater than the reconciled refundable balance;
2. a different authorized person approves;
3. operation waits for authenticated provider completion;
4. provider evidence appends refund ledger and credit/receipt evidence.

Disputes, chargebacks, fees, and settlements append rather than overwrite the
payment. Reconcile provider statement gross, fees, refunds, disputes,
chargebacks, net, currency, and allocations. Assign every mismatch.

Transfer, product change, and price adjustment return
`financial_operation_workflow_unavailable`. They require future
recipient-acceptance and repricing workflows.

## 11. Attendance reporting and badge preparation

Use Convention work **Reports & badges > Attendees and badges** for the
selected edition.
Access requires the edition-scoped
`registration.view_attendee_reporting` capability.

1. Check **Coming**. It means registrations currently `confirmed` or
   `checked_in`; wait-listed, payment-pending, expired, cancelled, and guardian
   pending records are deliberately absent.
2. Review **Countries** and the country breakdown. This uses the two-letter
   country in the restricted registration profile, not the optional public
   directory country.
3. Review attendee-level counts. Attendee, sponsor/super-sponsor, guest, and
   volunteer labels derive from current entitlements and capacities, not a
   self-asserted form answer.
4. Search a badge/display name or registration reference, or filter by country
   and attendee level. Clear filters before treating the displayed record count
   as the full coming population.
5. Select **Download badge CSV**. The same filters apply. Record the edition and
   generation time already present in the file when handing it to the badge
   operator.
6. Treat the file as personal operational data. Store it only in the approved
   convention workspace, share it only with badge staff, remove obsolete
   copies, and do not send it to an unapproved printer or design service.

The badge name uses the purpose-identified badge-name registration answer when
available and otherwise falls back to platform display name. The file includes
pronouns, structured language codes/labels, registration country, broad
attendee labels, state, and photo-review state. It excludes legal name, street
address, contact, emergency contact, exact product/price/payment, arbitrary
answers, and internal comments. Formula-like cell values are neutralized.

This download is data preparation only. Layout/version approval, printer
adapter, stock custody, physical issue, and reprint evidence remain under
PROD-05. More than 5,000 source rows requires the future asynchronous export
pipeline; do not bypass the limit with a raw database dump.

The public attendee page is separate. Attendees must opt in for the edition and
may enter a country specifically for that public page. Never copy the internal
report country into public content.

## 12. Safe test and rehearsal modes

There is no hidden “ignore payment” button.

Use one of:

- a zero-price synthetic product, confirmed as `free`;
- the local/test demo adapter, never production;
- the chosen provider's sandbox with non-production credentials;
- an authorized reasoned waiver, confirmed as `waiver`;
- a rehearsal edition and `.invalid` synthetic accounts.

A waiver does not create fake provider money. Reconciliation reports paid
amount, free places, and waived face value separately.

Minimum pre-launch test matrix:

| Scenario | Expected result |
| --- | --- |
| Unverified account submits | Denied in production policy; no capacity hold |
| Existing email bootstrap/recovery | Same non-disclosing behavior |
| Volunteer/ordinary/cross-edition accounts | Only authoritative active volunteer is eligible |
| Early-bird then normal | Separate price snapshots remain unchanged |
| Unknown or hidden answer | Rejected without registration |
| Same idempotency key twice | One registration; conflict if body differs |
| Capacity race | No oversubscription; loser waits or receives full result |
| Wait-list promotion | Oldest eligible entry gets fresh deadline |
| Deadline expires during payment | No silent late confirmation |
| Browser returns without webhook | Still pending/processing |
| Signed webhook repeated/reordered | One money/entitlement outcome |
| Wrong signature/amount/currency | Rejected or exception; no admission |
| SMTP transient/permanent failure | Retry/owned queue; registration unchanged |
| Pronoun `Other` | Write-in required only then |
| Six or unknown languages | Rejected; five valid codes accepted |
| Two fursuits, opt-out, opt-in | Independent rows; opt-out publishes none |
| New/corrupt/infected image | Private and rejected before publication |
| Approved same-owner image reuse | Approval and safety evidence reused |
| Cross-account image reuse | Rejected without disclosure |
| Public attendance consent withdrawn | Public row disappears immediately |
| Minor without guardian consent | No payment or confirmation |
| Restriction and appeal | Scoped consequence; safe message; no tenant leak |
| Refund proposer approves own request | Denied |
| Credential revoked offline | Conflict/rejection reconciles safely |
| Closure with any open queue | Manifest denied with named counts |
| Database restore | Counts and migrations reconcile from fresh target |

Automated coverage is under `tests/integration/`, with generated API schema and
Convention work component tests. Production acceptance must also use the selected
provider, SMTP server, ClamAV, object store, relay devices, browsers, assistive
technology, printers, representative volume, and actual on-call staff.

## 13. Close registration and archive the edition

Public intake ends automatically at configuration close. Operational closure
starts only after the last sale, payment, refund, dispute, and arrival work is
owned.

1. Transition the edition to `closing`.
2. Run lifecycle until no `guardian_pending`, `payment_pending`, or
   `waitlisted` registrations remain.
3. Resolve guardian requests, payment exceptions, financial operations,
   settlement batches, delivery pending/failures, pending media, historical
   corrections, restriction consequences/appeals, offline conflicts, and
   unfinished outbox work.
4. Reconcile provider statement, receipts, refunds, disputes, fees, waived/free
   places, capacity, entitlements, credentials, and check-in.
5. Run and record backup/restore and forward-reconciliation evidence.
6. Have independent owners review the `privacy`, `finance`, `operations`,
   `security`, and `jurisdiction` readiness gates. Each decision needs an
   evidence reference and summary. Open **Convention work → Convention
   setup → Setup guide → Edition readiness review**. Use a readable report
   name, controlled ticket/checklist reference, or secure document link as the
   evidence reference. Do not enter organization/account IDs or a timestamp:
   Maru uses the selected convention workspace, signed-in reviewer, and current
   server time automatically.
7. Read closure readiness. Every named count must be zero.
8. Generate the immutable closure manifest with the recovery reference.
9. Transition to archived. Maru rechecks that gates remain approved and
   current counts exactly match the manifest.

If new unresolved work appears after manifest generation, archival fails.
Resolve it and produce a new valid closure state through the supported
workflow—never patch counts or disable gates in production.

## 14. Production go/no-go boundary

Repository checks alone do not authorize real personal data. Go only when:

- a selected hosted provider and SMTP/ClamAV/object-store deployment pass
  sandbox and failure rehearsals;
- scheduler, workers, metrics, alerts, backups, restore, secret rotation,
  provider disablement, relay, device, and manual fallback are installed;
- representative load and migration rehearsal meet the forecast;
- retention policies are approved and provisioned through a controlled path;
- staff queues have named owners and response expectations;
- seasonal frontend passes OpenAPI/conformance, accessibility, origin, CSRF,
  abuse, and browser tests;
- unsupported transfer/product/price-change paths are reflected in policy and
  support scripts; and
- privacy, finance, safeguarding, security, jurisdiction, operational owners,
  and event leadership approve the readiness gates.

See [registration module](../modules/registration.md),
[identity](../modules/identity.md), [communications](../modules/communications.md),
[accreditation](../modules/accreditation.md),
[privacy operations](../modules/privacyops.md), and the
[registration backlog](../project/REGISTRATION_TODO.md).
