# Activity module

Status: Implemented bounded record-history projection for Convention series record and Event edition record
Last updated: 2026-08-01

## Purpose and requirements

`maru.activity` assembles small, audience-safe operational histories for
AUD-003, UX-021, and UX-023. It implements the distinction in
[Activity, audit, and history](../architecture/activity-audit-and-history.md):
a domain fact explains what happened to a record, while security audit proves
that authority was exercised. The two are correlated but are not
interchangeable products.

## Public contract

`record_activity(...)` requires:

- exact organization ID;
- exact aggregate type and aggregate ID;
- the display time zone; and
- a bounded limit, currently 20 on Convention series record and Event edition record.

The caller must already have authorization to view the record. The query asks
`maru.effects` only for allowlisted domain facts scoped to that organization and
aggregate, then asks `maru.identity` for safe display labels for the bounded
actor set. It returns immutable `RecordActivity` values containing action,
actor label, changed-field labels, and localized occurrence time.

## Allowlist and minimization

The first allowlist contains:

- convention-series created and updated;
- event-edition created and details updated; and
- event-edition lifecycle transitioned.

Wording and field labels are code-owned. Only declared changed-field names are
rendered; name, description, contact, date, locale, reason, form content, and
other entered values are not copied from payloads. Actor lookup returns a
display name or generic `Maru account`; deleted/missing actors and automation
use safe generic labels. Email, login handle, raw UUID, network data, source
channel, and audit policy detail are absent.

The current projection is C1 record history retained through its source domain
events. It is visible only with the parent record. It does not create new
person-associated tracking, analytics, or a duplicate durable activity table.

## Dependencies and boundaries

- depends on `effects.aggregate_domain_facts(...)` rather than importing the
  domain-event model directly;
- depends on `identity.account_display_labels(...)` rather than reading account
  contact/authentication fields;
- owns presentation vocabulary only, not source facts or actor identity; and
- must not read `AuditEvent` to reconstruct product history.

The current aggregate query is intentionally small. A later cross-domain or
department timeline needs its own access-aware query, pagination, correction/
supersession wording, subject visibility, and retention review.

## Failure behavior

Activity loads inside the record page's dependency boundary. A database
failure produces the page's generic 503 state rather than a partly truthful
record or leaked exception. Unknown event names and undeclared fields do not
render. Missing actor labels degrade to generic wording without failing the
record.

## Tests

Edition-spine tests cover exact organization/aggregate filtering, reverse
chronological order, bounded results, safe actor fallbacks, changed-field
allowlisting, value non-disclosure, lifecycle wording, and database failure.

## Limitations

This is M1 record history, not M2's full human activity workspace. It has no
cross-domain feed, department/resource audience calculation, comments,
correction/supersession UI, pagination, export, or **Manage access** action.
Those capabilities must not be inferred from the history blocks on Convention
series record or Event edition record.
