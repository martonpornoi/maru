# Data classification and retention

Status: Baseline requiring jurisdiction-specific review  
Last updated: 2026-09-01

This is a product and engineering control model, not legal advice. Each
deploying organization must document its roles, purposes, lawful bases,
jurisdictions, statutory obligations, processors, and retention periods with
qualified counsel or a data protection professional.

The design follows the GDPR principles of purpose limitation, data
minimization, accuracy, storage limitation, integrity, confidentiality, and
accountability, and treats protection by design and default as a system
property. Primary references include the
[GDPR text](https://eur-lex.europa.eu/eli/reg/2016/679/oj) and
[EDPB Guidelines 4/2019](https://www.edpb.europa.eu/documents/guideline/guidelines-42019-on-article-25-data-protection-by-design-and-by-default_en).

## Classification

Classification measures the harm of inappropriate access or alteration. It is
independent of whether a record is archived.

| Class | Meaning | Examples | Baseline controls |
| --- | --- | --- | --- |
| C0 Public | Approved for unrestricted publication | released schedule, public host biography, venue guide | publication workflow, integrity, correction history |
| C1 Internal | Operational, low personal sensitivity | generic runbook, room setup, inventory count, department task | authenticated scoped access, normal audit |
| C2 Personal | Identifies or relates to a person | contact details, registration, application, shift history, order | purpose-specific access, encryption, subject rights, export control |
| C3 Restricted | Disclosure may cause serious personal, safety, legal, or financial harm | legal/pseudonym link, accommodation narrative, conduct or medical case, identity evidence, bank/tax data, minor details, hotel room assignment | separated stores/projections, explicit assignment, sensitive-read audit, step-up where needed, narrow export |
| C4 Security critical | Enables control or compromise | password verifier, recovery secret, signing key, payment webhook secret, API credential, offline device key | secret manager or dedicated credential store, never ordinary UI/export/log, rotation and compromise procedure |

Files inherit the highest class of any content they may contain until reviewed.
Free text is not assumed harmless. A C0 publication derived from C3 data is a
new approved rendition, not a reclassification of the source.

## Data inventory schema

Every persistent field or typed attachment must register:

- domain and record type;
- data subject or business owner;
- source and collection method;
- stated purpose and compatibility rules;
- controller and authorized recipient categories;
- classification;
- lawful-basis and consent behavior where applicable;
- active-use trigger and retention trigger;
- review owner, minimum hold, maximum target, and deletion method;
- archive representation;
- subject export, correction, restriction, and deletion behavior;
- search, analytics, log, cache, backup, and external-processor propagation; and
- whether the field may appear in test data, support tools, or telemetry.

Schema review fails if this metadata is absent.

## Purpose partitions

Data supplied for one purpose is not a platform-wide profile:

| Partition | Typical owner | Compatibility rule |
| --- | --- | --- |
| Platform identity | platform operator | authenticate and let user manage account |
| Organizer relationship | organization | continuity and eligibility within that organizer |
| Edition participation | organization/edition | deliver the selected edition |
| Registration and order | registration/finance | admission, service, settlement, support |
| Workforce and HR | HR and accountable leads | staffing relationship; ordinary leads get consequences only |
| Programme calls and proposals | Applications owner for one edition | keep call schema, shared answers, invitations, contributor-owned proposed-public profiles, exact seals, included-collaborator responses, and later review as separate purpose-bounded records; no value crosses into Programme without an accepted adapter |
| Programme private operations | Programme Department for one edition | separate working, delivery, discussion, readiness, and approved-public-copy layers; release only the purpose-bounded projection |
| Accessibility | access team | coordinate requested accommodation with minimum disclosure |
| Safety case | assigned qualified team | case purpose only; no engagement analytics |
| Public content | subject plus publisher | only exact approved rendition and term |
| Logistics custody and restricted contact | Logistics owner for one organization/edition | release only the minimum place/contact/custodian fact needed for an authorized movement, return, discrepancy, or provider obligation |
| Optional analytics | documented analytics owner | aggregate or de-identify wherever possible |

Cross-partition reuse requires documented compatibility, notice, and policy.
Convenience alone is not sufficient.

### Applications-owned Programme proposal layers

- A dormant call's operational code, lifecycle, track/format definitions, and
  contributor-field policy are C1 until a later deliberate publication
  workflow creates a C0 rendition. Domain activation is not publication.
- Proposal answers retain each question's classification and may be C1 through
  C3. Shared editing does not lower that ceiling: only the lead and accepted
  collaborators with the exact current relationship may receive applicant-
  writable answers. Conditional absence is snapshot evidence, not permission
  to reveal the hidden question or a prior value.
- Invitations, collaborator identity, roster membership, transition reasons,
  and acknowledgement state are C2. Invitation delivery secrets or bearer
  material must never enter the proposal, event, audit, log, or command receipt.
- Proposed-public display name, biography, pronouns, website, and consent are
  contributor-owned C2 input. Calling them proposed-public does not make them
  C0. Only the exact contributor may revise their values. Each included
  collaborator may acknowledge or decline only the exact seal and own profile
  revision included for them; the lead's attributable seal is the lead action.
  A later Programme public-copy review is required before any public projection.
- A sealed revision is immutable mixed-classification evidence. Its identifiers,
  exact answer/profile/selection links, policies, roster, digest, predecessor,
  and per-person responses reveal no values by themselves, but their disclosure
  remains at least C2 and never authorizes dereferencing a higher-class source.
- Events, outbox payloads, receipts, audit metadata, errors, metrics, and health
  checks contain only closed action, lifecycle, version, count, and opaque
  identifier facts. They never copy answer, biography, consent, invitation,
  reason, reviewer, or roster values.
- Issue #63 mounts no read or write surface and approves no active-use retention
  schedule. Until a deploying organization accepts purpose, lawful basis,
  subject access, correction, withdrawal, legal hold, disposal, backup aging,
  and recovery behavior, the kernel remains dormant and its evidence is not
  production personal data.

### Programme private information layers

- The canonical Programme item identity and closed operational codes are C1.
  Private working title/summary and ordinary readiness state are C1 unless
  their entered content raises the classification.
- Technical requirements, accessibility-delivery instructions, media-consent
  notes, Department discussion, readiness rationale, source identifiers, and
  reviewer evidence are C3 by default. The Programme delivery table must not
  store a diagnosis, medical narrative, or unrelated case detail.
- The bounded public fields in an approved rendition, and the projection made
  only from those fields, are C0. The stored rendition row is mixed-sensitivity
  because its source link, predecessor, reviewer, review time, and rationale
  remain C3 evidence. Approval never reclassifies or exposes the private source
  revision, rationale, actor, prior rendition, or readiness history.
  C0 classification does not imply publication or discoverability: the current
  query remains dormant and capability-gated, and returns the same absent shape
  for an unpublished private item, an absent item, and a foreign-scope item.
- Layer-specific capabilities, exact edition scope, final reauthorization, and
  sensitive-read audit protect private projections. A generic item projection,
  event, audit record, log, exception, or future public endpoint must not join
  these layers together.
- Command receipts, readiness/review evidence, and discussion are retained
  operational evidence. Production activation requires locally approved
  active-use and retention triggers, subject/export handling, legal-hold rules,
  backup aging, and an audited disposition path. Until then they remain
  retained and the module remains dormant.
- Tests and documentation use synthetic organizations, editions, actors, and
  items only. Recovery restores Programme, Audit, Effects, and migration
  evidence from one consistent point and never fabricates a proposal, host,
  readiness fact, rendition, occurrence, Shift, or release.

### Logistics custody and restricted contact

- Reusable external-party identity contains only legal/public operational
  identity, role, provider reference, and an optional public URL. Private email,
  telephone, address, recipient, and access instructions belong only in a C2 or
  C3 `RestrictedAddress` with a closed purpose, retention trigger, owner, and
  exact organization/edition scope.
- Ordinary workspace, offer, manifest, activity, current-state, and Stage Tech
  projections never include restricted address/contact values. An authorized
  contact read requires the dedicated capability, a closed reason code, final
  scope reauthorization, an opaque short-lived request token, a sensitive-read
  audit, and private/no-store/no-referrer/noindex response handling.
- A bounded idempotent disposal worker redacts expired address/contact values
  and records only minimized execution evidence. It must honor active offer,
  agreement, return, incident, and legal-hold horizons; it must not erase the
  append-only movement/custody facts required to explain asset state.
- People are custodians, offerers, borrowers, providers, or keyholders, never
  containment nodes. Maru records declared handovers and responsibilities, not
  continuous person or vehicle location. Physical-key responsibility never
  grants software authority.
- Asset, stock, manifest, discrepancy, agreement, and custody evidence is
  business/operational history. Its person references require a separately
  approved retention schedule and should be minimized or de-identified after
  return, discrepancy, contractual, support, and legal periods close. QR labels
  carry only a digest reference, not contact or address data.

### Platform account invitations

- The recipient email and reserved account label are C2 platform-identity data.
  They exist only to establish the recipient-owned login and never imply an
  organization, edition, membership, registration, or workforce relationship.
- The raw invitation token and its encrypted delivery envelope are C4 bearer
  material. The web process stores only envelope ciphertext; only the delivery
  worker has private keys. Ciphertext is destroyed on confirmed delivery,
  reissue, acceptance, revocation, or expiry, whichever occurs first.
- The versioned HMAC digest, digest-key identifier, abuse bucket, and delivery
  security evidence are C3. They are not account-search or analytics fields and
  never appear in ordinary operator projections.
- Delivery status, minimized provider reference, command receipt, lifecycle
  transition, and reason are C2 restricted administrative evidence. Reasons
  must describe the operation and must not contain unrelated personal facts.
- A revoked or expired reserved identity is reviewed after its support and
  security window. A controlled job must remove or anonymize email, login
  handle, display label, challenge snapshots, and provider references while
  preserving only the minimum non-identifying integrity receipt justified by
  the approved policy. Accepted accounts follow the ordinary identity policy.
- Local controller/legal review must set the maximum terminal-evidence window,
  security-event hold, backup aging behavior, export/correction behavior, and
  legal-hold procedure before production. Until that policy and its audited job
  are configured and rehearsed, invitation production readiness stays blocked.

Identity migrations `0017_invitation_retention_workflow` and corrective
candidate `0018_invitation_retention_v8` implement this narrow disposition,
but do not choose the legal period. Production must supply one
closed, approved `MARU_IDENTITY_INVITATION_RETENTION_POLICY_JSON` document and
the migration owner must activate its exact digest in the database control
row. The bounded job considers only revoked or expired, inactive person
accounts whose exact sole provisioning invitation is proved. Any active hold,
accepted/current/sibling invitation, usable challenge, unresolved delivery,
group/permission, privacy request, organizer/edition/registration/workforce
relationship, non-invitation security event, or present or future foreign-key
relationship blocks disposition. The database repeats the relationship test
from its live foreign-key catalog so a newly added domain fails closed until
reviewed.

Successful disposition replaces account and challenge contact with a random
non-routable tombstone, replaces challenge lookup digests, and blanks the
terminal challenge's digest-key identifier only inside the receipt-bound
transaction. It also replaces every non-empty provider reference on the parent
delivery, attempt, and late-outcome graph with a one-way non-routable
tombstone. It preserves invitation transitions, command receipts, security
history, audit, a minimized policy receipt, and one current value-minimized
assessment. Permanent receipt-aware database guards protect every retained
tombstone, freeze the disposed assessment and complete parent delivery after
the exact one-time provider transition, and prevent later authority membership
or delivery evidence from being attached to the disposed identity.

Candidate selection uses a persisted fair cursor, bounded challenge/delivery
chunks, and a database advisory lock. Blocked and held rows record a safe
result code and do not starve later eligible rows; held rows are counted and
advance the cursor but are excluded from actionable readiness backlog. Policy
activation, holds, receipts, assessments, and scheduler/cursor evidence are
database-timed, accept no public backdating override, and reject future or
incoherent control timestamps. The policy document rejects duplicate JSON
members and the only accepted evidence sources are `operator` and `scheduler`.
The per-transaction random key is never persisted or returned. Removing its
Python reference is best effort; Maru does not claim guaranteed secure erasure
of interpreter or process memory. Backup aging and physical-media disposal
remain deployment responsibilities.

### Registration lifecycle and financial evidence

- Published offer names, public prices, purposes, and availability explanations
  may be C0 renditions; draft policy and internal capacity planning remain C1.
- A person's registration, waitlist membership or position, payment deadline,
  product snapshot, operational timeline, and entitlement are C2.
- Provider identifiers and payment evidence are purpose-limited C2 unless a
  local policy classifies a particular financial identifier as C3. Payment-card
  data never enters Maru.
- Provider webhook secrets and credentials are C4 and never appear in an
  ordinary registration or finance projection.
- Adjustment reasons are visible only to the intended attendee, service, and
  audit audiences. Operators state the operational fact without adding
  unrelated medical, conduct, or financial narrative.
- Waitlist and reservation records remain edition-owned even after expiry.
  Their attendee-facing history and required financial evidence follow separate
  retention policies; neither justifies retaining all submitted form answers.
- Rehearsal uses synthetic accounts and provider sandbox data. A waiver is
  recorded separately and never creates false provider-payment evidence.

### Attendee profile suggestions and public media

- Every attendee profile is C2 and owned by one organization and edition. A
  prior same-organization profile may be read as a labeled suggestion for its
  subject, but the new edition receives an independent snapshot only after
  explicit submission.
- Earlier profile values are historical evidence and are not rewritten when a
  later address, pronoun, language, bio, or fursuit changes. Post-edition
  correction requires a separate reasoned workflow.
- Public-list consent is edition-specific, off in suggestions, and can be
  withdrawn while the profile is current. Public rows are hidden automatically
  when an edition is archived or cancelled.
- Source image files and pending/rejected review state are C2. Only an exact
  approved rendition becomes C0, and only through the minimized public
  attendee projection.
- Exact approved-file reuse is limited to the same account and organization.
  Storage disposal must count every active reuse reference; changing one
  profile must not delete a file still referenced by another edition.
- Moderation approval addresses publication suitability, not malware. Before
  production, uploads require malware scanning, safe decode/re-encode,
  controlled renditions, metadata stripping, incident removal, and storage
  retention evidence.

## Retention policy model

A policy is versioned and scoped by:

- organization and jurisdiction;
- domain record and relevant field/attachment category;
- purpose;
- trigger event;
- review interval;
- minimum hold if applicable;
- target deletion or transformation deadline;
- legal-hold behavior;
- final disposition;
- accountable approver; and
- evidence of execution.

Durations are configuration backed by reviewed policy, not constants buried in
application code.

### Lifecycle

```text
active -> purpose ended -> retention review -> due
             |                 |              |
             |                 +--> legal hold+
             +--> minimized -----------------> disposed
```

Dispositions:

- hard delete;
- cryptographic erasure where supported;
- detach or pseudonymize the person link;
- aggregate below re-identification threshold;
- preserve a minimized statutory record; or
- preserve an optional participant-facing contribution snapshot.

Deletion produces a non-sensitive execution receipt and aggregate count, not a
copy of what was deleted.

## Category baseline

Exact durations require local review, but the trigger and intended outcome are
part of product design.

| Category | Typical trigger | Intended outcome |
| --- | --- | --- |
| Abandoned form draft | inactivity | delete promptly |
| Unsuccessful application | decision and appeal closure | remove answers and reviews when no longer justified; retain minimal decision only if required |
| Unsubmitted Programme proposal or expired invitation | call closure, withdrawal, or documented inactivity | remove proposed-public values, answers, and invitation contact when no longer justified; retain only minimized integrity evidence under an approved Applications policy |
| Submitted Programme proposal | decision, appeal, accepted transition, and support closure | retain the exact sealed revision and responses only for the approved review/transition purpose; dispose unneeded private values by field policy without fabricating or rewriting the historical seal |
| Successful staffing record | offboarding or edition close | retain useful contribution separately; remove sensitive evidence and expired provisioning data |
| Registration service data | edition and support close | retain minimized participation; handle financial evidence under its own rule |
| Attendee profile/contact snapshot | edition and support close | retain or dispose by field purpose; preserve only minimized justified participation |
| Pending or rejected attendee media | review resolution or abandonment | dispose promptly under reviewed media policy unless incident evidence requires a hold |
| Approved attendee media | publication withdrawal, supersession, or last reuse | remove public rendition promptly; dispose source only after all references and holds clear |
| Identity verification artifact | verification completion | retain verification result where justified; delete source image promptly |
| Pending account-invitation bearer envelope | delivery, reissue, acceptance, revocation, or expiry | destroy ciphertext and wrapped key immediately; retain no bearer-link copy in logs, audit, or telemetry |
| Revoked or expired reserved account invitation | terminal transition plus support/security review close | anonymize abandoned identity/contact and provider evidence through the audited policy job; retain only justified non-identifying integrity evidence |
| Accepted account invitation | acceptance | discard bearer material immediately; retain minimized invitation/security provenance under the approved identity/audit schedule |
| Payment/order evidence | settlement and statutory trigger | minimize and retain required accounting evidence; no card data |
| Accessibility request | accommodation completion and follow-up | retain only while coordination or defined follow-up needs it |
| Medical/conduct/safeguarding case | case closure and applicable limitation or policy | restricted retention with scheduled review or legal hold |
| Hotel room assignment | stay and reconciliation close | remove room-person linkage when no longer operationally required |
| Message or support case | resolution | category-specific review; do not retain all chat indefinitely by default |
| Published programme/content | supersession or withdrawal | retain public historical rendition and correction history where appropriate |
| Audit event | security/governance policy trigger | protect integrity, minimize payload, delete on reviewed schedule |
| Export artifact | generation or last authorized access | short expiry and object deletion; retain metadata receipt |
| Backup copy | backup creation | expire by backup lifecycle; deletion requests age out through documented rotation |
| Participation history | edition archive | retain minimized private history; public display only by explicit choice |
| Pending equipment offer | withdrawal, rejection, or acceptance plus support close | dispose pickup/contact details by their purpose trigger; retain only minimized decision, source, and accepted asset/agreement provenance while justified |
| Logistics restricted address/contact | declared expiry after the operational/contractual purpose ends | bounded audited redaction of recipient, email, phone, address, and access instructions unless an active obligation or legal hold applies |
| Asset/key custody and movement evidence | return, recovery, discrepancy, contract, and support closure | preserve append-only state provenance for the approved risk/legal period; then minimize person links without rewriting the physical event sequence |
| Offline logistics batch | expiry and reconciliation/exception closure | expire device/operation payloads on the bounded schedule; retain only the minimized receipt and unresolved discrepancy evidence required for review |

## Historical participation

Participation history should say:

- which edition;
- which capacity or approved role label;
- status or completion outcome;
- relevant non-sensitive recognition; and
- whether the user permits public display.

It should not retain by association:

- original application answers or reviews;
- legal name or identity-document image;
- medical or accommodation narrative;
- conduct or HR case detail;
- exact check-in movements;
- private shift notes;
- hotel room number; or
- unnecessary transaction details.

Organizer operational history and user-facing history are separate projections
with separate policy.

## User controls

`My Maru` must let a person:

- see global versus organizer- and edition-specific information;
- view the purpose, source, visibility, and relevant retention explanation;
- correct editable information or request a controlled correction;
- manage public profile, media, optional analytics, and channel choices;
- request a portable export;
- request deletion, restriction, or objection and follow its state;
- withdraw consent without pretending all other justified processing stops;
- see important recipients or connected applications; and
- obtain a human contact for disputed decisions.

Privacy controls use plain language and never use a single blanket consent.

## Minors

Age handling is jurisdiction- and edition-specific. The system must support:

- configured age bands and age-at-relevant-date calculation;
- guardian relationship and authority evidence where required;
- age-result disclosure rather than full birth date when sufficient;
- guardian and minor communication rules;
- restricted room, content, credential, check-in, pickup, and volunteer policy;
- transition when a person reaches the configured age; and
- heightened visibility and retention controls.

Maru must not infer age from profile, appearance, behavior, or social accounts.

## Logs, analytics, and non-production data

### Public repository and security-audit evidence

- A deliberate public Git author name and email are C0 publication metadata,
  not Maru account or identity evidence. The owner accepts the already-public
  historical personal Gmail attribution without rewriting history. Future
  maintainer commits use a GitHub no-reply address by default unless an author
  knowingly selects another public address.
- Public source, documentation, examples, screenshots, fixtures, and test data
  stay synthetic and must not contain production personal data.
- A raw secret-scan match, report, reusable fingerprint, or matched context is
  C4, or the higher class of the material it exposes. Keep it access-restricted
  and ephemeral, never commit or log it, and destroy the local working copy when
  triage and any provider response are complete. A sanitized aggregate
  checkpoint without matched content is C0 governance evidence.
- Sanitized dependency-license, notice, and asset-provenance inventories are C0
  when they contain no sensitive path or match content. Retain them with the
  repository's governance and release evidence.
- History rewriting, ref deletion, and forced updates are destructive incident
  actions, not routine retention cleanup. Rotate or revoke a real credential
  first and require separate authorization, impact review, and public
  coordination before altering published history.

### Application logs and non-production environments

- Application logs use opaque identifiers and structured error codes.
- Request bodies, tokens, message content, form answers, query text, and file
  contents are excluded by default.
- Error capture redacts known classified fields before transmission.
- Product analytics is a separate, minimized, documented pipeline.
- Small cohorts are suppressed; cross-edition comparison avoids person-level
  tracking unless strictly required and authorized.
- Development, tests, demos, screenshots, training, and support reproduce
  structure with synthetic data, never a production database copy.
- Debug access expires and is audited.

## Backups and replicas

Retention cannot promise immediate erasure from immutable backup generations.
The policy must describe backup rotation, access isolation, restore procedure,
and how restored data is brought forward through completed deletion and
restriction ledgers before service resumes.

Search indexes, caches, analytical stores, offline devices, generated files,
email providers, and other processors receive erasure work and report
completion or exception.

## Governance artifacts

Before production, each organization needs:

- data inventory and record of processing activities;
- controller/processor and subprocessor map;
- data protection impact assessment screening and completed assessment where
  required;
- privacy notices and field-level collection text;
- data-subject request runbook;
- breach and security incident procedure;
- retention schedule with legal approval;
- restricted-case access and review procedure;
- international-transfer and residency assessment; and
- periodic access, policy, vendor, and deletion-job evidence.
