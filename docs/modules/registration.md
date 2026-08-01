# Registration module

Status: Registration, extensible profiles, staff-assisted intake, reporting, provider-payment, finance, media, minor, credential, and closure boundaries implemented
Last updated: 2026-08-01

## Purpose and requirements

`maru.registration` owns edition registration configuration, attendee
registration state, staff-assisted intake evidence, provider-neutral payment and operational finance evidence,
admission entitlements, direct check-in evidence, and audience-specific
operational timelines. The implemented vertical covers EVT-002, EVT-003,
AUD-002, ACT-001, IDN-006, IDN-011, and REG-001 through REG-022.

ADR 0007 governs configuration reuse. ADR 0009 governs public registration and
the edition-owned profile foundation. ADR 0010 governs headless clients and
the reference renderer. ADR 0011 governs phased offers, reservations,
waitlists, deadlines, and payment exceptions. ADR 0012 supersedes the older
paid-directory rendition and governs explicit profile suggestions,
current-profile amendment,
structured pronouns/languages, multiple fursuits, media review/reuse, and the
public attendee rendition. ADRs 0013 through 0017 govern identity assurance,
provider finance, notifications, minors/media/privacy, credentials, offline
arrival, and closure. ADR 0018 adds the separately consented public-country
field, authoritative public attendee labels, and the first minimized
attendee-reporting preset. Registration data is always owned by one
organization and event edition.
Registration validation rejects a platform administrator as its attendee
subject. The account may still be retained separately as the attributed actor
of a permitted staff-assisted or platform operation.
PostgreSQL enforces the same distinction for the registration, attendee
profile, and fursuit subject account while leaving `submitted_by` and media
reviewer provenance untouched.
ADR 0019 adds staff-assisted registration while preserving the ordinary
policy, capacity, price, and payment lifecycle. ADR 0020 adds explicit,
audited account creation when the entered email has never belonged to an
account.
ADR 0029 adds reviewed, append-only post-submission profile extensions without
rewriting immutable registration answers or duplicating authoritative ticket,
payment, capacity, restriction, or role facts.

## Configuration and templates

An organizer can create a registration configuration draft:

- from a blank setup;
- from an immutable published template; or
- from the latest active or retired registration version of another edition in
  the same organization.

Every copy creates independent edition-owned question and product records. It
retains source provenance, starts in `review required`, and cannot become active
until an authorized organizer records a review reason. Activating a draft
retires the former active version and freezes the selected version. Editing an
open or historical form in place is prohibited by model validation and
PostgreSQL triggers.

An active configuration can be published as a new immutable template version.
Templates may be limited to one convention series or available to all
conventions owned by the organization. Cross-organization copying is denied.

Draft questions support:

- named, ordered sections with short attendee-facing descriptions;
- short and long text;
- yes/no;
- whole numbers;
- single and multiple choice;
- required and conditional display;
- explicit collection purpose;
- attendee-and-staff or registration-staff visibility; and
- C1 internal or C2 personal classification.

C3/C4 convention-defined questions are intentionally unavailable. The fixed
registration profile is the purpose-specific exception: legal name, date of
birth, address, and emergency contact have an explicit policy registry,
restricted workflow, and edition-owned retention boundary.
Public and attendee-self projections include only
`attendee_and_staff` questions. Staff-assisted intake may additionally complete
`registration_staff` questions. Unknown or staff-only answer keys are rejected
at the service boundary rather than merely hidden by the browser.

Admission products support edition-phase sale windows, active
participation-capacity eligibility, attendee-facing eligibility explanations,
product capacity, optional waitlisting, and a product payment-window override.
The configuration owns the default payment window, overall waitlist switch, and
automatic FIFO promotion switch. Volunteer, early-bird, and normal prices are
separate immutable offers.

Bootstrap editing is available at:

```text
/admin/identity/account/
/admin/registration/registrationconfiguration/
/admin/registration/registrationtemplate/
/admin/registration/registration/
/admin/registration/registrationsubmission/
/admin/registration/attendeeregistrationprofile/
/admin/registration/registrationprofileextensionfield/
/admin/registration/registrationprofileextensionvaluerevision/
```

Sections, questions, and products are inline on draft records. A question can
be assigned to a section on the same draft. Draft configurations also set the
minimum public-registration age. Active configurations and published templates
are read-only. Every draft inline has a remove checkbox; deletion is permitted
only before activation/publication.

When bootstrap administration has a selected convention workspace,
configuration, registration, payment, entitlement, submission, check-in, and
timeline pages show only that edition's records. Reusable template choices
remain visible when they belong to the same organization and are either
organization-wide or limited to the selected convention series. The explicit
source-edition picker can show other editions in the same organization, even
when the selected edition has no configuration yet; it excludes the selected
edition itself and every other organization. Copying through either exception
still creates an independent target-edition draft that requires review.

Registration and submission records are presented as read-only inspection
dossiers. A registration detail renders the immutable question-and-answer
snapshot submitted by the attendee, then clearly separates organizer-managed
facts: account/restriction state, one or more role assignments, convention
capacities, entitlements and Infinity-holder status, received and returned
amounts, staff-only timeline comments, and direct links to profile, fursuit,
guardian, payment, finance, receipt, credential, and timeline records. The
account detail page provides the cross-convention view of those relationships
and ticket/payment history. These views are an inspection and navigation aid;
workflow-owned status, finance, restriction, and authority records remain
read-only and must change through their application services.

Authorized staff can use `/admin/registration-assist/<edition_id>/` from the
Convention work Registration section outside public configuration and product
sale windows. It is the only staff-assisted intake route; former `/manage/...`
and `/staff/...` aliases are removed. An exact
normalized email match uses the existing active account. If the email has
never belonged to an account, the form visibly enters an explicit new-account
fallback and requires a display name and policy-valid temporary password.
Account, participation, registration, profile, deadline, audit, and timeline
are one transaction; an inactive or raced existing identity is never
overwritten. Staff must supply a reason. Maru records `staff_assisted`, the
acting account, a staff-only timeline entry, and a separate privileged account
creation audit where applicable. It still validates active configuration,
restrictions, age, answers, offer eligibility, capacity, price, payment
deadline, and duplicates. A paid product remains `payment_pending`.

## Public registration and attendee profiles

The local landing page links directly to `/register/`. Anonymous visitors see
only editions with an active configuration whose registration window is open.
They select an edition, choose an admission product, create a Maru account, and
submit the edition's configured sections in one transaction. If the email
already belongs to an account, the form does not modify it and sends the person
through sign-in instead.

Authenticated returning attendees use the same chooser. It separates their
existing registrations from other open editions. For a later edition in the
same organization, Maru may show the latest earlier profile as a clearly
sourced suggestion. The attendee reviews or changes it before submission;
public-list consent is always off. Submission creates a separate profile, so
the source convention never changes.

The fixed edition profile collects:

- real name and date of birth;
- phone with country initials, flag, international calling prefix, and
  canonical E.164 storage; optional Telegram handle; and a controlled pronoun
  choice with conditional `Other pronouns`;
- address, locality, postal code, region, and country;
- emergency contact name and the same structured telephone entry;
- an optional 500-character bio and up to five ISO 639-1 spoken-language
  codes;
- an optional protected profile image; and
- an explicit `brings fursuits` choice with up to ten named fursuits, optional
  species, and independently protected images.

Every collected category has a documented purpose, classification, visibility,
and retention rule in `profile_policy.py`. Restricted identity, birth date,
address, and emergency contact data are never placed in the Front Desk or
attendee-directory projections. Profile scope is redundantly tied to its
registration, organization, edition, and account, with model and PostgreSQL
guards against mismatch, scope mutation, and ordinary deletion.

The profile is editable by its owning active account while the edition has not
ended and is neither archived nor cancelled. Edits increment a separate
profile aggregate, append an attendee timeline item, audit the command, and
publish an outbox event. They never update `RegistrationSubmission`.

### Post-submission profile extensions

An organizer may add a reviewed, versioned edition profile field after
registration opens. Definitions record key, version, purpose, classification,
attendee visibility, writer policy, source provenance, reviewer, and lifecycle
state. An active definition is immutable; corrections create a new version and
retire the old version.

Each write appends a `RegistrationProfileExtensionValueRevision` with a stable
field key and increasing sequence. Attendee writes are allowed only for the
owning registration and an attendee-visible `attendee` or
`attendee_and_staff` field. Registration staff may write
`registration_staff` or shared fields with `registration.register_on_behalf`
and a mandatory reason. Staff-only definitions and values are absent from the
attendee projection. Database triggers enforce edition scope, reviewed active
definitions, active-definition immutability, and append-only values.

The Marucon rehearsal includes an attendee/staff address-detail field and a
staff-only identity-check field. It deliberately does not create an
`Infinity-holder` checkbox: Infinity eligibility, selected product, and active
entitlement remain authoritative domain records. Reserved extension-key
prefixes reject attempts to copy those facts into free-form profile fields.

Public-list participation is a separate versioned edition opt-in. The list is
anonymous/public, but a row appears only after registration reaches confirmed
or checked-in state. It exposes display name, pronouns, bio, spoken languages,
fursuit names/species, and approved images; it excludes real name, birth date,
address, email, phone, Telegram, emergency contact, registration answers,
product, price, and payment state. Withdrawal removes the row immediately.

Under consent version 3, an attendee may separately enter a two-letter country
for the directory. It is never copied from the registration address or a prior
edition. Broad attendee, sponsor, super-sponsor, guest, and volunteer labels
derive from active entitlements and participation capacities. Text remains
visible alongside color, and exact product/payment facts stay private.

Each image has `none`, `pending`, `approved`, or `rejected` review state. A new
or replacement image is pending and owner/moderator-only. Edition-scoped
moderators inspect an audited queue and record approve/reject with a reason;
the result appears in the attendee timeline. Anonymous image delivery requires
both approved state and a currently eligible public-list row. An exact approved
file can be reused by the same account inside the same organization without a
new wait; a replacement file is always pending.

The profile's `Roles and benefits` section is not free-form attendee data.
Volunteer departments come from active or proposed participation capacities,
and ticket-holder status such as `Infinity ticket holder` comes from active
registration entitlements. Administrators extend these authoritative sections
by assigning capacities and configuring admission-product entitlements.

Current public routes are:

```text
/register/
/register/<edition_id>/
/register/<edition_id>/profile/
/register/<edition_id>/profile/demo-payment/
/register/<edition_id>/profile/edit/
/register/<edition_id>/attendees/
/register/media/profile/<profile_id>/
/register/media/fursuit/<fursuit_id>/
```

The demo-payment profile route is POST-only and available solely when the
local/test payment adapter is enabled. Production never exposes it. Profile
pages also link to the edition's volunteer opportunities and private requested
onboarding documents owned by `maru.workforce`.

## Attendee lifecycle

The implemented lifecycle is:

```text
active configuration
  -> eligible product in its sale window
  -> payment pending, waitlisted, or confirmed free
  -> waitlist offer with fresh payment deadline
  -> provider confirmation or reasoned waiver
  -> entitlement active
  -> checked in

payment deadline -> expired -> capacity released -> oldest waitlist offer
inactive account open record -> cancelled
registration close -> remaining waitlist entries cancelled without payment
```

Submission validates the visible conditional schema, rejects unknown answers,
locks product and total capacity, and stores:

- configuration version;
- exact question schema;
- normalized answers;
- product name and price snapshots;
- currency;
- attendee-facing reference; and
- first operational timeline item.

A zero-price product confirms immediately. A paid product reserves capacity
until its explicit deadline. A full product may create a
non-capacity-consuming waitlist entry. The lifecycle processor expires overdue
reservations, closes waitlists after their sale period, cancels open records
for inactive accounts, and offers released capacity to the oldest
active-account entry under row locks.

A paid product uses a hosted payment adapter boundary. Maru records the
provider account and local intent, validates the configured return origin and
provider hosts, and returns a hosted checkout URL without accepting card data.
The browser return is status only. An HMAC-authenticated, timestamp-bounded
webhook reconciles provider account, intent, registration, amount, currency,
state, and idempotency identity. Duplicate events converge; late, conflicting,
mismatched, or uncertain events create a staff-owned payment exception.

The generic JSON hosted adapter and webhook protocol are implemented.
Production still has to supply a selected provider endpoint, credentials,
secret, sandbox evidence, and vendor-specific certification. The local/test
demo adapter remains disabled in production.

Authorized exception staff may set a future payment deadline or waive a
payment. A waiver is confirmation basis `waiver`, not provider payment.
Deadline changes, waivers, promotions, expiry, and cancellation create
append-only adjustment evidence, audit, attendee timeline, domain event, and
outbox work.

Successful confirmation grants the configured entitlement. Authorized Front
Desk staff can check in only a confirmed registration and must supply a reason.
Check-in creates append-only evidence and advances the registration version.

Provider payment appends an operational ledger entry and receipt. Refund and
cancellation are dual-controlled: one authorized staff member proposes and
another approves, then provider refund evidence completes the operation and
updates receipts/entitlement as appropriate. Provider fees, disputes,
chargebacks, and settlement allocations remain append-only and reconcile by
provider account, currency, and statement identity. Transfer, product change,
and price adjustment are explicitly rejected until their acceptance, capacity,
pricing, and fulfilment rules exist.

When an active minor policy requires guardian consent, submission enters
`guardian_pending` instead of holding paid capacity. A guardian accepts the
exact version through an expiring challenge before normal reservation or free
confirmation continues.

Images pass size/type/decode checks, malware scanning, metadata stripping, and
safe-rendition encoding before entering moderation. Safety evidence follows
approved exact-file reuse; disposal removes storage only when no protected
reference remains.

## Embedded Convention work experience

`My registration` renders the active edition-specific product and question
configuration. Conditional questions appear from the attendee's answers. After
submission it becomes a status, entitlement, and operational-history view.

`Registration` provides two capability-scoped projections:

- configuration managers see active provenance, questions, products, copy from
  template, copy from edition, draft review/activation, publication, and a link
  to the bootstrap draft editor;
- registration service staff see a minimized attendee queue, payment state,
  active entitlements, operational timeline, and check-in action.

Registration also links authorized organizers to staff-assisted registration,
workforce hierarchy administration, onboarding-document review, and the public
opportunity preview.

Finance-authorized staff see product-and-currency reconciliation separating
provider-paid amount, waiver face value, free places, outstanding reservations,
waitlisted, expired, and cancelled records. Exception-authorized staff can
change a deadline or waive payment with a required reason.

The Front Desk projection excludes email, form answers, HR data, safety cases,
and unrelated participation. Today shows typed configuration-review and
arrival-ready actions when the current account has the matching capability.

`Reports` uses `registration.view_attendee_reporting` and includes only
confirmed or checked-in registrations. Its summary answers how many people are
coming, checked in, volunteering, represented by approved photos, and grouped
by registration-country or authoritative attendee level. The preview and CSV
contain badge name, pronouns, up to five structured languages, registration
country code, broad attendee labels, registration state, and photo review
status. Search, country, and attendee-level filters apply equally to the
preview and download.

The staff report's country is the restricted registration-profile address
country and is never used by the public directory. The CSV includes edition ID,
edition name, and generation time, neutralizes spreadsheet formula prefixes,
is audited, and excludes contact, legal name, full address, payment, and
internal comments. Synchronous source populations above 5,000 are rejected
until the asynchronous export pipeline exists. This is badge-data preparation,
not a badge-layout or printer workflow.

## API contracts

Configuration:

- `GET .../registration/configuration`
- `POST .../registration/configuration/drafts`
- `POST .../registration/configuration/activate`
- `POST .../registration/templates`

Attendee:

- `POST /api/v1/public/editions/{edition_id}/registration/submissions`
- `GET|POST .../registration/me`
- `POST .../registration/me/{registration_id}/payment-intents`
- `GET .../registration/me/{registration_id}/payment-intents/{intent_id}`
- `GET .../registration/me/{registration_id}/receipts`
- `POST .../registration/me/{registration_id}/demo-payment`
- `GET|PUT .../registration/me/profile`
- `POST .../registration/me/profile/photo`
- `POST .../registration/me/profile/fursuits/{fursuit_id}/photo`
- `GET|POST .../registrations/me/profile-extensions`

Staff:

- `GET .../registrations`
- `GET .../registrations/{registration_id}`
- `POST .../registrations/{registration_id}/check-in`
- `POST .../registrations/{registration_id}/payment-deadline`
- `POST .../registrations/{registration_id}/waive-payment`
- `GET|POST .../registrations/{registration_id}/profile-extensions`
- `GET|POST .../registrations/{registration_id}/financial-operations`
- `POST .../registration/financial-operations/{operation_id}/approve`
- `GET .../registration/reconciliation`
- `GET|POST .../registration/settlements`
- `GET .../registration/payment-exceptions`
- `POST .../registration/payment-exceptions/{exception_id}/resolve`
- `GET .../registration/profile-media-reviews`
- `POST .../registration/profile-media-reviews/{media_id}`
- `GET .../registration/attendee-report`
- `GET .../registration/badge-export.csv`
- `GET .../actions`

Public definition:

- `GET /api/v1/public/editions`
- `GET /api/v1/public/editions/{edition_id}/registration`
- `GET /api/v1/public/editions/{edition_id}/registration/profile-suggestion`
  (authenticated self projection)
- `GET /api/v1/public/editions/{edition_id}/attendees`
- `POST /api/v1/public/guardian-consents/accept`
- `POST /api/v1/public/organizations/{organization_id}/payments/{provider_code}/webhook`

The public definition includes profile, submission, policy-acceptance,
idempotency, and lifecycle semantics: pronoun codes, the
conditional-other code, ISO 639-1 language choices and maximum, bio and
fursuit limits, media review/reuse rules, and public-list prerequisites.
The self profile `PUT` is a complete metadata replacement command; media
uploads are separate multipart commands so clients do not need to encode files
inside nested JSON.

All edition paths contain both organization and edition identifiers. Queries
scope by both before resolving records. Missing and unauthorized targets use
non-disclosing responses.

## Authorization, audit, and effects

The module defines:

- `registration.manage_configuration`;
- `registration.view_service_summary`;
- `registration.check_in`;
- `registration.manage_exceptions`;
- `registration.view_payment_summary`;
- `registration.view_self_profile`;
- `registration.manage_self_profile`;
- `registration.moderate_public_profile`;
- `registration.view_attendee_reporting`;
- `registration.view_self`; and
- `registration.register_self`.

Self capabilities require the current account as resource owner and an edition
participation. Staff capabilities require explicit edition-scoped authority.
Profile-extension self writes require `registration.manage_self_profile`;
staff writes require `registration.register_on_behalf` and a reason.
Sensitive service-list and detail reads are audited.
Self-profile and suggestion reads use a relationship-derived restricted-data
projection and are audited. Media queue and preview reads are edition-scoped
and audited; approval/rejection additionally requires a recorded reason.

Anonymous public submission is a deliberately narrow application service. It
may create an account and pending edition participation only while the selected
configuration is active and open. It cannot grant staff authority, capacity, or
paid state. Product capacity and configuration are locked before submission.

Configuration creation, activation, template publication, submission, payment
reconciliation, and check-in publish registered domain events through the
transactional outbox. Privileged mutations record safe changed-field names and
reason/correlation evidence without copying form answers into audit metadata.

Registration timelines are operational projections, not security audit.
Attendees and authorized staff receive the rendition appropriate to their
purpose.

## Database integrity and recovery

PostgreSQL guards enforce organization/edition parent scope, immutable
published templates and active configuration children, registration state and
aggregate-version edges, and append-only submissions, payment attempts,
entitlements, check-in records, and timeline entries. The same database layer
freezes active/published sections and rejects mismatched, rescaled, or
ordinarily deleted attendee profiles. Profile changes have their own aggregate
version guard. Fursuit rows redundantly carry registration, organization,
edition, account, and profile scope; a database trigger rejects mismatch,
scope mutation, archived/cancelled changes, and ordinary deletion.

Registration `0031` adds the IDN-011 database invariant to `Registration`,
`AttendeeRegistrationProfile`, and `AttendeeFursuit`. Before each insert or
update, the module locks and checks only the subject `account_id`; staff-assisted
submitters and media reviewers remain actor provenance. A deferred identity
trigger prevents later reclassification of any account that retains these
records. The transactional migration installs the guards before its final
count-only existing-data preflight, closing the deployment race as well as ORM
bulk and direct-SQL bypasses. See
[`idn011-convention-subject-migration-and-recovery.md`](../operations/idn011-convention-subject-migration-and-recovery.md).

The aggregate guard additionally constrains waitlist offer,
payment-deadline, confirmation, expiry, cancellation, and check-in
transitions. Registration adjustments are scope-checked and append-only at the
database layer.

Payment attempts, webhook receipts, ledger entries, settlement allocations,
receipts, safety receipts, and submissions are append-only. Entitlements may
only make the reasoned `active -> revoked` transition while scope and grant
evidence remain immutable. Cancellation/refund tests exercise that transition;
ordinary update and delete are rejected by PostgreSQL.

Migrations add only new module tables and guards. Rolling application code back
does not remove registration data. A schema rollback would require an explicit
export and recovery decision because financial and attendee history must not be
silently dropped.

## Verification

Integration coverage includes:

- template and prior-edition copy-on-write;
- cross-tenant and cross-series denial;
- explicit review and immutable activation;
- template publication and versioning;
- all supported question types and conditional validation;
- exact schema/answer snapshots;
- readable admin dossiers that keep attendee answers separate from
  organizer-managed roles, comments, status, entitlements, finance, and
  attachments;
- capacity rejection;
- API submission and idempotent demo reconciliation;
- purpose-limited Front Desk reads and read audit;
- reasoned check-in and attendee/staff timelines;
- action projection; and
- database immutability triggers;
- anonymous and returning-attendee registration;
- existing-email, minimum-age, upload, and account-creation failure behavior;
- profile and photo tenant/edition isolation;
- explicit prior-profile suggestion and cross-edition snapshot isolation;
- current-profile edit without registration-submission mutation;
- attendee/shared/staff-only profile-extension reads and writes without
  registration-submission mutation;
- append-only extension value revisions, reviewed versioned definitions,
  tenant isolation, reserved authoritative keys, and database guards;
- controlled pronoun write-in and five-language maximum;
- multiple fursuits and database scope/retention guards;
- public attendee field minimization and consent withdrawal;
- media pending/approve/public/reuse transitions and cross-account denial;
- self-profile metadata and multipart upload APIs;
- moderator queue authority and audit;
- capacity- and entitlement-derived profile facts; and
- section copying and immutability;
- phased product windows and volunteer-capacity eligibility;
- payment deadlines and late-payment rejection;
- FIFO waiting, automatic promotion, and close behavior;
- inactive-account open-record cancellation;
- reasoned deadline changes and payment waivers;
- public registration-definition APIs;
- financial reconciliation authorization; and
- append-only adjustment database guards.
- complete JSON headless bootstrap/sign-in handoff, CSRF, version and policy
  acceptance, idempotency replay/conflict, and submission parity;
- hosted intent creation, provider-host allowlist, signed webhook replay and
  mismatch handling, exception resolution, receipts, refund dual control,
  disputes, fees, settlement, and cross-tenant denial;
- minor policy and guardian challenge gating;
- malware-scanner protocol, image safety/rendition evidence, reuse copying, and
  reference-aware disposal;
- credential issue/revoke, signed offline manifest, idempotent ingest, and
  conflict reporting;
- post-edition correction, subject export/minimization, and disposal evidence;
  and
- closure readiness counts, reviewed gates, immutable manifest, and stale
  manifest rejection.
- bulk/direct registration-subject rejection, complete-graph account
  reclassification refusal, populated-data preflight, and subject-write versus
  reclassification serialization.

The Convention work tests cover convention-defined conditional questions,
permission-denied states, reconciliation rendering, controlled exception
controls, and reasoned profile-image review. Desktop and 390-pixel mobile
browser walkthroughs cover the public chooser, account creation form,
submitted/editable profile, returning suggestion, public attendee list, and
embedded Convention work registration journey with no runtime console errors.

## Limits

The repository-controlled safety boundary is substantial but a deployment is
not automatically production-approved. A selected payment provider adapter
still needs credentials and sandbox/vendor certification; SMTP, ClamAV,
object-storage lifecycle, scheduler/workers, alerting, and a relay client must
be provisioned and rehearsed. Representative throughput/load proof is still
required even though PostgreSQL contention tests prove no two successful
transactions oversubscribe the tested boundary.

Transfer, product change, and price adjustment are intentionally unavailable.
Badge layout/printing and stock custody, friendly form studio, staff
registration on behalf, attendee-accepted transfer, broader catalog,
organization-independent platform privacy requests, a visual extension-field
builder beyond specialist records, and retention-policy
dual-control provisioning remain product work.

Every partner still needs privacy, finance, safeguarding, security,
jurisdiction, operational-owner, and go/no-go approval. See
[`registration-runbook.md`](../operations/registration-runbook.md) for the
operator and tester procedure and
[`REGISTRATION_TODO.md`](../project/REGISTRATION_TODO.md) for the exact
residual boundary.
