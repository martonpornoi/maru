# ADR 0047: Governed registration setup and platform account invitations

- Status: Accepted
- Date: 2026-08-02
- Extends: ADRs 0005, 0009, 0013, 0029, 0031, 0039, 0042, and 0045
- Supersedes: only ADR 0007's temporary allowance for Django admin to edit
  draft registration questions and products, after the staged writer-retirement
  gate in this decision is activated
- Requirements: IDN-001, IDN-002, IDN-004, IDN-006, IDN-007, IDN-009,
  IDN-011, IDN-013, EVT-002, EVT-003, REG-001, REG-002, REG-012 through
  REG-015, REG-021 through REG-024, UX-019, UX-020, UX-026, AUD-001 through
  AUD-003, AUD-005, PRI-001, PRI-004, PRI-009, INT-001, INT-002, NFR-001
  through NFR-004, NFR-008 through NFR-010

## Context

Maru already has a substantial registration domain: copy-on-write
configuration, immutable submissions, purpose-partitioned edition profiles,
profile extensions, staff-assisted registration, offers, payment evidence,
and public API contracts. Those capabilities do not yet form one coherent
organizer journey in the restored administration shell. Some draft
configuration, minor-policy, extension-field, provider-account, and identity
records can still be changed directly through Django model administration or
fixtures. Those paths cannot consistently enforce exact edition scope,
expected versions, idempotency, atomic audit and outbox evidence, or immutable
published meaning.

The first realistic convention journey also needs people to exist before they
choose to register. Public self-bootstrap remains essential, but a platform
operator may need to invite a synthetic demonstration user or a known future
user. That convenience must not give the platform administrator a convention
identity, must not preselect any participation, and must not revive the unsafe
practice of administrators assigning shared production passwords.

The existing tenant domain-event outbox is organization-scoped. An account
invitation is a platform identity action before any organizer relationship
exists. Assigning a fabricated organization merely to enqueue its email would
misstate ownership and could leak the action into a tenant event stream.

## Decision

### One Page 10 journey in the shared administration shell

The canonical organizer surface is an edition-scoped **Registration**
workspace under the selected organization, convention series, and event
edition in the original `/admin/` shell. A platform-scoped **Accounts**
inventory with an adjacent **Invite** action is available only to active
platform administrators. Invitation acceptance is a public account-security
flow beneath `/accounts/`.

There is no second registration administration shell, global Quick Start, or
parallel React-owned builder. Server-rendered HTML and versioned API adapters
are thin clients of the same queries and application commands. Existing
clients may remain compatibility adapters only until contract parity and
deprecation evidence permit their removal.

Route scope is an untrusted locator, never authority. Every query and command
resolves the complete persisted organization/series/edition chain and repeats
the current exact-scope authorization decision before releasing protected
names or committing a change. Active platform administration is evaluated as
explicit oversight and actor attribution, not as membership, participation,
registration, workforce assignment, or an authority grant in the convention.

### Optional platform account invitation

Account invitation is additive to public self-registration and is never a
prerequisite for it. An invitation command:

- accepts a normalized email plus optional normalized login handle, display
  name, and preferred language, together with a reason, retry key, and
  code-owned expiry policy;
- creates only an inactive `PERSON` platform account with an unusable password
  and a versioned invitation record;
- refuses to overwrite, merge, reactivate, or disclose an existing identity;
- creates no organization membership, Board appointment, capability grant,
  participation, registration, application, onboarding request, position,
  assignment, shift, entitlement, order, or public-directory entry; and
- creates a single-use challenge whose raw bearer secret is returned only to
  the delivery adapter and is never stored in plaintext, written to audit,
  placed in an event payload, or logged.

The recipient must prove control of the invited email and choose their own
policy-valid password. Acceptance activates the person account, verifies the
invited address, consumes the exact current challenge, revokes competing open
challenges for that invitation, records account security history, and creates
no convention relationship. Reissue and revocation are separate reasoned,
expected-version, idempotent commands. Reissue invalidates the prior challenge;
revocation leaves the reserved inactive identity for an explicit later
identity-lifecycle decision rather than deleting or silently reusing it.

Invitation creation, reissue, revocation, delivery-state changes, expiry, and
acceptance produce global administrative audit evidence. Where the subject
account exists, recipient-visible security history is also appended. Required
email is represented by a purpose-specific, platform-scoped durable identity
delivery record written in the same transaction as the invitation transition.
The same durable identity-delivery row contains an envelope-encrypted C4 token
payload and key identifier; the challenge retains only its one-way digest.
The request process may encrypt but cannot decrypt that payload. A dedicated
retry worker decrypts it only for delivery after commit and records attempt,
provider reference, next retry, terminal failure, and reconciliation state.
The ciphertext is destroyed after confirmed delivery, revocation,
supersession, or expiry and is never retained as long-term delivery evidence.
Key access, rotation, and loss recovery belong to the identity delivery
runbook and readiness check.

The tenant `DomainEvent` and `OutboxMessage` tables are not populated with a
fabricated organization for this platform-global action. Generalizing those
tables to platform scope would require a separate decision and migration. This
decision's identity delivery record is the durable effect boundary required by
ADR 0005, not a best-effort post-commit email call.

### Edition-owned copy-on-write configuration

Each edition has one registration setup workspace. Starting it requires one
explicit source choice:

- blank;
- an exact immutable published template version allowed for the organization
  or series; or
- an exact eligible configuration version from another edition in the same
  organization that the actor may read.

Import copies independent edition-owned definitions and records the immutable
source identifier, version, canonical digest, import time, actor, and review
state. It never shares mutable rows, crosses an organizer boundary, infers the
immediately previous edition, or activates the target.

The configuration's command aggregate version is separate from the versioned
form schema retained by registrations. Draft sections, questions, products,
ordering, and minor policy are changed through purpose-built commands. An
active configuration version is immutable; later change starts a successor
draft with explicit provenance and target review. Published template versions
are immutable. Configuration activation is a high-impact command that verifies
review-sensitive dates, prices, capacities, purposes, agreements, minor
policy, and current edition lifecycle before atomically selecting the one
active version.

Custom registration questions are additions to, not replacements for, the
typed edition-profile domains. A configuration with zero custom questions is
therefore valid when its other activation checks pass. The existing service
gate that requires at least one question must be retired; activation still
validates every question that does exist.

Post-submission profile extensions remain a separate edition-owned catalog
under ADR 0029. Definitions support C1/C2 information only, become immutable
when active, and use superseding versions for later change. Values are
append-only typed revisions. A self-service writer must own the exact
registration and may use only active attendee-visible attendee-writable
fields. Staff reads and writes require dedicated exact-edition capabilities;
`registration.register_on_behalf` is not treated as a generic profile-data
permission. Staff writes require a reason and the field's staff writer policy.
Authoritative entitlement, payment, restriction, role, capacity, and
participation facts, including special-ticket status, never become extension
answers.

Typed C3 registration-profile domains such as legal identity, address, date of
birth, guardian/consent, emergency contact, and safety-restricted information
remain governed by their purpose-specific models and policies. Page 10 does
not turn them into arbitrary form-builder or extension fields.

### Closed commands, concurrency, and evidence

Every Page 10 mutation has a closed input schema. Unknown fields and
client-supplied tenant, edition, actor, subject, lifecycle result, aggregate
version result, source digest, timestamp, audit, event, delivery, or security
evidence are rejected. Browser forms carry a server-created UUID retry key;
API clients use `Idempotency-Key` and may not repeat it in JSON. Reuse with the
same actor, exact scope, operation, and normalized input returns the first
outcome. Reuse with changed input conflicts.

Optional import values distinguish absence from falsy input. Where the source
contract permits inheritance, an omitted value may inherit; an explicitly
submitted `0`, empty string, empty list, or `false` remains present and is
validated according to that field. In particular, explicit capacity zero is
rejected and must never select the inherited capacity through truthiness.

Commands that can race lock their control row and require an expected positive
aggregate version, except a first creation command that explicitly expects
version zero. Append-only value writes additionally compare the current
subject-field revision. A successful tenant command changes its domain state,
appends value-minimized audit evidence, appends the minimized domain event,
and enqueues its outbox effect in one transaction. Invitation commands follow
the global audit and durable identity-delivery boundary above. A failed audit,
event, outbox, security-history, or required delivery-evidence write rolls back
the complete command.

Audit and event metadata may contain stable record identifiers, operation,
versions, lifecycle, field keys, counts, source channel, and outcome. They do
not contain email addresses, display names, login handles, question labels,
purpose or help text, profile values, answers, staff reasons, prices, raw
provider material, or invitation secrets. Sensitive reads are audited before
the protected response is released; failure of required audit evidence is a
name-free dependency failure.

### Authorization, disclosure, and privacy

Configuration viewing and mutation require the current exact-edition
registration capabilities selected by policy, with explicit platform
oversight evaluated separately. Profile-extension catalog management uses
`registration.manage_configuration`. Staff extension-value reads and writes
use dedicated `registration.view_profile_extensions` and
`registration.update_profile_extensions` capabilities at the exact edition;
introducing them requires an additive catalog migration and no implicit grant.
Attendee self-service follows exact account ownership and field policy, not a
staff capability.

Every header computes effective access from current platform authority,
capability lineage, resource scope, field ceiling, lifecycle, and exceptional
access. It never stores a page-local ACL. Named people appear only to a viewer
already permitted to see that relationship. A missing, dormant, malformed, or
stale authorization dependency fails closed without tenant names, people,
counts, configuration contents, or hidden-principal hints.

Account identifiers and administrative reasons are C2. The raw invitation
bearer secret is C4 and ephemeral; its one-way digest and abuse/security
evidence are C3. Registration definitions are C1 or C2 according to declared
purpose. Extension values inherit the field's C1/C2 classification. Audit,
logs, metrics, error text, and event payloads use only the minimized evidence
listed above. Retention and erasure follow the owning identity, registration,
finance, legal, and audit policies; deletion is never smuggled into a setup
edit.

### Staged retirement of direct writers

The new contract is activated through a staged, reversible deployment rather
than by pretending current direct writers are already safe:

1. Add aggregate versions, immutable provenance/digests, command receipts,
   invitation/delivery evidence, and required constraints. Backfill existing
   records with an explicit `legacy` origin and unknown provenance where facts
   cannot be proved; never fabricate actor or source history.
2. Route Page 10 HTML/API adapters, maintained fixtures, imports, and internal
   tools through the shared application services. Compare projections and
   prove idempotency, authorization, audit/outbox, retry, rollback, and
   performance behavior on representative data.
3. Make registration template/configuration inlines, minor-policy,
   profile-extension-field, payment-provider-account, and account-creation
   model-admin writers read-only or unregister them. Compatibility clients may
   call the same commands but may not retain an independent writer.
4. Activate database stopped-writer guards and a deployment readiness check
   that rejects an obsolete writer/schema generation. A downgrade that would
   re-enable a direct writer requires controlled migration-owner recovery,
   documented data consequences, and a new readiness generation.

Until a stage's readiness evidence passes, documentation and UI must identify
the affected writer as transitional. No stage claims provenance that predates
its controls, and no direct ORM fallback is allowed after the stopped-writer
generation is active.

### Synthetic educational journey

Tests, fixtures, screenshots, tutorials, and demonstrations use deterministic
fictional people and reserved `.invalid` email domains. They do not scrape,
copy, or infer accounts from a live public volunteer roster. A local
development-only fixture may use a documented shared convenience password for
synthetic accounts only if it refuses non-development settings and clearly
states that production invitations require recipient-owned passwords.

The educational smoke journey must prove that a non-participating platform
administrator can create the tenant spine, invite synthetic person accounts,
configure and activate registration, and observe evidence without becoming a
convention subject; an invited person can accept, sign in, register once, and
complete an allowed extension; an exact-edition staff actor can update only a
staff-writable extension with a reason; and foreign-tenant, stale, replayed,
unknown-field, retired-field, and authoritative-entitlement attempts fail
without partial state or disclosure.

## Consequences

- Organizers receive one coherent registration setup journey while public and
  replaceable convention frontends retain the same versioned domain contract.
- Platform operators can help create identities without assigning passwords or
  gaining convention participation.
- Historical form meaning, imported provenance, and post-submission changes
  remain explainable.
- New aggregate controls, receipts, delivery evidence, capabilities, database
  guards, migrations, and operational workers are required before the contract
  can be described as implemented.
- Django model administration becomes an inspection and recovery surface for
  the affected records, not a competing everyday writer.
- A general platform-scoped domain-event stream remains a future architecture
  decision; the invitation workflow cannot fake tenant ownership meanwhile.

## Alternatives considered

### Keep Django admin as the permanent form builder

Rejected. Model inlines cannot reliably express the shared strict command,
expected-version, idempotency, provenance, and atomic evidence contract.

### Make the existing React registration area a second administration product

Rejected. It would restore the competing shell and duplicate workflow that the
page-by-page rebuild is intended to remove. A frontend may consume the API but
does not own separate domain rules.

### Let a platform administrator choose or share production passwords

Rejected. It exposes reusable credentials, weakens address verification, and
confuses identity provisioning with convention authority. Only the recipient
chooses a production password.

### Attach platform invitations to a placeholder organization

Rejected. It fabricates tenant ownership, corrupts event-stream meaning, and
risks cross-tenant disclosure.

### Rewrite a submission or store current additions in one JSON object

Rejected. Both destroy schema/version meaning and bypass typed validation,
field policy, retention, and append-only amendment evidence.

### Treat special-ticket status as an organizer checkbox

Rejected. It is an authoritative product/entitlement fact and cannot be
self-asserted or duplicated as a profile extension.

### Import the current public volunteer roster for realism

Rejected. Public visibility is not consent for account creation, and ADR 0042
requires synthetic-only educational data.
