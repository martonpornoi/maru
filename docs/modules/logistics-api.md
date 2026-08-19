# Logistics API

Status: bounded v1 contract accepted in the canonical current tree; read-only
responsive browser rehearsal passes while mutation-role and production rollout
remain gated
Last updated: 2026-08-11

## Boundary shared by every endpoint

All Logistics endpoints are authenticated and return `Cache-Control: private,
no-store` on successful responses and safe errors. There are no public
Logistics endpoints. Route scope and the minimum exact capability are checked
before query parameters, request bodies, or idempotency headers are parsed.
The command service then locks affected rows and repeats authorization against
the exact organization, edition, self relationship, or typed manifest binding.

JSON bodies are closed: unknown keys, duplicate scalar values at browser
boundaries, noncanonical UUIDs, alternate integer spellings, invalid closed
codes, and ambiguous or nonexistent edition-local times are rejected. A denied,
inactive, missing, or foreign target receives the same closed denial even when
the supplied payload is malformed.

Mutations use a canonical `Idempotency-Key` UUID and, for versioned aggregates
or event streams, an expected version or subject sequence. An exact retry
returns the recorded result. Reusing a key for a different canonical command is
a conflict. Free-text reasons are bounded and are not copied into generic audit
or outbox metadata.

## Personal equipment offers

- `GET|POST /api/v1/my/organizations/{organization_id}/editions/{edition_id}/equipment-offers`
  lists only the authenticated person's offers or submits a new offer while the
  edition is Preparing, Ready, or Live.
- `POST /api/v1/my/organizations/{organization_id}/editions/{edition_id}/equipment-offers/{offer_id}/withdraw`
  withdraws only that person's still-Pending offer at the expected version.

Self-offer authority is relationship-derived and cannot be persisted as a
grant. Contact fields are written only to a purpose- and retention-bound
restricted address. Offer/item/ownership evidence is retained separately from
contact disposal.

## Catalog commands

Organization-scoped commands use
`/api/v1/organizations/{organization_id}/logistics/` and require exact
organization `logistics.manage_catalog` authority:

- `POST parties`
- `POST restricted-addresses`
- `POST nodes`
- `POST assets`
- `POST stock-lots`
- `POST physical-keys`
- `POST physical-keys/{key_id}/keyholders`
- `POST labels`
- `POST agreements`
- `POST kits`

Edition-allocated commands use
`/api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/` and
require exact edition `logistics.manage_catalog` authority:

- `POST restricted-addresses`
- `POST nodes`
- `POST assets`
- `POST stock-lots`
- `POST physical-keys`
- `POST agreements`

The organization and edition variants call the same commands. A grant at one
scope does not silently cover the other. Reusable party profiles accept only
legal/public identity; operational contact values belong in restricted
addresses.

## Workspace, offers, manifests, and events

- `GET /api/v1/organizations/{organization_id}/editions/{edition_id}/logistics`
  returns the bounded edition workspace under `logistics.view_workspace` and
  audits its minimized personal-data projection.
- `POST /api/v1/organizations/{organization_id}/editions/{edition_id}/equipment-offers/{offer_id}/review`
  accepts or rejects one Pending offer under `logistics.review_offers` and an
  expected aggregate version.
- `POST /api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/events`
  appends one custody/movement/count/condition/damage/return event under
  `logistics.manage_operations` and the expected subject sequence.
- `GET|POST /api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/manifests`
  lists or creates manifests.
- `GET /api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/manifests/{manifest_id}`
  reads one exact manifest.
- `POST /api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/manifests/{manifest_id}/state`
  seals, completes, or cancels through the closed manifest transition command.
- `POST /api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/manifests/{manifest_id}/lines`
  adds one server-snapshotted line while the manifest is Draft.
- `POST /api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/manifests/{manifest_id}/lines/{line_id}/receive`
  records the Stage Tech receipt for an exact line under an exact
  `logistics.manage_manifest` binding, expected subject sequence, and
  idempotency key.
- `GET /api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/stage-receiving`
  returns the bounded Stage Tech projection.
- `GET /api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/activity`
  returns bounded event activity and audits the minimized operational read.

Manifest line labels are derived by the server and cannot be supplied by a
client. `Completed` freezes manifest definition and route facts, but a one-time
canonical late reconciliation event remains allowed for a line/event type.
Database uniqueness prevents repeating the same planned manifested traversal.

## Offline reconciliation

`POST /api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/offline-batches`
accepts one bounded, expiring, ordered batch under
`logistics.reconcile_offline`. Each operation carries a canonical idempotency
key, expected subject sequence, label references, and closed action. The server
is authoritative: appendable operations create normal custody events;
unavailable labels, state conflicts, count differences, or damage produce
closed review/discrepancy evidence. Exact duplicates reuse the prior canonical
receipt; conflicting reuse cannot overwrite it.

## Restricted contact reads

`POST /api/v1/organizations/{organization_id}/editions/{edition_id}/logistics/restricted-addresses/{address_id}/read`
requires `logistics.view_restricted_contacts`, one supported purpose code, and
an active retained exact address. The sensitive values are returned only after
the read audit commits. Browser access uses a short-lived opaque token; neither
surface places contact values in URLs, audit metadata, events, or logs.

## Verification and acceptance

The final canonical current-tree repository gate passed all 4,067 tests in
15,558.23 seconds (4:19:18) at 90.78 percent coverage. The authenticated
read-only browser rehearsal covered the Logistics workspace and Stage Tech
receiving projection at 1920 and 390 pixels: both had exactly one `main`
landmark and one H1, no horizontal overflow, and no mutation controls for the
rehearsed role.

This does not extend browser acceptance to a mutation-capable Logistics role.
Keyboard and automated-accessibility evidence, representative recovery,
deployment rehearsal, runtime production activation, and production approval
remain required. API mutation services retain their exact capability,
idempotency, version, and append-only evidence boundaries independently of the
read-only browser result.

## Known partials

The API does not yet provide maintenance scheduling/value-class workflow,
tracked loss/disposal, department demand/reservation planning, driver/route
planning, supplier acceptance/invoice linkage, low-stock/wastage workflow,
Party retirement, or a governed discrepancy-status workflow. Corrections
append a new event and, when investigation is required, a new discrepancy.
These omissions map to the partial LOG-001/002/003/004/006/007 requirements
and are not supported by direct database edits.
