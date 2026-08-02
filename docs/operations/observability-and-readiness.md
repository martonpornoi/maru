# Observability and operational readiness

Status: Executable registration, delivery, finance, privacy, and closure signals defined  
Last updated: 2026-07-28

Observability must answer “what is affected, for whom, since when, why, and what
can we safely do?” without turning logs into a second ungoverned database of
personal information.

## Signals

### Metrics

- request success, denial reason, latency, size, and saturation by capability;
- database connection, transaction, lock, replica, query, and storage health;
- cache effectiveness and coordination failures;
- outbox age, throughput, attempts, quarantine, and result by workload;
- connector health, provider response class, rate budget, and reconciliation
  drift;
- authentication, recovery, step-up, session, and suspicious-volume signals;
- relay snapshot age, clock drift, command backlog, rejection, and sync lag;
- object scan, render, import, export, and disposal queues;
- deployment version, migration/backfill state, and feature-flag exposure;
- registration lifecycle last success, duration, eligible candidate count,
  expiries, cancellations, promotions, and oldest overdue reservation age;
- registration capacity held, available, and waitlisted by opaque edition and
  product identifiers, without person-level metric labels;
- service-objective error budget and live-edition status.

Personal names, email addresses, handles, message text, case categories, room
numbers, file names, and query values are not metric labels.

The implemented outbox boundary renders stable Prometheus text for one explicit
organization and workload pool via `effects_metrics`. It includes message
status, attempt outcome, ready/expired-lease age, and replay count. A supervised
worker emits structured child outcome with opaque organization ID, workload
pool, and safe error code. Concrete thresholds and recovery steps live in the
[effect worker runbook](effects-worker-runbook.md).
Registration reservation and waiting-list recovery lives in the
[registration runbook](registration-runbook.md).

The implemented command:

```text
python src/manage.py registration_metrics \
  --organization ORGANIZATION_UUID \
  --edition EDITION_UUID
```

renders machine-readable, explicitly tenant/edition-scoped registration state,
oldest overdue reservation, capacity, payment exception, delivery failure,
pending media, guardian, privacy correction, restriction/appeal, offline
conflict, settlement, and lifecycle-heartbeat signals. It verifies that the
edition belongs to the supplied organization before inspection. Deployments
still have to scrape, retain, dashboard, and route alerts from this output.

Identity challenge delivery must expose run success/failure and age of the
oldest pending challenge. Payment webhooks expose signature rejection,
duplicate, exception kind, and intent age without provider payload or attendee
identity as metric labels. Closure readiness is a domain-health projection;
an approved gate does not suppress a non-zero live queue.

### Structured logs

Common fields:

```text
timestamp, level, service, release, environment, request/correlation/trace,
organization and edition opaque IDs, principal kind and opaque ID,
capability, route/command/event type, result/reason, duration, dependency,
retry/idempotency state, safe error code
```

Payloads use schema-controlled safe fields. Unexpected objects are not
stringified. Redaction is tested.

### Traces

Distributed trace context follows:

```text
client request -> command -> database/outbox -> worker -> connector
```

Trace attributes follow the same classification limits. Sampling retains
errors and slow paths without automatically retaining sensitive bodies.

### Domain health

Technical success is insufficient. Maru also measures:

- schedule release projected to each required surface;
- check-in and fulfilment reconciliation gaps;
- payment and refund discrepancies;
- payment intents stuck creating/uncertain, open webhook exceptions, and
  unreconciled settlement batches;
- permanent or aging registration notification delivery failures;
- pending or failed identity challenge delivery;
- pending guardian consent and moderated-media safety/review;
- open historical corrections, due retention work, and restriction appeals;
- expired access still observed in an external provider;
- unacknowledged urgent assignment or announcement;
- unowned blocking work and readiness evidence age;
- credential, asset, auction, and cash ledger imbalance;
- retention/deletion work overdue; and
- archive manifest completeness.

These signals link to authorized work queues, not public telemetry.

## Health endpoints

- **Liveness:** process can make progress; no dependency-heavy checks.
- **Readiness:** instance can safely receive the intended workload.
- **Dependency status:** authenticated operator view with latency, freshness,
  queue, circuit, and failure state.
- **Product status:** role-specific view of affected capability and alternative.

A healthy process can still deliver an unhealthy event workflow; domain health
must be visible separately.

The public `/health/ready` probe always performs a cheap database/catalog
check. Before the cutover tables exist, compatibility mode needs nothing more.
Once they exist, compatibility mode also proves exactly one generation-zero
latch and no marker; an active or malformed database cannot appear healthy
under a later `false` configuration. When the production recovery fence
`MARU_REQUIRE_EXACT_AUTHORITY_PROVENANCE=true` is selected, readiness instead
requires the exact ADR 0044 marker/latch contract. A dormant, missing,
malformed, or unreadable contract returns safe `503` dependency status without
contract, tenant, person, capability, database-version, or database error
details. The cheap public SQL gate is followed by the complete fingerprinted
runtime-contract verifier; a marker-shaped but weakened trigger/function
contract cannot pass. It then proves that `CURRENT_USER`, `SESSION_USER`, and
the current backend's `pg_stat_activity.usesysid` all identify
`MARU_RUNTIME_DATABASE_ROLE`; role or session-authorization impersonation does
not pass. The named login must have none of the forbidden attributes,
reserved/predefined or admin-option memberships, ownership, database/schema
creation, temporary-table, table-maintenance, parameter-control, persistent
non-origin trigger-setting, sequence-update, or object/column grant-option
paths. It also positively proves database connection, every user-schema usage
path, ordinary runtime relation DML, SELECT-only materialized-view and exact
marker/latch access with no table- or column-level `REFERENCES`, sequence
use/read, live
`session_replication_role=origin`, and the exact versioned v2 policy/trigger-
helper function closure. `PUBLIC` function execution or an extra/missing
runtime execute grant fails closed. The same minimized dependency fails closed
when any role proof fails, the server major is not the rehearsed PostgreSQL 17
contract, the effective schema order is not `pg_catalog, public, ...`, or the
exact rows cannot be read through their `public`-qualified relations. Public
health never reports the role name, membership, object, credential, or database
error that caused the denial.

The exact catalog gate also requires workforce
`0007_structure_write_integrity`. It fingerprints all 14 Page 9
`SECURITY DEFINER` trigger helpers and matches all 28 Page 9 trigger
attachments by table, function signature, event/row type, enabled state,
`UPDATE OF` columns, and deferred timing. A missing migration-recorder row,
altered helper definition, disabled/replaced trigger, changed update-column
set, or changed constraint timing makes readiness unavailable. These helpers
remain outside the 19-function runtime execute allowlist: they are callable
only through their pinned PostgreSQL triggers, with direct execution revoked
from both `PUBLIC` and the runtime login.

## Alert design

An alert has owner, severity, edition impact, symptom, threshold, evaluation
window, deduplication key, runbook, fallback, and clear condition.

| Severity | Meaning | Response |
| --- | --- | --- |
| SEV-0 | Immediate life-safety concern | use independent emergency procedure |
| SEV-1 | Live-essential function unavailable or integrity/security at material risk | page on-duty response and event command |
| SEV-2 | Important workflow impaired or objective rapidly burning | assigned rapid response |
| SEV-3 | Degraded planning workflow or actionable drift | business-hours or configured owner |
| SEV-4 | Trend, capacity, or cleanup signal | backlog and review |

Alerts describe user consequence: “check-in commands cannot synchronize,” not
“CPU is 83%.” Supporting technical signals are linked.

## Live event operations

### Technical readiness board

For each edition:

- declared event window and forecast;
- deployed release and configuration fingerprint;
- database, queue, object, identity, payment, mail, social, and relay status;
- capacity headroom and error budget;
- current changes and freezes;
- open high-risk vulnerabilities or accepted risks;
- backup/restore and relay drill date;
- staffing and escalation coverage; and
- fallback readiness.

### On-duty handover

The outgoing operator records:

- active incidents and user impact;
- unusual load or work queues;
- provider degradation;
- manual mitigations and their expiry;
- releases, flags, or configuration changes;
- pending reconciliations;
- important edition activity ahead; and
- custody of devices or privileged access.

The incoming operator acknowledges and validates the monitoring path.

## Incident response

```text
detect -> acknowledge -> declare -> assign roles -> contain
       -> communicate -> recover -> reconcile -> review -> improve
```

Roles:

- incident commander;
- technical lead;
- event operations liaison;
- communications lead;
- scribe/timeline owner;
- security/privacy/safety specialist where relevant; and
- provider liaison.

One person may hold several roles in a small incident, but command and hands-on
work should separate as soon as impact warrants.

### Required record

- start, detection, declaration, and recovery times;
- affected capabilities, editions, audiences, and data;
- current confidence and unknowns;
- decisions, actions, owners, and evidence;
- internal and public status messages;
- security/privacy assessment and notification decision;
- reconciliation completion;
- root and contributing conditions;
- what worked and failed;
- corrective work with owner and deadline; and
- review visibility and redaction.

The incident log is not the same as a restricted conduct, medical, or
safeguarding case.

## Operator tools

Authorized tools must support:

- correlation search using opaque identifiers;
- explainable authorization decision replay without protected content;
- domain event and outbox chain;
- job retry, cancel where safe, quarantine, and dead-letter inspection;
- connector disable, credential-health view, and reconciliation;
- payment exception resolution, settlement evidence, and dual-controlled
  cancellation/refund;
- registration lifecycle dry-run and scoped metrics;
- communication failure, media moderation, guardian, privacy, restriction,
  appeal, and offline conflict queues;
- closure-readiness counts, gate evidence, and manifest digest;
- release, migration, configuration, and flag history;
- user session and service-principal revocation;
- relay lease and device revocation;
- export/artifact invalidation;
- safe read-only database diagnostics; and
- evidence package for incident review.

No “god mode” UI silently bypasses policy. Exceptional infrastructure actions
use separate, short-lived, monitored access.

## Runbook standard

Every runbook states:

- symptom and alert;
- user/event consequence;
- safety boundary;
- decision owner and escalation;
- safe diagnostic steps;
- immediate containment;
- degraded or manual alternative;
- recovery steps and validation;
- reconciliation and data-integrity checks;
- communication template;
- evidence to preserve;
- security/privacy review trigger; and
- follow-up.

Runbooks are executable during a provider and Maru outage: essential copies
exist independently.

## Change and deploy observation

Every release annotates dashboards and service objectives. Automated
progressive checks compare:

- error and denial rates;
- latency and database load;
- outbox and connector lag;
- authentication and recovery;
- key domain invariants;
- relay compatibility;
- memory/CPU/restart and cost;
- client error and accessibility smoke tests.

A rollback decision considers database compatibility and accepted commands. If
rollback would lose or misinterpret work, the runbook uses a feature stop or
forward repair.

## Security monitoring

Signals include:

- credential stuffing and recovery abuse;
- MFA downgrade or unusual privileged session;
- grant expansion, break-glass, sensitive reads, and bulk exports;
- cross-tenant denial anomalies;
- emergency publication or schedule changes;
- integration installation, secret rotation, and webhook signature failures;
- device lease anomaly and offline replay;
- audit integrity checkpoint failure;
- unusual query, delivery, file, or cost volume; and
- retention job disablement or repeated failure.

Monitoring never assumes that high activity alone proves wrongdoing. Alerts
lead to proportionate human review.

## Operational readiness review

No edition enters Ready or Live solely because software tests passed. The joint
review verifies:

- accountable service and technical owners;
- authorization and access review;
- representative load, device, printer, and connector tests;
- current schedule, check-in, payment, communication, and fallback data;
- accessibility and safety coordination;
- restore and relay evidence;
- on-call and handover;
- provider limits and spending alerts;
- public support/status channels;
- reconciliation owners;
- open risks and accepted-risk authority; and
- explicit go/no-go decision.

Readiness expires when material configuration, release, venue, provider,
schedule, or staffing assumptions change.
