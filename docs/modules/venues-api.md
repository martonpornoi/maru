# Venues API contract

Status: mounted strict adapter contract
Last updated: 2026-08-09

Venue routes use explicit organization, edition, and (for operational work)
typed edition-space identifiers. Authenticated adapters authorize before body
or query parsing, reject unknown inputs, and repeat tenant/object checks in the
shared command or query service. Mutations require one canonical lower-case
UUID in `Idempotency-Key`; versioned mutations also require the current
positive `expected_version`. Whitespace-padded keys are invalid. Commands that
create a new resource return `201`, while an exact idempotent replay returns
`200`.

```text
GET  /api/v1/public/organizations/{organization_id}/editions/{edition_id}/venue-schedule
GET  /api/v1/my/organizations/{organization_id}/editions/{edition_id}/venue-schedule
GET|POST /api/v1/organizations/{organization_id}/venue-properties
PATCH /api/v1/organizations/{organization_id}/venue-properties/{property_id}
POST /api/v1/organizations/{organization_id}/venue-properties/{property_id}/space-paths
POST /api/v1/organizations/{organization_id}/venue-properties/{property_id}/space-combinations
POST /api/v1/organizations/{organization_id}/venue-properties/{property_id}/media
POST /api/v1/organizations/{organization_id}/venue-properties/{property_id}/media/{media_id}/approve
POST /api/v1/organizations/{organization_id}/venue-spaces/{space_id}/layouts
POST /api/v1/organizations/{organization_id}/venue-layouts/{layout_id}/approve
POST /api/v1/organizations/{organization_id}/venue-properties/{property_id}/room-types
PUT  /api/v1/organizations/{organization_id}/accommodation-room-types/{room_type_id}/night-inventory
GET|POST /api/v1/organizations/{organization_id}/editions/{edition_id}/venues
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/venue-spaces
GET  /api/v1/organizations/{organization_id}/editions/{edition_id}/venue-spaces/{space_selection_id}
PUT  /api/v1/organizations/{organization_id}/editions/{edition_id}/venue-spaces/{space_selection_id}/availability
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/venue-spaces/{space_selection_id}/bookings
PATCH /api/v1/organizations/{organization_id}/editions/{edition_id}/venue-spaces/{space_selection_id}/bookings/{booking_id}
POST /api/v1/organizations/{organization_id}/editions/{edition_id}/venue-spaces/{space_selection_id}/bookings/{booking_id}/commands/{action}
```

Booking commands close `action` to `approve`, `publish`, `withdraw`, or
`cancel`. Independent approval and publication, hard availability, physical
overlap, configured/fire capacity, optimistic version, and idempotency
conflicts return stable non-partial errors. Staff schedule responses may
include restricted setup/effective/teardown and review state only after an
audited exact-space read.

Booking creation and rescheduling have separate closed bodies: creation forbids
`expected_version`, while rescheduling requires it and remains a complete
replacement despite using `PATCH`. Nested capacity and availability objects are
closed to unknown fields, and `space_kind` uses the code-owned Venue space-kind
catalog. Media approval requires `public_reference`; layout approval instead
accepts `approved_reference`, which is required by the service for public
layouts.

The public schedule response contains only active, approved, published
effective programme intervals, public copy, public venue/space/access facts,
and an optional approved public-layout rendition. My Maru returns the same
schema only for an exact confirmed, active, or completed Participation scope.
Authenticated Venue APIs set `Cache-Control` to a private no-store policy;
the public schedule route is the sole cacheable Venue API surface.
