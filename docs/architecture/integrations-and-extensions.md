# Integrations and extensions

Status: Baseline  
Last updated: 2026-07-26

Maru removes app hell by becoming the canonical event record and action center.
It does not remove every specialist provider. Integrations must reduce duplicate
accounts, re-entry, and contradictory state rather than merely adding a menu of
links.

## Contract layers

### Internal module contracts

- **Command:** a request to perform one authorized domain action.
- **Query:** a purpose-built, policy-filtered read.
- **Domain event:** an immutable fact emitted after a successful transition.

Public contract packages contain identifiers, typed values, schemas, and
protocols. Another module does not import private models, services, migrations,
admin classes, or repositories.

### External API

The supported REST API provides:

- edition- and organization-explicit routes;
- OpenAPI 3.1 description and generated client compatibility;
- opaque identifiers and discoverable scoped aliases;
- cursor pagination for changing collections;
- consistent filtering, sorting, sparse authorized fields, and include limits;
- RFC 9457-style problem details with stable Maru error codes;
- optimistic concurrency with entity version or `If-Match` where collision
  matters;
- `Idempotency-Key` for retried commands;
- correlation and request identifiers;
- UTC timestamps plus authoritative edition time-zone metadata;
- documented rate, size, cardinality, and cost limits;
- deprecation and sunset headers; and
- explicit preview endpoints for high-impact actions.

An API version is a compatibility contract, not a copy of internal Django URLs.
Breaking change requires a new major boundary or supported transition period.

### Domain event envelope

```json
{
  "event_id": "opaque-id",
  "event_type": "schedule.release.published.v1",
  "occurred_at": "2026-07-26T12:00:00Z",
  "organization_id": "opaque-id",
  "event_edition_id": "opaque-id",
  "aggregate_id": "opaque-id",
  "aggregate_version": 7,
  "actor": {"kind": "account", "id": "opaque-id"},
  "correlation_id": "opaque-id",
  "causation_id": "opaque-id",
  "classification": "C1",
  "data": {}
}
```

Payloads are minimal and versioned. Consumers fetch an authorized projection
when they need more detail. Restricted case contents never enter a general
event stream.

## Transactional delivery

The state transition and an outbox record commit in one database transaction.
Workers claim outbox entries, execute internal projections or connector
deliveries, and record outcome. Delivery is at least once; consumers and
adapters are idempotent.

Failure does not roll back the canonical action after commit. Operators can see
retry, quarantine, compensation, and reconciliation.

## Connector contract

Every connector declares:

- provider and supported capability version;
- direction: inbound, outbound, or reconcile;
- required scopes and credential type;
- data classes transmitted and provider regions where known;
- installation owner and organization/edition scope;
- trigger and mapping configuration;
- rate, batch, file, text, and media limits;
- idempotency and remote identifier behavior;
- health, last success, backlog, and permanent failure;
- secret rotation and webhook-verification method;
- disable, disconnect, export, and deletion behavior; and
- sandbox or rehearsal support.

Connector code validates provider data as untrusted input. It cannot call
private module models.

## Integration catalog

| Category | Maru owns | Provider may own |
| --- | --- | --- |
| Identity | account link, organizer relationship, policy, session history | credential authentication, federation assertion |
| Payments | order intent, entitlement, reconciliation, attendee timeline | card data, authorization, settlement rail |
| Email/SMS/push | canonical message, audience, consent class, delivery state | transport and remote delivery diagnostics |
| Social networks | canonical announcement and approved variant | external post and platform interaction |
| Website/CMS | structured approved event facts | presentation and editorial material outside Maru |
| Calendar | authoritative commitments and release | personal calendar copy |
| Accounting | operational ledger, evidence, mapping, reconciliation state | statutory ledger and reporting |
| File/signature | classified file relationship and workflow state | binary storage, e-sign ceremony where selected |
| Team collaboration | task/message handoff where justified | optional general discussion |
| Access control | entitlement and credential policy | door-controller execution |
| Maps/signage | approved locations, programme, alerts, playlists | visual renderer or hardware player |
| Analytics/BI | governed read model and aggregate definition | additional authorized visualization |
| Travel/hotel | request, approved assignment, operational reference | property or carrier booking system |

## Announcement adapters

Website, platform inbox, email, push, X, Bluesky, Telegram, Barq, and future
destinations are capabilities, not promises that a provider always exposes a
usable API.

Each adapter reports:

- text, rich text, image, link, localization, scheduling, reply, edit, and
  deletion capabilities;
- account authorization and credential health;
- rendered preview and any loss of formatting;
- submitted, accepted, delivered where knowable, failed, rate-limited, and
  unknown states;
- remote identifier and immutable published rendition; and
- correction behavior.

If a destination cannot be automated, Maru produces an approved copy package
and manual-publication task with confirmation evidence. It does not pretend
manual publication was API-verified.

## Identity and single sign-on

One Maru account may link several authentication methods after strong
verification. The platform never assumes two accounts are the same because
their display name, handle, or email looks similar.

For organizers that use external workspaces:

- Maru remains the role and access-intent source where configured;
- provisioning creates a provider assignment with its own scoped service
  identity;
- observed provider state returns through reconciliation;
- discrepancy is visible and assigned;
- offboarding is incomplete until revocation is confirmed or accepted as risk;
  and
- connector outage never makes an expired Maru grant active again.

## Webhooks

Subscriptions are bound to an approved integration, event types, tenant scope,
classification ceiling, endpoint, owner, and expiry/review.

- Verification challenge proves endpoint control.
- Requests are signed over raw bytes with timestamp and rotating key ID.
- Receivers reject stale replay outside the documented window.
- Delivery has stable ID, attempt history, exponential backoff, and
  dead-letter state.
- Operators can replay a selected safe range.
- Redirects and destination changes are revalidated against SSRF policy.
- Payload retrieval remains authorized after queued delay.

## Imports

Imports follow:

```text
upload -> quarantine -> parse -> map -> validate -> preview
       -> authorize frozen change set -> apply -> reconcile -> receipt
```

Each staged row has source, input hash, mapping version, proposed action,
warning/error, and eventual result. CSV and spreadsheet content is treated as
untrusted. Identity matching never relies only on display name.

Imports do not become a permanent backdoor around workflow, state transitions,
or audit.

## Application installation

A third-party application has:

- developer/publisher identity;
- manifest and supported contract version;
- declared data use and privacy contact;
- redirect/webhook origins;
- requested read, write, event, and field scopes;
- organization approver;
- edition and resource boundaries;
- service principal and credential;
- installation owner and review date;
- activity and error history; and
- revoke and data-deletion procedure.

User authorization cannot grant scopes the organization has not installed.
Organization installation cannot make an app read a user's unrelated
cross-organizer profile.

## Extension points

In-process extensions are trusted code and therefore require review, release,
and deployment. They may register only versioned contracts:

- module command or event handlers;
- classified field and query definitions;
- workflow states, rules, and tasks;
- forms and validators;
- safe actions and object-workspace panels;
- reports and export templates;
- schedule constraints;
- connector adapters; and
- readiness criteria.

Extension declarations include owner, module namespace, migration behavior,
capabilities, data inventory, settings schema, health, tests, and removal
procedure.

Runtime organizer customization uses configuration and automation, not uploaded
arbitrary Python.

## Compatibility and removal

- API, event, and extension contracts use semantic compatibility rules.
- A deprecation records replacement, first warning release, usage by installed
  consumers, planned sunset, and owner.
- CI tests maintained example consumers and event fixtures.
- Database expand/migrate/contract supports rolling compatibility.
- Disabling a connector stops future access but preserves minimal historical
  delivery and reconciliation records.
- Removing an extension requires data export, retention disposition, workflow
  migration, capability cleanup, and unresolved-work report.

## Integration readiness gate

A connector is production-ready only when:

- happy path and provider sandbox are tested;
- credential loss, expiry, and rotation are tested;
- duplicate, delay, reordering, rate limit, malformed input, and partial
  provider failure are tested;
- reconciliation identifies drift;
- personal-data transfer and retention are documented;
- support can diagnose it without reading protected content;
- spend and resource limits are configured;
- disablement and replacement are rehearsed; and
- the event has an alternative for the live-critical consequence.
