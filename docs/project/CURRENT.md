# Current project state

Last updated: 2026-07-29  
Phase: Registration production-safety complete; initial workforce onboarding slice implemented; partner deployment readiness next  
Implementation status: Guided organizer/locale setup, browser first-authority bootstrap, staff-assisted account creation/registration, reviewed volunteer onboarding, position-driven access, comprehensive admin data, and registration reporting delivered; provider, infrastructure, load, policy, and go/no-go gates remain

## Current outcome

Maru is an executable Django/PostgreSQL modular monolith with an API-first,
edition-owned registration journey:

```text
verified account
  -> versioned headless or bundled form
  -> volunteer / early-bird / normal offer
  -> guardian pending, free confirmation, paid reservation, or FIFO wait-list
  -> hosted provider intent and authenticated webhook
  -> operational ledger, receipt, entitlement, and notification
  -> credential and online/offline check-in
  -> finance/privacy/delivery/conflict reconciliation
  -> reviewed readiness gates and immutable closure manifest
  -> archived history
```

The built-in registration pages are a neutral accessible reference and
fallback, not the intended annual visual brand. A convention can replace them
with a colorful seasonal frontend using the same versioned APIs. Maru
revalidates identity, configuration version, policy acceptance, conditional
answers, eligibility, price, capacity, deadline, payment, and state
transitions; the frontend never becomes authoritative.

The local/test-only v5 demonstration fixture now gives every one of the 63 Maru
models registered in Django admin at least one safe synthetic example. Its
registration and account inspection pages expose readable person dossiers:
immutable submitted answers, profiles and fursuits, organizer roles and
capacities, account/restriction state, staff-only comments, Infinity
entitlement, amount received, finance/receipt evidence, guardian consent,
messages, credentials, check-in, privacy evidence, and attached-record links.
Older demo databases upgrade additively without rewriting historical
registration state. The seed command now defaults to the documented,
intentionally public local/test credential `Z7!maru-demo-fixture-2026`; an
explicit reset updates each unique stable-ID fixture account and cannot touch
non-fixture identities. The existing local fixture's 80 synthetic accounts
have been reset and the command remains unavailable under production settings.

The Staff Console now has an active Reports destination. An explicitly
authorized chair or registration lead can see the confirmed/checked-in
population, country and authoritative attendee-level breakdowns, filterable
badge-data preview, and an audited, formula-neutralized CSV. The preset is
edition scoped, excludes legal/contact/full-address/payment/internal-comment
data, and refuses synchronous populations above 5,000 pending the asynchronous
export pipeline.

Returning attendees receive a labelled compatible same-organization profile
suggestion. Submission creates a separate edition snapshot. Current-edition
changes do not mutate prior conventions or the immutable submission. Pronouns
use a maintained vocabulary with conditional Other, bio is limited to 500
characters, spoken languages use ISO 639-1 codes with a five-language limit,
and an attendee may opt into multiple fursuits.

Profile and fursuit images pass type, size, decode, malware, metadata, and
safe-rendition processing, then remain private pending scoped human moderation.
An exact approved file can be reused by its owner in the same organization
with copied safety evidence. The public attendee rendition is opt-in,
confirmed/checked-in only, instantly withdrawable, and excludes legal,
contact, emergency, answers, product, price, and payment data.
Consent version 3 may also publish a country entered specifically for the
directory and broad attendee/sponsor/super-sponsor/guest/volunteer labels
derived from entitlements and capacities. It never reuses address country, and
text accompanies every color cue.

Registration implements separate immutable volunteer, early-bird, normal,
free, and other offers; authoritative volunteer eligibility; overall/product
capacity; time-limited paid reservations; no-payment FIFO wait-list; fresh
promotion deadlines; expiry; reasoned deadline change; and payment waiver.
PostgreSQL locks and guards protect scope, capacity, state transitions,
snapshots, and append-only evidence.

Payment uses a locally recorded intent and provider-hosted checkout. Browser
return is never proof. HMAC/timestamp-verified provider events reconcile
account, reference, amount, currency, state, and idempotency; uncertain, late,
or mismatched evidence enters an owned exception queue. Payments, fees,
refunds, disputes, chargebacks, receipts, and settlements are append-only
operational finance. Cancellation/refund are dual-controlled. Transfer,
product change, and price adjustment are explicitly rejected until their full
acceptance and repricing workflows exist.

Every important registration/restriction event creates a canonical localized
inbox message before optional email. Delivery is idempotent, retryable, and
preference-aware; permanent failure is visible to staff and cannot change
registration truth.

Identity now includes verified email, non-enumerating recovery, abuse limits,
session inventory/revocation, privileged step-up, and user security history.
Organizer/edition restrictions are reasoned, expiring, appealable, and
separate from platform login state. Consequences preserve financial/history
evidence and cannot leak across organizers.

An edition may activate a versioned minor/guardian policy. Required consent
blocks payment and confirmation. Privacy operations provide scoped request
tracking, minimized export, reasoned post-edition correction, retention
minimization, and disposal receipt. Retention policy is read-only in bootstrap
administration until independently approved provisioning exists.

Confirmed admission can issue a revocable credential. Signed, time-bounded
offline manifests and idempotent device operations allow bounded degraded
arrival with a conflict queue. Archival requires five evidenced readiness
gates, zero unresolved operational queues, an immutable count digest, and a
current restore/recovery reference.

An empty organization can now establish its first separate bootstrap controller
and Convention Chair through a one-shot command, producing scoped authority and
ten common furry-convention position templates. The initial workforce module
owns edition departments, reporting lines, positions/headcount, publishable
opportunities, applications, versioned NDA-style document requests, reviewed
private PDFs, and position assignments. Assignment activation requires
approved documents and two authorized controllers, then creates the exact role
assignment and participation capacities atomically. Public opportunities and
self-service applications/documents have reference pages and versioned APIs.
Saving already approved onboarding evidence or an active position assignment
through bootstrap admin preserves the immutable record instead of surfacing a
database-trigger error.
The Accounts bootstrap page also explains that a selected convention workspace
shows only edition participants, so newly created platform accounts remain
visible under **All foundation data** until registration or workforce
bootstrap creates their participation.
New registration templates and edition configuration drafts created through
bootstrap admin now record the signed-in administrator automatically instead
of requiring an inaccessible read-only creator value.

Organization setup now distinguishes the independently governed tenant from
its recurring Convention Series brands. Organizations and series have useful
legal/public identity, contact, description, and website metadata. Organization
defaults support several searchable ISO languages with English pinned, ISO
country selection, and searchable IANA time zones labelled with current UTC
standard/daylight offsets. Edition locale entry uses the same bounded choices.
The synthetic fixture populates the added metadata.

The first controller and Chair can now be established through a superuser-only,
password-confirmed **First convention setup** admin wizard backed by the same
one-shot transaction as `bootstrap_convention`. Draft registration/template
sections, questions, and products can be removed before activation/publication;
active and historical records remain immutable.

Authorized registration staff can create a reasoned registration outside
public configuration/product sale times for an exact active account or, after
an explicit warning, atomically create a previously unseen unverified account
with a display name and temporary password. This bypasses timing only: all
ordinary restrictions, configuration, age, answer, eligibility, capacity,
price, duplicate, wait-list, deadline, and payment rules still apply. Staff
source/actor/reason and a separate privileged account-creation audit are
retained, and paid admission remains payment pending. Registration and
emergency telephone fields now show country initials, flag, and calling prefix
and store a validated E.164 value.

## Accepted decisions

- ADRs 0001 through 0006: modular Django/PostgreSQL platform, multi-tenant
  editions, scoped authority, bounded offline approach, transactional outbox,
  and React/TypeScript Staff Console.
- ADRs 0007 through 0012: copy-on-write registration configuration, edition
  context, public registration, headless/reference clients, phased
  reservations/wait-list, and reusable moderated attendee profiles.
- ADR 0013: verified identity lifecycle, sessions, step-up, exact-origin
  browser policy, and scoped appealable restrictions.
- ADR 0014: provider-hosted payment, authenticated reconciliation, append-only
  operational finance, dual control, and explicit unsupported changes.
- ADR 0015: canonical inbox plus optional idempotent email projection and
  failure queue.
- ADR 0016: minor consent, safe media pipeline, historical correction,
  retention minimization, and disposal evidence.
- ADR 0017: revocable credentials, signed bounded offline check-in, and
  evidence-gated edition closure.
- ADR 0018: separately consented public country, authoritative attendee labels,
  and minimized attendee-reporting/badge-export preset.
- ADR 0019: empty-organization authority bootstrap, staff-assisted
  registration, position opportunities, reviewed onboarding documents, and
  position-driven access.
- ADR 0020: guided browser bootstrap; organizer/series identity; stable,
  searchable language/country/IANA time-zone entry; draft-item removal;
  structured E.164 telephone input; and explicit audited staff account
  creation.

## Implemented production-safety boundary

### Public identity and API

- Account bootstrap, verification, recovery, session creation, session
  inventory/revocation, step-up, security history, restrictions, and appeals.
- Full JSON registration submission with CSRF, exact CORS allowlist,
  configuration version, policy acceptance, profile suggestion, conditional
  fields, idempotency receipt, self-profile, and multipart image upload.
- OpenAPI 3.1 plus generated Staff Console types.

### Registration operations

- Immutable configuration/templates, phased offers, profile policy,
  eligibility explanations, capacity, reservation, wait-list, lifecycle,
  adjustments, entitlements, media moderation, enriched public directory,
  attendee reporting, badge-data CSV, and metrics.
- Generic hosted-payment adapter contract, intent/status/webhook, exception
  queue, operational ledger, receipts, refunds, disputes, fees, settlement,
  and reconciliation.
- Canonical service notifications, SMTP projection, retry/failure evidence,
  and attendee preferences.
- Minor policy and guardian acceptance.
- Credentials, revocation, signed offline manifests, ingest/conflicts.
- Subject requests/export, correction decisions, minimization/disposal.
- Closure readiness, reviewed gates, manifest, and archive recheck.

### Workforce onboarding

- Password-confirmed browser or command-line one-shot first-controller/Chair
  bootstrap and ten common position templates.
- Edition departments, position reporting hierarchy, headcount, and automatic
  publishable opportunities that may remain visible when filled.
- Volunteer applications and private, versioned, scanner-gated PDF agreement
  requests with reasoned review.
- Dual-controlled assignment activation into immutable role versions and
  authoritative staff/volunteer/position capacities.
- Public and self-service web/API contracts plus populated bootstrap admin.

### Integrity and operations

- Deny-by-default organization/edition authorization and sensitive-read audit.
- PostgreSQL constraints/triggers for scope, immutable snapshots, state edges,
  append-only finance/audit/timeline/credential evidence, and constrained
  entitlement revocation.
- Transactional outbox, idempotent handlers, supervised workers, quarantine,
  replay, and safe metrics.
- Production settings fail closed for secrets, hosts, origins, SMTP, scanner,
  offline signing, verification, privileged step-up, and closure gates.
- Local PostgreSQL fresh-target restore and count reconciliation rehearsal.

## Verification

- 390 backend tests pass against PostgreSQL 17.
- Branch-aware coverage is 90.08%, above the 90% gate; declarative migration
  files are omitted from coverage measurement.
- Ruff formatting and lint pass.
- Strict mypy passes 172 source files.
- Django system check and `check --deploy` pass with production-shaped
  settings.
- Migration drift reports no changes. Fresh migrations apply through
  accreditation 0003, communications 0002, privacyops 0005, registration 0027,
  organizations 0002, and workforce 0002.
- OpenAPI 3.1 generation/validation passes without warnings; Staff Console
  types regenerate successfully.
- Thirteen Staff Console tests, TypeScript typecheck, and Vite production build
  pass.
- Python and production frontend dependency audits report no known
  vulnerabilities; the local Maru package is correctly skipped as non-PyPI.
- PostgreSQL restore rehearsal succeeds into
  `maru_restore_drill_production`, verifies 75 migrations, 82 accounts,
  2 organizations, 6 editions, 33 audit events, and 13 outbox messages, then
  removes the drill database.
- The v5 seed is idempotent on a fresh database and upgrades the existing local
  fixture; all 63 registered Maru admin models are non-empty. Browser QA
  verifies the admin index labels plus registration, submission-answer,
  payment, attached-record, and account-history dossiers. The public attendee
  page renders guest, attendee/volunteer, and super-sponsor examples with
  separate country values, readable labels, and no horizontal overflow. Its
  static local credential and unique-account reset behavior are integration
  tested; the existing 80 fixture accounts were reset successfully.
- A separate empty PostgreSQL database applied the entire schema and one-shot
  workforce bootstrap without demo seeding. It created 11 role bundles, 10
  position templates, one department/Chair position, four scoped role
  assignments, and one active position assignment; the disposable rehearsal
  database was removed afterward.
- The active local `maru_walkthrough` database applied organizations 0002
  successfully; `marucon` retained `en` and `Europe/Vienna` as its default
  locale values.
- Documentation validation passes 96 Markdown files and 180 unique requirement
  identifiers.

## Known limits and production gates

- No concrete payment vendor has been selected or certified. The generic
  hosted adapter is implemented, but production endpoint, credentials,
  webhook secret, sandbox matrix, and vendor/finance/security approval are
  external deployment gates.
- SMTP, ClamAV, object storage/lifecycle, scheduler, worker supervision,
  monitoring/alerts, relay devices/client, scanners, printers, and secret
  rotation must be installed and rehearsed in the target environment.
- Correctness tests include real PostgreSQL contention, but a
  production-shaped throughput/load report against the first edition forecast
  remains required.
- Transfer, product change, and price adjustment are intentionally unavailable.
  Badge layout/printing, stock custody, form studio,
  XLSX/asynchronous large exports, downloadable document rendering, broader
  catalog, and platform-global privacy/identity workflows remain product work.
- Workforce qualifications, availability, shifts, work records, assignment
  ending/replacement, approval notifications, and purpose-built hierarchy UX
  remain. The current assignment admin verifies a distinct authorized
  approver identity but is not yet a separately authenticated approval inbox.
- Staff-created accounts currently use an explicitly supplied temporary
  password. A production-grade expiring invitation/password-setup delivery
  flow remains before organizers should use this fallback with real people.
- Retention execution exists, but active jurisdiction policy provisioning needs
  an independently approved, dual-controlled path. Bootstrap admin cannot edit
  policy.
- Purpose-built assignment/search UX for every exception queue remains P1; APIs,
  action projections, and read-only admin provide the current functional
  boundary.
- Partner privacy, finance, safeguarding, security, jurisdiction, operational,
  and event-leadership approval is mandatory before production personal data.

The exact residual list and exit evidence are in
[`REGISTRATION_TODO.md`](REGISTRATION_TODO.md). Repository-controlled blockers
are implemented; Maru must not be described as production-approved until those
deployment and governance gates pass.

## Smallest sensible next actions

1. Select the first partner, jurisdiction, hosted payment provider, SMTP,
   storage/scanner topology, forecast, and named queue owners.
2. Certify the concrete provider adapter and provision production secrets.
3. Install workers, scheduler, telemetry, alerts, backups, storage lifecycle,
   relay devices/client, and documented fallbacks in rehearsal.
4. Run production-shaped load, provider failure, mail failure, media,
   offline-arrival, secret rotation, restore, and closure drills.
5. Provision independently approved retention/minor/refund/restriction policies
   and record all five readiness gates.
6. Certify the first seasonal frontend against OpenAPI, headless conformance,
   accessibility, origin/CSRF, abuse, and browser requirements.
7. Rehearse the clean convention/workforce walkthrough with the first partner,
   including browser bootstrap and missing-account staff intake; then build a
   separately authenticated approval inbox, expiring account-invitation flow,
   and the highest-value purpose-built workforce queues.
8. Add asynchronous expiring exports and physical badge layout/printing only
   when the first partner's volume and fulfilment process require them.

## Resume instructions

Read `AGENTS.md`, this file, `ROADMAP.md`, `REGISTRATION_TODO.md`, requirements
REG-001 through REG-021, HR-007/008, QRY-001 through QRY-008, IDN-007/008,
MSG-007, PRI-009, ADRs 0013 through 0020, the
registration/workforce/identity/communications/accreditation/privacy module
docs, and both registration and clean-onboarding runbooks.

Do not enable provisional registration, identity test tokens, credential test
tokens, demo payments, missing step-up, or closure bypass in production. Do not
trust browser payment return, mutate active configuration, charge a wait-listed
person, auto-roll a person to a higher price, publish unapproved media, expose
restriction detail across organizers, or use raw database edits to repair
state.
