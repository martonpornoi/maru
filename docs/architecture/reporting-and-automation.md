# Reporting, documents, and automation

Status: Baseline with first registration reporting preset  
Last updated: 2026-07-29

Maru should let ordinary authorized organizers answer operational questions
without SQL, while making it difficult to create an accidental disclosure,
unbounded query, misleading metric, or irreversible mass action.

## Semantic reporting layer

A module publishes versioned datasets rather than raw tables.

Examples:

- registrations and entitlements;
- order and payment reconciliation;
- programme readiness and publication;
- workforce demand, coverage, and onboarding;
- room and resource use;
- dealer application and fulfilment;
- asset custody and discrepancies;
- support demand and service level;
- announcement delivery;
- edition readiness and risk; and
- minimized historical participation.

Each dataset declares:

- stable identifier, version, owner, and description;
- grain: what one row represents;
- organization and edition scope;
- joins to other approved datasets;
- fields, types, labels, formats, and localization;
- sensitivity and required capabilities;
- filter, group, aggregate, sort, and export support;
- calculated-field definition and null/unknown meaning;
- freshness and authoritative source;
- row and cost estimates; and
- test fixtures and invariants.

The semantic layer keeps “attendee,” “checked in,” “volunteer hour,” “revenue,”
“capacity,” and “ready” from acquiring contradictory definitions in every
spreadsheet.

## Implemented registration preset

The first code-owned preset is `registration.attendee_report.v1`, exposed in
the Convention work Reports & badges destination and guarded by
`registration.view_attendee_reporting`.

- Grain: one confirmed or checked-in edition registration.
- Trusted scope: organization and edition are server-injected; clients cannot
  select models or joins.
- Fields: badge name and source, display name, pronouns, structured spoken
  languages, internal registration country code, registration state, broad
  authoritative attendee labels, and profile-photo review state.
- Aggregates: coming, confirmed, checked in, represented countries,
  volunteers, approved photos, country distribution, and attendee-level
  distribution.
- Filters: bounded search, country, attendee level, and page.
- Export: audited UTF-8 CSV with edition/generation metadata and spreadsheet
  formula neutralization.
- Explicit exclusions: legal name, contact, street/locality/postal address,
  emergency contact, arbitrary answers, exact product/payment/price, and
  internal comments.
- Bound: at most 5,000 synchronous source rows. Larger reports require the
  asynchronous artifact lifecycle below.

This preset deliberately precedes the generic semantic query AST. Its fields
and joins are code-reviewed and cannot be expanded through request parameters.

## Safe query representation

The UI builds a typed query abstract syntax tree:

```json
{
  "dataset": "workforce.coverage.v1",
  "scope": {"event_edition_id": "opaque-id"},
  "select": ["department", "starts_at", "required", "confirmed"],
  "filters": [
    {"field": "starts_at", "operator": "within_edition_day", "value": "Saturday"}
  ],
  "group_by": ["department", "starts_at"],
  "order_by": [{"field": "starts_at", "direction": "asc"}],
  "limit": 500
}
```

The server:

1. validates dataset and AST version;
2. resolves trusted tenant/edition context;
3. checks dataset and field capabilities;
4. injects mandatory policy filters;
5. estimates complexity and result size;
6. compiles only registered operators and joins to ORM/SQL;
7. executes under statement, row, memory, and concurrency limits;
8. applies output classification and small-group rules; and
9. records definition, version, scope, freshness, and result metadata.

Custom SQL, arbitrary model names, unregistered joins, expressions, and
functions are not accepted from clients.

## Saved questions

A saved question contains:

- query AST and semantic dataset version;
- plain-language purpose and output definition;
- owner and shared audience;
- relative edition scope rather than a hidden hard-coded edition where useful;
- display, chart, threshold, and unknown-data behavior;
- freshness expectation;
- classification and export allowance;
- last validation and result health; and
- migration state when the dataset changes.

Personal views do not silently become department truth. Certified questions
have an accountable data owner and versioned definition.

## Dashboards

Dashboards are composed from saved questions and actionable domain cards.

- Every number links to its definition and permitted underlying records.
- Data age and incomplete source state are visible.
- A target, threshold, comparison period, and denominator are explicit.
- Small cohorts are suppressed or broadened where re-identification is
  plausible.
- “Unknown” remains different from zero.
- Historical comparison includes material edition changes such as venue,
  duration, capacity, or policy.
- Readiness always links to criteria and evidence.

Dashboards do not become life-safety alarms without a separate validated
procedure.

## Export pipeline

```text
request -> authorize definition -> estimate -> queue -> reauthorize execution
        -> generate -> scan/validate -> classify -> deliver expiring artifact
        -> audit -> dispose
```

Supported baseline formats:

- CSV for interoperable tabular data;
- XLSX for formatted workbooks with metadata and multiple related sheets;
- PDF for stable printable or signed-off views;
- iCalendar for commitments and released timetable;
- JSON for supported data portability and integration;
- print-language outputs such as badge, label, or ticket PDF where required.

### Artifact rules

- Template and dataset version are embedded.
- Edition, local time zone, filters, generation time, requester or official
  publisher, classification, and data freshness are visible where appropriate.
- XLSX/CSV values that begin as formulas are neutralized by default.
- PDFs include accessible structure to the extent supported by the selected
  renderer and have a documented alternate accessible source.
- Restricted artifacts are encrypted in transit and storage, short-lived,
  unguessable, and reauthorized at download.
- Highly sensitive exports may require step-up, approval, reason, watermark,
  recipient, and download count.
- Generated artifacts are immutable; a correction creates a new version.
- Email attachments are avoided for restricted recurring reports; send a
  reauthorized link.

## Document templates

Templates combine approved structured data with a versioned layout:

- badge and credential;
- ticket/pass and check-in sheet;
- invoice/receipt or operational financial statement;
- schedule grid, programme book, room sign, and run sheet;
- volunteer roster, briefing, handover, and certificate;
- dealer pack, table card, intake label, auction sheet, and settlement;
- asset manifest, custody sheet, load list, and inventory count;
- emergency/fallback pack and contact sheet;
- contract, offer, policy, and acknowledgement record; and
- archive or board report.

A template declares supported data fields, classification, language, page
geometry, required approvals, sample fixture, accessibility alternative,
version, and retirement. User-authored HTML, office macros, and server file
access are prohibited.

## Operational workflow engine

Typed domain state machines remain in module code. Configuration may select
allowed transitions, owners, deadlines, forms, tasks, approvals, and
notifications within the module's declared extension points.

A workflow definition includes:

- subject type and version;
- states and terminal outcomes;
- transitions and commands;
- actor/capability;
- guard conditions;
- required fields, evidence, approval, and reason;
- generated tasks, messages, events, and deadlines;
- cancellation, correction, and appeal;
- migration path for in-flight subjects; and
- archive rendition.

Configuration cannot invent a transition that violates a code-owned invariant.

## Automation engine

An automation is:

```text
trigger + typed conditions + delay/debounce + bounded actions
```

Triggers may be a domain event, schedule instant, recurring review, threshold,
or explicit human invocation. Actions come from an allowlisted command catalog,
such as create task, assign queue, request approval, send template message,
set a permitted field, invoke a connector, or start an export.

### Authority

An automation has its own service principal with:

- organization/edition scope;
- capability ceiling approved at activation;
- action and audience limits;
- owner and review/expiry;
- definition version and deployment state; and
- separate credentials for any connector.

It cannot use the current viewer's broader authority or create a grant beyond
its ceiling.

### Execution

Each run records trigger, input identifiers and versions, conditions evaluated,
actions attempted, idempotency keys, approvals, outputs, errors, retries, cost,
and final state. Sensitive values are referenced or redacted in general run
history.

Loop detection uses causation chains, depth, frequency, and action limits.
Backpressure protects interactive operations and provider budgets.

### Lifecycle

```text
draft -> tested -> rehearsal -> approved -> active -> paused -> retired
```

Editing creates a new version. Existing runs retain their original definition.
A kill switch pauses new triggers without deleting queued or completed history.

## Preview and approval

Before activation or a high-impact manual run, Maru shows:

- sample matched records;
- exact fields and state changes;
- audiences and likely message volume;
- money, credential, publication, or access consequences;
- downstream connector calls and estimated cost;
- missing permission or data-class obligations; and
- rollback, compensation, or irreversibility.

The preview is itself authorized and cannot expose records merely because a
rule author lacks permission to act on them.

## Scheduling assistance

Constraint solvers and recommendation systems may propose:

- programme placements;
- shift candidates and coverage alternatives;
- rooms and equipment;
- hotel or scarce-resource allocation under an explicit policy;
- logistics routes and loading windows; and
- task sequencing.

The engine records:

- hard constraints that cannot be bypassed;
- soft constraints and weights;
- input snapshot/version;
- infeasible or unassigned demand;
- explanation for recommendation and conflict;
- manual locks and overrides; and
- accepted solution version.

It does not score a person's moral worth, loyalty, or hidden suitability.

## AI-assisted features

Optional model-assisted work may:

- propose a safe query AST from a natural-language question;
- summarize an authorized thread or handover;
- draft channel variants or translations for review;
- classify an incoming service request into a queue;
- extract proposed structured fields from a rider or form attachment;
- explain schedule conflicts; and
- suggest missing readiness evidence.

Controls:

- normal authorization happens before context retrieval and after output;
- provider, region, retention, and training use are documented;
- C3/C4 data is excluded unless an approved use case and deployment support it;
- prompts and outputs are treated as untrusted content;
- sources and uncertainty are shown;
- no automatic consequential HR, access, safety, financial, or disciplinary
  decision;
- prompt injection cannot invoke commands or broaden retrieval;
- human approval precedes publication or material mutation; and
- organizers can disable assistance without losing the underlying workflow.

## Testing

- dataset contract and known-answer fixtures;
- authorization over rows, fields, joins, aggregates, counts, and exports;
- query cost and adversarial cardinality;
- small-group privacy;
- formula and document injection;
- PDF/XLSX/CSV/iCalendar conformance and visual regression where relevant;
- automation idempotency, loop, pause, retry, approval, and permission ceiling;
- workflow migration with in-flight subjects;
- schedule-solver constraint and explainability properties; and
- AI feature evaluation for disclosure, injection, unsupported claims, and
  human-approval enforcement.
