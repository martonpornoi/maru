# Page 6 contract: Create event edition

- Status: Implemented and backend-verified for platform oversight and scoped
  Executive Board authority; owner/browser rehearsal and visual-state
  residuals remain
- Route: `/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/new/`
- API: `POST /api/v1/organizations/<organization-id>/editions`
- Requirements: IDN-004, IDN-012, UX-012, UX-013, UX-019, UX-020, UX-022,
  UX-024, INT-001, NFR-009
- Decisions: ADRs 0037–0040

## Purpose and primary user

Create the first or next dated occurrence beneath an existing convention
series and make it immediately revisit-able. Creation establishes edition
identity only; it does not create people, governance, registration,
applications, programme, venue selection, departments, positions, shifts, or
staffing records.

The browser permits an active Maru platform administrator.
ADR 0040's active Board root also carries `events.create` for the trusted
organization scope; its backend authorization matrix passes. API and
service callers require that same capability. Platform attribution is audit
evidence, not participation.

## Placement and navigation

Page 5's **Convention editions** row exposes an adjacent **+ Add** action only
for an Active series beneath a non-Closed organization. Page 6 retains the
global, selected-organization, and selected-series sections, with the edition
add action current exactly once. Closed/inactive scope remains visible in a
409 explanation but does not render a working creation form.

On success the browser redirects to the new Page 7 record. It does not silently
select the edition as working context; selection is an explicit Page 7 POST.

## Explicit input contract

The persisted edition fields are non-null. The idempotency receipt is internal
control evidence retained with the created edition. Dates are calendar dates,
not ambiguous local timestamps.

| Field | Type and format | Bounds; null/blank | Normalization | Classification and writer | Lifecycle and retention |
| --- | --- | --- | --- | --- | --- |
| `name` | Unicode text | 1–160 characters; null/blank forbidden | Trim ends and collapse internal whitespace | C1 edition setup; browser/API `events.create` holder, including explicit platform policy | Creation value; later editable only in Draft/Preparing; retained with edition |
| `starts_on` | ISO calendar date (`YYYY-MM-DD`) | Required; null/blank forbidden | Parse as date, without time-zone conversion | C1 edition setup; same writer | Must be on/before end; retained with edition history |
| `ends_on` | ISO calendar date (`YYYY-MM-DD`) | Required; null/blank forbidden; at most 31 days after start | Parse as date, without time-zone conversion | C1 edition setup; same writer | Must be on/after start; retained with edition history |
| `time_zone` | IANA time-zone identifier | Required; model max 63 characters; null/blank forbidden | Trim and validate against installed IANA zone data; browser inherits organization default | C1 locale setup; same writer | Later editable only in Draft/Preparing; retained with edition |
| `language_codes` | Ordered list of language codes | 1–16 unique valid codes; each ≤35 characters; null/blank forbidden | Trim and lowercase; browser inherits organization defaults | C1 locale setup; same writer | Later editable only in Draft/Preparing; retained with edition |
| `currency_codes` | Ordered list of ISO 4217 codes | 1–8 unique codes; each exactly 3 letters after validation; null/blank forbidden | Trim and uppercase; browser accepts comma/whitespace separators, maximum 39 input characters | C1 finance-locale setup, not payment data; same writer | Later editable only in Draft/Preparing; retained with edition |
| `series_id` | UUID | API required; null/blank forbidden; absent from HTML | Parse canonical UUID | C1 trusted scope pointer; API `events.create` holder | Must resolve under route organization; never copied from browser input |
| Browser `idempotency_key` / API `Idempotency-Key` | UUID retry key; hidden form field or HTTP request header | Required; null/blank forbidden | Parse UUID; preserve the browser value through validation; API body never contains it | Internal C1/C2 control metadata because receipt links actor and scope; same command caller | One receipt per actor/series/key; retained with edition; not a secret or routine display value |

Organization, slug, lifecycle, lifecycle version, aggregate version, actor, and
timestamps are server-owned. HTML accepts the six human fields,
`idempotency_key`, and CSRF. API JSON accepts exactly `series_id` plus the six
human fields and requires the UUID `Idempotency-Key` request header. It rejects
an `idempotency_key` JSON property like every other undeclared body key. Unknown
keys are rejected with an actionable validation error rather than ignored.
Trusted organization scope always comes from the route.

Validation identifies the affected field and uses stable service/API codes for
the security-critical cases: `edition_name_required`,
`edition_name_too_long`, `edition_end_before_start`,
`edition_date_range_too_long`, invalid time-zone/language/currency codes,
`missing_idempotency_key`, `invalid_idempotency_key`, `unknown_input_field`,
`edition_parent_closed`, `edition_series_inactive`, and
`edition_creation_idempotency_conflict`. UI text says how to correct the value
without echoing another tenant's record or an internal exception.

## Resulting state and idempotency

Maru generates a lowercase, at-most-80-character slug unique
case-insensitively within the series; collisions receive bounded numeric
suffixes and an empty Unicode transliteration falls back to `edition`. The
edition begins in Draft, with lifecycle version 0 and aggregate version 1.

The service normalizes the complete payload and binds its SHA-256 digest to the
actor, series, and idempotency UUID. A retry with the same key and normalized
payload returns the original edition (`200` API or ordinary redirect); reuse
with different payload returns 409. The database requires the stored digest to
be exactly one lowercase SHA-256 value. The audit stores only a hash of the key.
The receipt is append-only and its edition/organization/series scope is guarded
in PostgreSQL.

## Authorization, transaction, and evidence

The route and supplied API series UUID must resolve to the exact organization;
the organization and series are locked. A Closed organization or Inactive
series returns conflict. Authorization runs before mutation and is repeated by
the application service.

Edition, receipt, value-minimized audit event,
`events.edition.created.v1`, and its transactional outbox delivery commit in
one transaction. Failure of any required write leaves none of them behind.
Creation does not select a workspace or grant any relationship.

The M1 header truthfully identifies platform oversight and no convention role.
The M2 adapter must also explain an active Board assignment's
organization-scoped `events.create` without exposing other principals. It
remains narrower than department/resource/field access, and **Manage access**
does not appear until that underlying editor exists.

## Page and API states

- **Initial:** inherited time zone/languages are visible, other inputs blank,
  generated retry key hidden, and Draft/no-side-effect boundaries explained.
- **Validation:** field-local errors and preserved idempotency key; no partial
  edition or evidence.
- **Success:** new creation redirects to Page 7 / API 201.
- **Replay:** original edition reused / API 200.
- **Conflicting replay or blocked parent:** 409 and no mutation.
- **Denied:** 403 without cross-tenant existence disclosure.
- **Not found:** authorized caller receives 404 for unknown scoped parents.
- **Dependency failure:** generic 503/retry problem with complete rollback and
  no internal exception text.

## Verification required for completion

- every boundary, locale, currency, date, Unicode, and slug collision case;
- strict unknown-field, forged organization/series, cross-tenant, denied, and
  projection tests;
- same-key replay, changed-payload conflict, concurrent double-submit, and
  receipt-scope/immutability tests;
- audit/outbox failure rollback and value minimization;
- migration preflight for overlong historical editions, oversized language or
  currency collections, unsupported currencies, aggregate-version backfill,
  receipt digest integrity, and fail-closed downgrade fencing;
- no relationship or operational side effects;
- OpenAPI/generated-client drift; and
- keyboard, focus, desktop, 390-pixel, blocked/error, and navigation evidence.

## Explicit non-goals

- Selecting the edition automatically.
- Registration/form inheritance or publication.
- Lifecycle transition, organization governance, programme, venue, documents,
  logistics, staffing, or access assignment.
