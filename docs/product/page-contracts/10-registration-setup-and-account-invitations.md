# Registration setup and account onboarding contract

- Status: Accepted target contract; canonical read/orientation slice mounted,
  complete implementation and writer cutover are not claimed by this document
- Canonical edition route:
  `/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/registration/`
- Related platform route: `/admin/platform/accounts/`
- Public acceptance route: `/accounts/invitations/accept/`
- Requirements: IDN-001, IDN-002, IDN-004, IDN-006, IDN-007, IDN-009,
  IDN-011, IDN-013, EVT-002, EVT-003, REG-001, REG-002, REG-012 through
  REG-015, REG-021 through REG-024, UX-019, UX-020, UX-026, UX-029,
  AUD-001 through AUD-003, AUD-005, PRI-001, PRI-004, PRI-009, INT-001,
  INT-002, NFR-001 through NFR-004, NFR-008 through NFR-010
- Decisions: ADRs 0005, 0007, 0009, 0010, 0013, 0016, 0019, 0026, 0029,
  0031, 0039, 0042, 0045, 0047, and 0055

## Purpose, outcome, and current truth

Registration setup and account onboarding makes the first end-to-end convention journey understandable without
creating a second administration product. It gives an authorized operator:

1. an optional platform-level way to invite a person account;
2. one edition-owned registration setup workspace;
3. an explicit blank, published-template, or exact prior-edition source;
4. a governed builder for draft sections, questions, products, minor policy,
   and ordering;
5. activation and successor-version controls that preserve historical meaning;
6. a catalog for safe C1/C2 post-submission profile extensions; and
7. truthful status, access, provenance, evidence, and downstream-effect views.

The platform administrator is a global operator and attributed actor. It is
never a convention subject. Inviting a person, configuring registration, or
inspecting delivery state creates no membership, Executive Board appointment,
capability grant, participation, registration, application, position,
assignment, shift, entitlement, order, or public-directory entry for that
administrator.

This contract does not assert that the current registration APIs, Django
model-admin pages, React registration destination, fixture writers, or identity
bootstrap already meet it. Those are inputs to the staged migration in ADR
0047. Registration setup and account onboarding becomes the canonical writer only after its readiness gate is
active. Legacy compatibility writers with an at-least-one-custom-question gate
or truthiness-based capacity inheritance do not meet this contract and must be
retired or reconciled before that gate can pass.

### Working-tree implementation checkpoint

The builder and definition-command core is independently accepted. Independent
review rejected the first configuration and profile-definition lifecycle cores
for incomplete authoritative evidence, source provenance, database
immutability, nested validation, review durability, and populated downgrade
behavior. A second configuration corrective candidate now adds the governed
reusable-template publication command and proves complete catalog and prior-
edition source graphs before listing, importing, or replaying them. Imported
eligibility is fixed at the successful import ceremony; later edition-date or
label changes do not rewrite that fact, and same-organization cross-series
policy copies use the source edition's actual series authority. Additive
registration migration `0037` guards complete template publication and active
configuration evidence. This candidate still awaits a separate independent
verdict. Invitation-retention v7 was likewise
rejected; its v8 corrective candidate now has permanent receipt-aware
tombstones, complete provider-reference disposal, fair bounded assessment,
strict database-time/source evidence, and populated-v7 recovery tests, but
still awaits an independent verdict. Canonical lifecycle adapters, successor and
retirement commands, profile-value commands, compatibility-writer
reconciliation, stopped-writer guards, and production cutover remain separate
work; this checkpoint does not mark Registration setup and account onboarding implemented or production ready.

Independently of that registration cutover, the first management-experience
slice implements the **User accounts** inventory, contextual invitation flow,
status-aware invitation next steps, and the handoff toward Representation & access. Focused HTML
integration tests cover that presentation. It changes no invitation command,
identity-retention, authorization, or convention-relationship behavior and is
not evidence that the broader Registration setup and account onboarding writer is ready.

The focused management recovery also separates the high-frequency
**Registration desk** from this canonical **Registration** setup record. The
desk places a searchable, filterable, paginated attendee queue before
configuration and links directly to Registration setup and account onboarding for setup work. Its purpose-limited
attendee detail is a labelled modal drawer with initial close focus, contained
keyboard navigation, Escape closure, background isolation/scroll lock, and
focus return to the exact attendee opener. The lower-frequency setup area has
one owner-safe handoff to **Workforce** instead of several specialist-record
links with different staff-only permission boundaries. Registration setup and account onboarding's active
version is readable in the fictional local fixture through one honest
`legacy_existing` setup control per configured edition with
`legacy_unknown` provenance. The fixture invents no actor, source digest,
command receipt, or completed writer cutover. Focused browser and integration
evidence for that handoff does not satisfy this contract's full state,
accessibility, concurrency, or recovery gates.

## Placement and navigation

The shared task-oriented navigation has two independently authorized durable
destinations:

- **User accounts** in Platform administration, visible only to active platform
  administrators; and
- **Registration** once beneath the selected exact edition, visible only after
  the complete route scope is safely resolved and the viewer may access the
  registration setup workspace.

Convention work separately exposes **Registration desk** for attendee service
and **Capacity & waitlist** for capacity policy. Those names are not aliases for
the Registration setup and account onboarding writer: the desk serves current registrations, while
**Registration** owns edition configuration and provenance.

**Invite account** is a contextual action owned by **User accounts**. It remains
discoverable through navigation search's search-only **Actions** group and is
not pinnable or rendered as an equal-weight permanent sidebar destination. The
inventory presents **Invite a user account** as its primary action. Search
matches stable generic terms including `users`, `people`, `staff`, and
`volunteers`; it never indexes protected account or tenant values. Authorized
technical identity records remain in the collapsed, searchable **Specialist
records** gateway.

Each child page has exactly one current navigation action. It uses the same
Maru logo, side-menu position, record header, modules, forms, buttons, status
language, spacing, focus treatment, and responsive stacking as earlier restored
pages. Registration setup and account onboarding adds no Quick Start, workspace switcher, second global menu, or
embedded competing shell.

The registration header shows the organization, series, edition, edition
lifecycle, active registration version, setup state, and a computed
effective-access explanation. The **User accounts** header explicitly says
that account provisioning does not grant convention access. Its results appear
before the longer account-boundary explanation. Invitation detail presents a
status-aware next step: wait for recipient acceptance, reissue an expired
invitation, return to User accounts, or—only after acceptance—choose an
organization and continue to **Representation & access**. That continuity does
not create a membership, Board appointment, or authority and does not weaken
Representation & access's eligibility rules. A **Manage access** control is shown only when the
underlying exact-scope authority workflow exists and the viewer may use it; no
inert page-local ACL editor is rendered.

At 1,100 CSS pixels and below the shared navigation uses the accessible
closed-by-default overlay drawer and compact context selector defined by ADR
0055. Wider layouts retain the persistent sidebar. The account inventory,
invitation forms/detail, and eventual registration builder must reflow without
page-level horizontal scrolling.

## Canonical browser surfaces

The target HTML route families are:

```text
GET  /admin/platform/accounts/
GET  /admin/platform/accounts/invitations/new/
POST /admin/platform/accounts/invitations/
GET  /admin/platform/accounts/invitations/{invitation_id}/
POST /admin/platform/accounts/invitations/{invitation_id}/reissue/
POST /admin/platform/accounts/invitations/{invitation_id}/revoke/

GET  /accounts/invitations/accept/
POST /accounts/invitations/accept/

GET  .../registration/
GET  .../registration/configurations/new/
POST .../registration/configurations/
GET  .../registration/configurations/{configuration_id}/
POST .../registration/configurations/{configuration_id}/update/
POST .../registration/configurations/{configuration_id}/activate/
POST .../registration/configurations/{configuration_id}/retire/
POST .../registration/configurations/{configuration_id}/successors/

GET  .../registration/configurations/{configuration_id}/sections/new/
POST .../registration/configurations/{configuration_id}/sections/
POST .../registration/configurations/{configuration_id}/sections/{section_id}/update/
POST .../registration/configurations/{configuration_id}/sections/{section_id}/move/
POST .../registration/configurations/{configuration_id}/sections/{section_id}/remove/

GET  .../registration/configurations/{configuration_id}/questions/new/
POST .../registration/configurations/{configuration_id}/questions/
POST .../registration/configurations/{configuration_id}/questions/{question_id}/update/
POST .../registration/configurations/{configuration_id}/questions/{question_id}/move/
POST .../registration/configurations/{configuration_id}/questions/{question_id}/remove/

GET  .../registration/configurations/{configuration_id}/products/new/
POST .../registration/configurations/{configuration_id}/products/
POST .../registration/configurations/{configuration_id}/products/{product_id}/update/
POST .../registration/configurations/{configuration_id}/products/{product_id}/move/
POST .../registration/configurations/{configuration_id}/products/{product_id}/remove/

GET  .../registration/configurations/{configuration_id}/minor-policy/
POST .../registration/configurations/{configuration_id}/minor-policy/

GET  .../registration/profile-fields/
GET  .../registration/profile-fields/new/
POST .../registration/profile-fields/
GET  .../registration/profile-fields/{field_id}/
POST .../registration/profile-fields/{field_id}/update/
POST .../registration/profile-fields/{field_id}/approve/
POST .../registration/profile-fields/{field_id}/activate/
POST .../registration/profile-fields/{field_id}/retire/

GET  .../registration/attendees/{registration_reference}/profile/
POST .../registration/attendees/{registration_reference}/profile-values/
```

The ellipsis is the exact persisted organization/series/edition slug chain.
Identifiers in route construction are selected through bounded server results;
operators are not asked to paste UUIDs. Registration references are stable,
opaque human support references and never accepted without the trusted route
scope.

GET and POST responsibilities are separate. Every state change is POST-only,
CSRF protected, private `no-store`, and followed by POST/Redirect/GET on
success. Each form contains only the action it describes. Reissue, revoke,
activate, retire, and remove never share one ambiguous status field.

The public acceptance GET contains no account details and does not consume a
challenge. The raw invitation secret must not appear in a request path, query
string, `Referer`, analytics event, or access log. The email client supplies it
through a URL fragment that same-origin acceptance code posts once, with a
manual paste fallback for browsers without that enhancement. The clean GET
page remains usable without a token and explains how to paste the code. The
POST response never confirms whether another email or account exists.

## Versioned API surfaces

The API uses the same queries and commands. The canonical target families are:

```text
GET  /api/v1/platform/accounts
POST /api/v1/platform/account-invitations
GET  /api/v1/platform/account-invitations/{invitation_id}
POST /api/v1/platform/account-invitations/{invitation_id}/reissue
POST /api/v1/platform/account-invitations/{invitation_id}/revoke
POST /api/v1/public/account-invitations/accept

GET  /api/v1/organizations/{organization_id}/editions/{edition_id}/registration/setup
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/registration/setup
GET  /api/v1/organizations/{organization_id}/editions/{edition_id}/registration/configuration
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/registration/configuration/drafts
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/registration/configuration/{configuration_id}/commands
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/registration/configuration/activate

GET  /api/v1/organizations/{organization_id}/editions/{edition_id}/registration/profile-extension-fields
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/registration/profile-extension-fields
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/registration/profile-extension-fields/{field_id}/commands
GET  /api/v1/organizations/{organization_id}/editions/{edition_id}/registrations/{registration_id}/profile-extensions
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/registrations/{registration_id}/profile-extensions
```

Nested section, question, product, ordering, and minor-policy operations are
closed command variants within the configuration command resource. A command
discriminator selects one documented schema; fields belonging to another
variant are unknown and rejected. OpenAPI lists every variant, response,
permission, idempotency header, expected-version rule, error code, and maximum.

The existing configuration workspace/draft/activation and self/staff profile
extension endpoints remain compatibility aliases only until they reject
unknown input, use the new application services, return the versioned
projections, and pass the same authorization and evidence tests. Alias removal
requires a published deprecation window and consumer inventory; Registration setup and account onboarding does
not silently break a public frontend.

API mutation requests require a UUID `Idempotency-Key` header and reject a
retry key in JSON. HTML mutation forms carry a server-generated hidden UUID.
API failures use RFC 9457 problem details with stable machine codes and no
protected labels. A successful creation returns `201`; successful idempotent
replay returns the original canonical resource and replay indicator; stale or
changed-key reuse returns `409`; validation returns `400`; denied/unknown scope
uses the non-disclosing authorization boundary; dependency failure returns a
generic retryable `503`.

## Trusted scope and permission matrix

Organization, series, edition, account, invitation, configuration, section,
question, product, field, and registration locators are untrusted until loaded
through their complete parent chain. A selected-edition session improves
navigation only. It cannot replace route scope, grant access, or reparent a
record.

| Actor and current authority | Accounts and invite | Registration setup | Extension catalog | Extension values |
| --- | --- | --- | --- | --- |
| Anonymous or inactive account | Acceptance form only, with a valid challenge | None | None | None |
| Active person account | Own accepted identity and security history only | None unless separately authorized | None unless separately authorized | Own exact registration's attendee-visible, attendee-writable active fields |
| Exact-edition configuration manager | No platform inventory or invitation right | Read and mutate through `registration.manage_configuration` within field/lifecycle policy | Manage definitions through `registration.manage_configuration` | No staff value access merely because definitions can be managed |
| Exact-edition registration profile staff | No platform inventory or invitation right | No builder access merely from profile access | Read only if separately granted configuration authority | Read through `registration.view_profile_extensions`; write staff-permitted fields through `registration.update_profile_extensions` and a reason |
| Active platform administrator | Global minimized account inventory and invitation commands | Explicit attributed oversight at the exact resolved edition | Explicit attributed definition oversight | No profile-value access from platform status alone; a current person relationship and exact tenant capability are required |

The two profile-extension staff capabilities are additive Registration setup and account onboarding capabilities;
they must enter the versioned capability catalog with an exact-edition ceiling
and no inferred grant from `registration.register_on_behalf`. Existing grants
are not silently widened. Attendee self-service uses authenticated ownership
and the field definition, not one of those staff capabilities.

Authorization runs before each sensitive query, again against the locked
target inside each command, and freshly before a name-bearing response is
released. Pinned lineage, expiry, lifecycle, resource scope, and field ceiling
must still be current. Platform oversight is an explicit policy branch, not a
superuser shortcut that creates a convention relationship. Restricted safety,
HR, payment, legal, and case data retain their own policies.

## Page states and projections

### Platform Accounts

The inventory shows at most the minimized identity needed for provisioning:
display name, login handle, normalized email, person/platform-admin kind,
active/inactive state, verified/unverified state, joined date, and current open
invitation state. It does not embed memberships, registrations, applications,
payments, restrictions, staff files, or cross-tenant activity. Those belong to
their separately authorized records.

The account projection supports bounded exact/prefix search across normalized
email, login handle, and display name; stable state/kind filters; cursor
pagination; and deterministic ordering. A blank inventory says plainly that
no person accounts have been provisioned. A dependency error releases no
partial person list. Invitation detail shows only the reserved identity,
status, expiry, version, safe delivery state/code, attempt count, created and
last-transition times, attributed actor, and minimized audit timeline.

Invitation states are `pending`, `accepted`, `revoked`, and `expired`.
Delivery states are independent: `pending`, `processing`, `delivered`,
`retrying`, and `permanent_failed`. Delivery failure does not roll back an
already committed invitation, pretend the email arrived, or permit an
administrator to view the secret. A manager may reissue a pending, expired, or
delivery-failed invitation using the current expected version. Accepted and
revoked invitations cannot be reissued; a new reasoned invitation lifecycle is
required if policy later permits it.

### Registration workspace

The overview presents one of these truthful setup states:

- **Not configured:** no configuration exists; offer explicit source choices.
- **Draft in review:** show the selected draft, source/digest evidence,
  validation summary, unanswered review-sensitive items, and safe preview.
- **Active:** show the immutable active version, opening/closing window,
  capacity, currency, product/question counts, minor-policy readiness, and
  successor-draft action.
- **Closed by time:** keep configuration readable; explain that attendee entry
  is closed without changing the edition lifecycle.
- **Read-only by lifecycle:** Ready/Live/Closing changes require the accepted
  high-impact policy; Archived and Cancelled are immutable for ordinary
  Registration setup commands.
- **Unavailable:** safe dependency failure with no partial configuration,
  source, person, or access projection.
- **Too large:** explicit limit state and no incomplete editable builder.

The overview separates configuration status from public registration state.
An active form is not necessarily open now, a draft is not publicly available,
and an edition being Ready or Live does not by itself activate registration.
Payment-provider readiness may be summarized with safe status codes, but
Registration setup neither displays credentials nor treats browser return as
payment evidence.
Provider-account creation and secret mapping belong to the integration/finance
workflow governed by ADR 0014.

### Builder and preview

The builder is record oriented. Sections, questions, and products appear in
stable ordered modules with explicit **Add**, **Edit**, **Move**, and **Remove**
actions. A move selects a bounded preceding/succeeding record rather than
accepting an arbitrary large position. Removal is allowed only in a draft and
requires a reason; referenced conditional questions, submissions, orders,
offers, or other protected evidence cannot be deleted. The command either
performs the complete renumbering or changes nothing.

Preview uses the same schema projector and answer validation contract as the
public reference client, but is clearly marked as a preview and creates no
account, registration, submission, reservation, wait-list entry, payment,
entitlement, or consent. Staff-only questions are labeled and never rendered
as attendee inputs. Conditional logic is checked for missing sources, forward
references, cycles, incompatible values, and hidden-required dead ends before
activation.

Zero custom questions is a valid builder state. Typed edition-profile fields
for the core attendee record already have their own purpose-specific models,
validation, visibility, and retention; organizers do not need to duplicate
them as custom questions merely to activate registration. Every custom
question that does exist still participates in preview and activation
validation.

### Profile extensions

The extension catalog shows stable key, version, label, purpose,
classification, attendee visibility, writer policy, requiredness, source,
review state, lifecycle, and supersession. It never shows attendee values in
the catalog. Draft definitions may be edited; approved definitions may be
activated; active definitions are immutable; retirement stops ordinary new
writes but preserves history. A changed active definition starts a new version
with the same key and an explicit supersedes relation.

The attendee/staff value page projects only the fields visible to that actor
and the current revision per stable key. It never rewrites the original
submission. A staff page uses a searched exact registration and separately
audits the sensitive read before releasing values. Each write appends one
typed revision with actor, source channel, field version, sequence, server
time, and staff reason where required. Repeating the same idempotent request
returns the first revision; a stale expected sequence conflicts.

## Closed input contracts

### Account invitation

| Field | Type and bounds | Normalization and validation | Classification and retention |
| --- | --- | --- | --- |
| `email` | Required email, at most 254 characters | Trim, Unicode-safe domain handling, canonical case-insensitive uniqueness; never overwrite an existing account | C2 identity contact; retained under identity/invitation schedule |
| `login_handle` | Optional text, at most 120 characters | IDN-010 validation, trim ends, case-insensitive uniqueness, no `@`, control characters, or leading/trailing whitespace | C2 login alias; becomes account data on acceptance |
| `display_name` | Optional text, at most 120 characters | Trim/collapse ordinary whitespace; no control characters | C2 identity label; recipient may amend through account policy |
| `preferred_language` | Optional closed language code, at most 35 characters | Select from code-owned supported language catalog; omission uses the displayed code-owned default | C1 preference |
| `reason` | Required text, 1–240 characters | Trim ends and collapse ordinary whitespace | C2 administrative rationale; excluded from events/logs |
| `expected_version` | `0` for create; positive integer for later commands | Compared under invitation lock; server renders current value | C1 control evidence |
| `retry_key` | UUID in HTML; API header only | Scope/actor/operation/input bound | C1 immutable receipt |

Account kind, staff/superuser flags, active state, verification time, password,
challenge expiry, delivery status, actor, invitation status, timestamps,
security history, audit, and effect fields are server owned and rejected if
submitted. Invitation expiry is a code-owned bounded security policy displayed
before confirmation; an operator cannot lengthen it.

Acceptance accepts only the raw single-use code plus `new_password1` and
`new_password2`, each at most 128 characters and subject to the configured
password validators. It rejects unknown fields, expired/revoked/consumed or
superseded challenges, inactive invitation lineage, more than the fixed abuse
attempt limit, and changed email ownership. Errors are non-enumerating. The
password and raw code are never retained in form errors, audit, logs, metrics,
security history, or delivery evidence.

### Configuration metadata and source

| Field | Type and bounds | Validation |
| --- | --- | --- |
| `source_kind` | Required closed choice: `blank`, `published_template`, `prior_edition` | Exactly one source branch; source choices are server-projected and authorized |
| `source` | Required only for a non-blank source | Exact immutable eligible version in the same organization; target edition excluded |
| `name` | Required Unicode text, 1–160 characters | Trim/collapse ordinary whitespace; unique version meaning within the edition |
| `opens_at`, `closes_at` | Required aware local date-times | Enter/display in edition time zone, store aware UTC instant; close strictly after open |
| `capacity` | Integer, 1–1,000,000 | Hard overall admission ceiling enforced independently of each product ceiling |
| `currency` | Required 3-letter code | Code-owned ISO 4217 choice allowed by the edition; uppercase persisted |
| `minimum_age` | Integer, 0–120 | Below 18 requires a complete enabled minor policy before activation |
| `default_payment_window_minutes` | Integer, 15–43,200 | Display human duration and persisted exact minutes |
| `waitlist_enabled` | Boolean | Automatic promotion must be false when wait-listing is false |
| `automatic_waitlist_promotion` | Boolean | Requires wait-listing and readiness of the offer worker |
| `review_note` | Optional text, at most 2,000 characters | Required to resolve imported review state; never interpreted as policy code |
| `reason` | Required text, 1–240 characters | Required for update, activation, retirement, and successor commands |
| `expected_version` | Zero for first creation, otherwise positive integer | Compared under aggregate lock |
| `retry_key` | UUID in HTML; API header only | Bound to actor, exact scope, operation, and normalized input |

For a copied draft, a truly omitted optional override may inherit the displayed
source value where the command variant documents that behavior. Presence is
tested explicitly, never by truthiness: capacity `0` is present and invalid,
not a request to inherit. Empty text/list and `false` likewise retain their
declared field meaning instead of silently selecting a source/default.

Activation additionally requires the exact current edition name as a
1–160-character case-sensitive confirmation, current source digest, resolved
review state, and current expected aggregate version. Confirmation text is not
persisted as a second edition fact. The schema version assigned to an activated
form is server owned and distinct from the aggregate version used for
concurrency.

### Sections and questions

| Record | Fields and bounds | Invariants |
| --- | --- | --- |
| Section | key 1–80 lowercase slug; title 1–160; description 0–500 | Key unique in configuration; position selected by bounded move target |
| Question | key 1–80 lowercase slug; label 1–200; help 0–2,000; purpose 1–240 | Key unique; purpose and C1/C2 classification required |
| Question type | `short_text`, `long_text`, `boolean`, `single_choice`, `multiple_choice`, or `integer` | Type is immutable after activation; answers use the shared typed validator |
| Options | 2–64 unique labels of 1–120 characters for choice types; empty for other types | Trim labels, preserve display case/order, reject duplicates after normalization |
| Visibility | `attendee_and_staff` or `registration_staff` | Staff-only fields cannot be supplied or satisfied by an attendee client |
| Condition | optional prior question key plus value of at most 120 characters | Both or neither; no self-reference, forward reference, cycle, incompatible value, or cross-configuration key |
| Requiredness and section | Boolean plus optional exact same-configuration section | A required conditional field must have a reachable visible path |

Short-text answers are at most 500 characters and long-text answers at most
4,000. Multiple-choice answers contain at most 64 unique allowed values.
Integer inputs use the signed 32-bit range `-2147483648` through `2147483647`
rather than arbitrary JSON numbers. Empty strings, whitespace-only required
values, alternate JSON types, and undeclared question keys are rejected.
The question collection itself may be empty; activation cannot invent a
placeholder question or require duplication of a typed core-profile field.

### Products

| Field | Type and bounds | Validation |
| --- | --- | --- |
| `code`, `entitlement_code` | Required lowercase slugs, 1–80 characters | Unique product code; reserved authoritative namespaces remain code owned |
| `name`, `entitlement_name` | Required text, 1–160 characters | Trim/collapse ordinary whitespace |
| `description` | Optional text, at most 2,000 characters | Plain text in the builder; safe rendering at clients |
| `price_minor` | Integer, 0–1,000,000,000,000 | Exact minor units in configuration currency; never accept a float |
| `capacity` | Integer, 1–1,000,000 | Concurrency still enforces actual hard availability |
| `sales_open_at`, `sales_close_at` | Optional aware date-times | Both absent or close after open; coherent with explained registration availability |
| `required_capacity_codes` | Up to 32 unique stable codes, each at most 80 | Every code exists in the active participation-capacity catalog; non-empty list requires explanation |
| `eligibility_explanation` | Optional text, at most 240 characters | Required and attendee-safe when eligibility is restricted |
| `waitlist_enabled` | Boolean | Cannot bypass parent wait-list policy |
| `payment_window_minutes` | Optional integer, 15–43,200 | Overrides only the parent deadline, not payment evidence rules |

Ordering uses the same bounded move contract as questions and sections.
Products referenced by registrations, offers, reservations, orders,
entitlements, credentials, finance evidence, or submissions are never deleted
or rewritten; later policy uses retirement or a successor configuration.

### Minor policy

The minor-policy editor accepts `enabled`, `minor_age_threshold` from 1 through
120, `guardian_notice_version` up to 40 characters, `jurisdiction_code` up to
40 characters, and `review_reference` up to 120 characters, plus reason,
expected version, and retry key. The guardian threshold must be above the
configuration's absolute minimum age. An enabled policy requires every
review-evidence field and an authorized server-attributed reviewer/time. The
operator cannot submit reviewer identity or review timestamp. A disabled
policy cannot activate a configuration whose minimum age would admit a minor.

### Profile-extension definitions and values

Definitions use the question key, label, help, type, options, purpose,
classification, requiredness, and ordering bounds above. They additionally
accept `attendee_visible`, writer policy (`attendee`, `registration_staff`, or
`attendee_and_staff`), and one optional authorized published-template or exact
prior-edition source. Attendee-writable fields must be attendee-visible. Only
C1/C2 is allowed. Keys beginning with `infinity`, `admission`, `entitlement`,
`payment`, `role`, `capacity`, or `restriction` are rejected for the
authoritative-domain reason, not merely as a naming preference.

Implementation staging note: the current corrective lifecycle candidate
accepts only a blank source for a newly created canonical profile definition.
Template and prior-edition source selection fails closed until storage can bind
the claim to one exact source definition identifier, generation, and canonical
digest as this contract requires. Historical legacy container pointers remain
preserved but do not authorize a new import claim.

Create/update, approval, activation, retirement, and successor creation are
separate commands. Approval records the actual current actor and server time.
Activation requires approved current review and expected version. Retirement
does not erase earlier values. One predecessor may have at most one non-retired
successor. The model and database enforce that invariant independently of the
command, activation proves the exact successor-start evidence graph, and a
retired definition version is terminal.

Lifecycle retry replay is evidence verification, not receipt lookup. The exact
action-specific target tuple and current definition digest must match the
immutable receipt, audit, event, and required outbox graph. Receipt and target
evidence is append-only at the database boundary. A populated downgrade that
would remove successor action semantics fails closed and uses fix-forward
recovery.

Value writes accept one exact field identifier, the typed value, current
expected field-key sequence, retry key, and a staff reason of 1–500 characters
when the actor is not the registration owner. The client cannot submit account,
registration, organization, edition, field key/version, sequence result,
actor, source channel, time, or audit data. A required field cannot receive an
empty normalized value. An explicit clearing revision is available only where
the definition is optional and the owning retention/purpose policy permits it;
history remains append-only.

The value aggregate has one durable control per registration/stable field key
and one immutable receipt per successful command. The receipt binds actor,
writer kind, exact scope and field, request digest, expected/result sequence,
retry key, revision, correlation, and minimized audit/event/outbox evidence.
An exact retry returns that historical result even after later commands advance
the control; it does not require the historical revision to remain current.
Revision and receipt insertion, current-pointer advancement, evidence, and the
response projection either commit together or roll back together.

The attendee/staff value projection is a deterministic limit-plus-one query of
at most 128 active fields. It releases only the current value and sequence for
each permitted stable key, performs a fresh final authorization decision,
appends a sensitive-read audit, and includes a digest over field identifiers,
definition versions, and current sequences. It never returns revision history
or staff-only definitions to an attendee.

Each profile-extension definition selects exactly one reader audience: owner
self-service, exact registration staff, one exact current Department/team, all
confirmed attendees, or public. Writer policy remains separate and cannot be
broadened through the reader setting. Confirmed-attendee and public values join
only the minimized attendee-directory projection, require current edition
directory consent plus confirmed/check-in state, and are rechecked immediately
before release. Withdrawal therefore removes publication without a cleanup job.

The v1 value `POST` adapters require `expected_sequence` in the closed JSON
body and one canonical lower-case UUID in `Idempotency-Key`; successful
responses include `Idempotent-Replay`. Missing/invalid input is `400`, hidden
scope or field is `404`, sequence/retry/limit conflict is `409`, and incomplete
atomic evidence is a name/value-free RFC 9457 `503`. Staff reads and writes use
only `registration.view_profile_extensions` and
`registration.update_profile_extensions`; broader registration-summary or
on-behalf authority does not imply access.

## Limits, ordering, and fail-closed reads

Registration setup and account onboarding owns code-defined ceilings so one tenant cannot create an unbounded
projection or hide omitted records behind an apparently complete editor:

| Projection dimension | Hard ceiling |
| --- | ---: |
| accounts returned per page | 100 |
| invitation transition/delivery rows shown per detail | 100 |
| selectable published template versions | 100 |
| selectable platform starter versions | 100 |
| selectable prior editions | 100 |
| drafts per edition | 32 |
| sections per configuration | 64 |
| questions per configuration | 256 |
| products per configuration | 128 |
| options per choice question or field | 64 |
| profile-extension definitions per edition | 128 |
| profile-extension fields in one attendee/staff projection | 128 |

Every limited query performs a limit-plus-one probe and deterministic ordering.
Crossing a ceiling returns a typed `registration_setup_limit_exceeded` or
`account_inventory_limit_exceeded` state with no partial editable collection.
The response explains which code-owned limit needs an architecture review. A
client-provided `page_size` cannot exceed the account ceiling. Search text is
2–120 characters after normalization; a blank search means stable first page,
not an unbounded scan.

Read composition captures one projection instant and compares the relevant
account-inventory or registration-setup aggregate control before and after the
bounded query. Movement retries the complete projection once; a second
movement fails generically. Snapshot coherence does not replace the fresh
final authorization decision. If protected-name read audit cannot be appended,
the response releases no names or partial data.

## Lifecycle, provenance, and immutability

Configuration and template lifecycles are `draft`, `active`/`published`, and
`retired`. There is at most one active registration configuration per edition.
A published template and active configuration are immutable. Retirement is a
reasoned lifecycle transition, not deletion. A successor copies independent
draft rows and retains exact predecessor provenance; it never changes the form
or price snapshot held by an existing registration.

Imported tenant content records source organization, optional series, exact template
or edition/configuration identity, source version, canonical content digest,
import time, importing actor, and `review required`. Source labels are shown
only after current source-scope authorization; stable identifiers/digest may
remain as non-disclosing evidence if later access is lost. Import never copies
accounts, answers, registrations, submissions, orders, entitlements, payment
evidence, invitations, assignments, or profile values.

Code-owned platform starters use a deterministic catalog identifier plus exact
starter version and digest instead of pretending to be tenant records. Explicit
selection copies independent edition-owned sections/questions/products into a
review-required draft. Catalog upgrades never rewrite an existing copy, and
organizer edits never alter the code-owned starter or another tenant's copy.

Ordinary configuration mutations are allowed for Draft/Preparing edition work
under a non-Suspended, non-Closed organization. Ready, Live, and Closing
edition changes need an accepted high-impact change-control contract before
Registration setup and account onboarding enables them. Archived and Cancelled editions are read-only; a future
reasoned correction workflow may append evidence but cannot rewrite historical
submissions. Organization suspension/closure and edition movement are checked
again inside every command transaction.

## Atomic evidence and effects

Each successful tenant mutation commits these inseparable records:

1. the exact domain transition;
2. a scope-bound idempotency receipt and request digest;
3. value-minimized administrative audit evidence;
4. a minimized domain event with aggregate type/id/version and safe state; and
5. an outbox message for every required asynchronous effect.

Invitation commands instead commit account/invitation state, a scope-bound
receipt, global administrative audit, subject security history where
applicable, and the durable platform identity-delivery record. They never use
a placeholder organization event. The worker delivers after commit with
at-least-once retries, provider idempotency where available, uncertainty
reconciliation, quarantine, and an explicit operator retry path.

An audit/event/effect payload may contain stable identifiers, safe operation
code, status, old/new aggregate version, schema/template version, counts,
source channel, outcome, and correlation identifier. It excludes email,
handle, display name, question/field labels, help/purpose text, answers, profile
values, staff reasons, free-text review notes, price values, provider payloads,
and raw invitation tokens. Logs and metrics obey the same minimization.

Database, authorization, validation, audit, event, outbox, receipt, delivery
evidence, and concurrency failures roll back the whole mutation. External
delivery failure after commit is an explicit durable state, not rollback and
not success. Duplicate delivery is tolerated by the adapter; duplicate domain
state is prevented by the command receipt and challenge state.

## Privacy and retention classification

| Data | Classification | Visibility and handling |
| --- | --- | --- |
| account email, login handle, display name | C2 | recipient and active platform administrators; no tenant visibility from identity alone |
| preferred language and non-personal lifecycle state | C1 | purpose-limited account operation |
| raw invitation token/password | C4 | password never retained; token exists only as an envelope-encrypted delivery payload until delivery/revocation/supersession/expiry and is never persisted plaintext or emitted to evidence |
| token digest, abuse counters, request fingerprint | C3 | identity-security worker and authorized security operations only |
| invitation reason and safe delivery failure detail | C2 | active platform administrators; value excluded from audit/event/log metadata |
| configuration/template definitions | C1 or C2 | exact edition/template authority; published public wording is a separate projection decision |
| profile-extension definition | Declared C1 or C2 | exact edition authority; purpose, reader audience, and separate writer policy mandatory |
| profile-extension value and staff reason | Inherits C1/C2 field, reason C2 | owner, exact registration/Department audience, or consented minimized confirmed/public directory projection; never catalog-wide |
| legal name/address/date of birth/guardian/emergency/safety data | C3 purpose-specific domain | excluded from generic Registration setup and account onboarding question and extension definitions |
| audit, receipt, event, delivery control | C1–C3 minimized evidence | append-only/control access; no source values or bearer secret |

Before release, the privacy inventory must assign purpose, controller,
retention trigger, maximum period, deletion/anonymization action, data-subject
visibility, export behavior, and lawful basis to the invitation and new control
records. Registration setup and account onboarding does not invent durations in the UI. Accepted identity facts
follow the account lifecycle; expired/revoked invitation delivery evidence does
not become indefinite marketing/contact history. Legal, payment, registration,
and audit retention remain separate and cannot be shortened through a setup
edit.

## Error, accessibility, and responsive behavior

Validation remains adjacent to the affected field and preserves safe operator
input. The page distinguishes validation, stale version, changed idempotency
reuse, protected dependency, lifecycle conflict, authorization denial,
projection overflow, database failure, and downstream delivery failure. It
never turns a dependency error into an empty list or tells a public caller
whether an email exists.

The desktop builder uses a readable record column beside the shared sidebar;
it does not center the whole administration grid with a large left margin. At
390 CSS pixels, navigation stacks without horizontal overflow, tables become
labelled record cards or scroll only within an explicitly labelled region, and
actions remain in source order. Dragging is optional enhancement only: every
move has keyboard-operable before/after controls. Status, validation, required
state, classification, and access never rely on color alone.

Every input has a persistent label, help connected with `aria-describedby`,
announced error, sensible autocomplete, and visible focus. Dialogs are not
required for core operations. High-impact activation/revocation/retirement
confirmation pages receive focus at their heading and list the exact effects.
Form recovery must not place passwords or invitation codes back into HTML.
Target accessibility is WCAG 2.2 AA with automated and manual keyboard/screen
reader evidence.

## Staged writer retirement and recovery

Implementation must inventory and retire at least these direct writer classes:

- registration-template model admin and its section/question/product inlines;
- registration-configuration model admin and its section/question/product
  inlines;
- minor-registration-policy model admin;
- registration-profile-extension-field model admin;
- payment-provider-account model admin where it can bypass its owning command;
- identity account-add/change paths that can assign invitation-subject
  credentials directly; and
- demonstration fixture/import code that saves those aggregates directly.

The activation sequence is additive controls/backfill, shared commands and
adapters, read-only/unregistered direct writers, then database stopped-writer
guards/readiness. Legacy rows receive an honest legacy origin and no invented
actor/source digest. Readiness names the exact schema/writer generation and
proves all runtime processes use it. Rollback before the guard can disable the
new routes. Rollback after the guard requires a controlled migration-owner
procedure; application runtime cannot silently reopen a direct writer.

The current React client may read or call compatibility adapters during the
transition, but it cannot remain a second owner of registration mutations.
Its registration navigation is removed only after API parity, consumer
inventory, browser replacement, and deprecation evidence pass.

## Verification and educational smoke contract

Registration setup and account onboarding cannot be marked implemented until verification includes:

- unit tests for every normalization, bound, closed variant, lifecycle,
  immutable-state, condition graph, authoritative-key, and privacy rule;
- service tests for exact tenant/edition authorization, platform oversight,
  actor/subject separation, expected versions, idempotent replay/conflict,
  locks, rollback, append-only values, zero-custom-question activation,
  omitted-capacity inheritance versus explicit-zero rejection, and minimized
  evidence;
- integration tests against PostgreSQL for unique active versions, concurrent
  source import/activation/invitation/value writes, database guards, audit and
  outbox atomicity, and direct-writer rejection;
- API contract tests that reject unknown/client-owned fields and prove every
  RFC 9457 response and OpenAPI schema;
- delivery-worker tests for delayed, duplicated, transiently failed,
  permanently failed, revoked, superseded, expired, and consumed invitations;
- browser tests for empty, populated, denied, stale, overflow, dependency,
  delivery-failure, success, validation, keyboard ordering, the
  320/390/768/958/1,024/1,280/1,920-pixel matrix, and 200 percent zoom in the
  shared Maru shell;
- accessibility checks plus manual keyboard and representative screen-reader
  evidence; and
- performance tests at every declared ceiling with query counts, response-size
  budgets, and no unbounded cross-tenant scan.

The deterministic educational smoke journey uses only fictional names and
`.invalid` emails. It proves:

1. the platform administrator remains non-participating while creating the
   organization/series/edition spine and inviting synthetic person accounts;
2. an invitee accepts, chooses a password, signs in, and gains no convention
   access from invitation alone;
3. an exact-edition manager starts a reviewed draft, builds and activates one
   form, and cannot mutate the active version;
4. the person registers once through the same public contract and may fill an
   added attendee-writable extension without rewriting the submission;
5. exact-edition staff may update only a staff-writable field with a reason;
6. Infinity/special-ticket state remains an authoritative entitlement; and
7. foreign-tenant, under-scoped, stale, changed-retry, unknown-field, retired,
   replayed-challenge, and simulated audit/outbox/delivery failures leave no
   partial state or protected disclosure.

A local development fixture may document one shared convenience password for
those synthetic accounts only, must refuse production settings, and is not the
production invitation flow. No fixture, screenshot, tutorial, or test imports
or imitates identifiable people from a live volunteer roster.

## Operations and observability

Release readiness checks migrations, aggregate/control generation, command
writer generation, worker availability, invitation expiry/cleanup scheduler,
email adapter configuration, outbox lag, authorization catalog version, and
OpenAPI parity. A missing dependency fails closed before Registration setup and account onboarding is mounted as
canonical.

The invitation-retention production gate requires one complete approved JSON
policy, its exact migration-owner-activated database control, a successful
`retention-v2` heartbeat no more than 26 hours old, no unheld due backlog more
than 24 hours old, and immediate C4 envelope destruction for every terminal
invitation. No duration is inferred by code. Holds remain separate audited
commands; the worker still records and traverses held rows fairly while
readiness excludes them from actionable backlog. Registration setup edits cannot
release a hold or smuggle in deletion. Every successful scheduler heartbeat
uses a database-materialized timestamp and an INSERT-time cursor-coherence
guard; no public service accepts an evidence-time override.

Metrics are low-cardinality and contain no email, handle, name, reason, field
label, value, token, configuration name, or tenant name. Required signals
include command outcome by safe operation code, stale/replay conflicts,
projection overflows, command latency, invitation delivery age/attempt/result,
identity delivery backlog, encryption-key readiness, tenant outbox backlog,
activation failures, and
sensitive-read audit failures. Alerts name a safe internal record identifier
only through restricted operational tooling.

Runbooks must cover invitation delivery reconciliation and revocation,
lost/expired challenge reissue, identity conflict without disclosure,
configuration activation recovery, stuck outbox messages, source-digest
mismatch, database writer-guard readiness, and rollback. Operators may retry a
durable effect or command receipt; they may not edit status/evidence rows to
make a failed action appear successful.

## Explicit non-goals

Registration setup and account onboarding does not:

- create or infer convention relationships for a platform administrator or an
  invited person;
- require pre-created accounts before public registration;
- assign, reveal, email, or share production passwords;
- scrape or copy a public volunteer roster;
- replace applications for panels, DJs, Maid Café, charity performance, Art
  Show, dealers, volunteering, or other typed contributions;
- turn C3/C4 legal, guardian, safety, medical, payment, restriction, or identity
  information into generic questions/extensions;
- make special-ticket, admission, payment, role, capacity, or restriction facts
  self-asserted checkboxes;
- mutate submitted answers, historical schema snapshots, orders, payments,
  entitlements, or prior-edition profiles;
- expose payment-provider credentials or accept browser return as proof of
  payment;
- create a general page-local ACL, a second staff website, or a public annual
  frontend; or
- claim the direct-writer migration is complete merely because a new page is
  mounted.
