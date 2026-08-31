# Applications module

Status: typed form studio, applicant workspace, review queues, and closed
target-transition receipts accepted in the canonical current tree; production
remains gated
Last updated: 2026-08-31

## Purpose and boundary

`maru.applications` implements REG-023 and a bounded intake/review slice of
KNO-009. It owns edition-scoped, versioned contribution and service
applications built from one typed field vocabulary. Attendee registration
remains owned by `maru.registration`; the Registration starter is a
navigation/catalog entry and cannot be copied into this module. An application
never creates a second registration or grants a ticket, payment state,
convention role, or access. Configurable staff answer-correction windows,
public answer renditions, retention execution, and real downstream target
adapters remain outside this slice.

ADR 0081 preserves this ownership for the accepted but not yet executable
`programme_operations@1` profile. Applications will own programme calls,
proposal collaborators, private answers, immutable revisions, reviewer
assignments and conflicts, review evidence, decisions, and the idempotent typed
target receipt. A Programme adapter may consume only that explicit accepted
transition to create or reconcile a private Programme item. It must not copy
the answer sheet into Programme, make private review material public, grant a
host broader convention access, or create attendee Participation. The host-
panel starter and adapter remain successor runtime work.

ADR 0047's governed-writer rules apply: route scope is untrusted, commands use
closed inputs and expected versions, API retries use canonical UUID keys, and
successful mutations commit minimized audit, domain-event, and outbox evidence
in the state transaction.

## Definition lifecycle and starter catalog

An `ApplicationDefinition` is owned by one organization and edition and has a
stable code plus an immutable schema version. Its lifecycle is:

```text
draft -> active -> retired
          |
          +-> explicit copy-on-write successor draft
```

Drafts may change sections, questions, owner Departments, assigned reviewer
role versions, and optional named reviewers. Activation requires a complete
owner/reviewer/question graph. Active definitions and their child rows are
immutable; retirement changes lifecycle evidence only. A successor copies the
schema and assignments into a new independent draft.

The code-owned catalog contains one external Registration entry plus the ten
application-owned starters below. Only the application-owned starters can be
copied, and copies are never shared mutable templates:

| Starter | Target adapter |
| --- | --- |
| T-shirt and merchandise submission | `merch_submission` |
| DJ application | `dj_set` |
| Fursuit Dance Competition | `fursuit_dance_competition` |
| Maid Cafe | `maid_cafe` |
| Adult Fursuit Striptease | `adult_fursuit_striptease` |
| Volunteer application | `volunteer` |
| Feedback | `feedback` |
| Idea submission | `idea` |
| SecOps damage report | `damage_report` |
| Time-bounded helper | `helper` |

The helper starter sources the account display name and registration Telegram
contact through explicit read adapters and collects an explicit availability
interval. Source-bound questions are applicant-visible but not
applicant-writable.

## Shared field contract

Sections contain ordered questions using a closed vocabulary: short and long
text, integer, decimal, boolean, single and multiple choice, date, time,
instant, email, phone, URL, address, person reference, domain reference, and a
safety-checked file receipt. Each question records:

- stable key, label, help, purpose, and classification;
- required and closed conditional-display rules;
- length, numeric, option, choice-count, and reference constraints;
- applicant/staff/reviewer visibility and writer policy;
- public-after-approval and API-projection policy; and
- field or definition retention policy.

Question classification cannot exceed definition classification at
activation. Only separately reviewed C1 renditions may be marked public.
Safety-checked files reference an immutable clean scanner receipt; arbitrary
paths, unscanned uploads, and client-declared scan status are rejected.

## Applications, revisions, and review

Eligible people create bounded ordinal drafts during the configured window.
Eligibility is closed to authenticated people, edition participants,
registered attendees, confirmed attendees, or active volunteers. Cardinality
and applicant edit deadlines are enforced server-side.

Answers are append-only `ApplicationAnswerRevision` rows. Every revision keeps
the question identifier, stable key/type/classification snapshots, sequence,
normalized value, source, actor, and time. Applicant, authoritative source,
and future reasoned staff-correction provenance are distinct. Current answers
are a projection over revisions, not a mutable response row.

Review queues combine an exact immutable `RoleBundle` version with optional
named people. A reviewer must have the current review capability and match the
definition's assigned queue. Sensitive definitions additionally require
`applications.review_sensitive`. Review decisions are append-only, reasoned,
sequenced, and retain whether authority came from the exact role version or a
named-person assignment.

Acceptance creates one immutable `ApplicationTargetRecord` whose adapter kind
must equal the definition's closed adapter discriminator. It is transition
evidence for the target-domain adapter, not a generic answer sheet. Downstream
typed modules consume that explicit adapter transition; they do not treat the
application answer projection as their source of truth.

## Sensitive policy fence

C3/C4 definitions and the adult and damage-case adapters cannot activate with
blank or `default`, `generic`, or `standard` policy codes. They require an
edition-approved audience and retention policy. The adult adapter also
requires minimum age 18 and an explicit age-policy version. Python validation
and PostgreSQL triggers enforce the same fence. Sensitive review requires the
non-delegable sensitive-review capability.

## Authorization

The catalog entries are:

- `applications.manage_definitions` at exact edition scope;
- `applications.review` for assigned C1/C2 queues;
- `applications.review_sensitive` for assigned C3/C4/adult/case queues;
- non-persistable `applications.view_self`; and
- non-persistable `applications.apply_self`.

Self capabilities resolve against the authenticated account and exact edition,
not a client-supplied subject. Organizer, applicant, and reviewer queries scope
every lookup by organization and edition. Applicant projections release only
applicant-visible answers; reviewer projections require both staff-visible and
reviewer-visible policy. Protected self and review reads append minimized
sensitive-read audit evidence before response release.

## HTTP contracts

The same Django admin shell now exposes executable organizer, applicant, and
reviewer journeys rather than read-only projections. Each view builds from
`admin.site.each_context(request)`, so navigation, pinned destinations, and the
shared Access explanation remain consistent. Applicant pages set the personal
surface flag and never inherit selected-edition staff navigation.

Personal discovery does not require an admin edition context. It bounds
distinct edition candidates before evaluating eligibility, shows only editions
where the person has an available definition or their own submission, and then
links to the exact-edition workspace:

```text
GET  /my/applications/
GET /my/organizations/{organization_id}/editions/{edition_id}/applications/
POST /my/organizations/{organization_id}/editions/{edition_id}/applications/definitions/{definition_id}/start/
GET  /my/organizations/{organization_id}/editions/{edition_id}/applications/submissions/{submission_id}/
POST /my/organizations/{organization_id}/editions/{edition_id}/applications/submissions/{submission_id}/answers/
POST /my/organizations/{organization_id}/editions/{edition_id}/applications/submissions/{submission_id}/submit/
```

Organizer pages copy a code-owned, non-external starter into an independent
draft; configure its purpose, classification, eligibility, window,
cardinality, policy, exact owner Departments, immutable reviewer role versions,
and optional exact named reviewers; add sections and questions; and activate,
retire, or create a copy-on-write successor:

```text
GET /admin/organizations/{organization_id}/editions/{edition_id}/applications/
GET|POST /admin/organizations/{organization_id}/editions/{edition_id}/applications/starters/{starter_code}/copy[/submit]/
GET      /admin/organizations/{organization_id}/editions/{edition_id}/applications/definitions/{definition_id}/
POST     /admin/organizations/{organization_id}/editions/{edition_id}/applications/definitions/{definition_id}/{configure|sections|questions|activate|retire|successor}/
GET /admin/organizations/{organization_id}/editions/{edition_id}/applications/review/
GET  /admin/organizations/{organization_id}/editions/{edition_id}/applications/review/{submission_id}/
POST /admin/organizations/{organization_id}/editions/{edition_id}/applications/review/{submission_id}/decisions/
```

Definition-window `datetime-local` values are interpreted only in the
persisted edition IANA time zone. Ambiguous fall-back and nonexistent
spring-forward wall times are rejected. Command versions, cardinalities, age,
length, and choice constraints require canonical base-10 integers; duplicate,
unknown, and alternate transport spellings are rejected. Applicant answer
fields remain typed according to the question definition. Every HTML mutation
uses the same idempotent command service as the v1 adapter, ignores preview
state, and returns safe validation or stale-version errors without disclosing a
foreign object.

The strict JSON API contract is documented separately in
[`applications-api.md`](applications-api.md).

```text
GET|POST /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/definitions
GET      /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/starters
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/definitions/{definition_id}/commands
GET      /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/me
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/definitions/{definition_id}/submissions
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/submissions/{submission_id}/answers
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/submissions/{submission_id}/submit
GET      /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/review-queue
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/submissions/{submission_id}/review-decisions
```

Definition commands use the closed `operation` discriminator. Every mutation
requires a canonical `Idempotency-Key`; same-key/same-intent requests replay
the original receipt and changed intent conflicts. Unknown query or JSON
fields, client-owned scope, lifecycle evidence, and result fields are rejected.

## Evidence, migrations, and recovery

Each successful mutation appends an immutable command receipt, `allow` audit
event, minimized `applications.definition.changed.v1` or
`applications.submission.changed.v1` event, and transactional outbox message.
Event envelopes contain lifecycle/adapter facts only and never answers,
contact information, reviewer reasons, or question text.

Migration `0001` creates the bounded schema. Migration `0002` installs tenant,
definition-lifecycle, activation-graph, append-only revision, contiguous review
history, exact queue-basis, IDN-011 subject, and typed-target triggers. Terminal
Applications migration `0003_integrity_function_execute_boundary` revokes the
default `PUBLIC EXECUTE` privilege from all seven Applications integrity
functions, leaving function `EXECUTE` owner-only. The functions still run
through their installed triggers for permitted table DML, but the production
runtime role receives no direct `EXECUTE` privilege. Readiness requires both
integrity migrations and proves the functions' exact owner-only ACL. Reversing
`0003` restores the prior `PUBLIC EXECUTE` behavior and therefore makes
readiness fail closed. Reversing `0002` removes triggers and functions but does
not delete domain data. A deployment must review retained applications before
reversing the app migrations; ordinary application deletion is intentionally
blocked pending a governed retention workflow.

Focused verification covers the closed starter/event/capability catalogs and
PostgreSQL workflows for policy activation, idempotency, applicant/reviewer
visibility, exact role attribution, acceptance transition, audit/outbox
evidence, append-only enforcement, and tenant isolation.

The final canonical current-tree repository gate passed all 4,067 tests in
15,558.23 seconds (4:19:18) at 90.78 percent coverage. This accepts the bounded
Applications module in the repository; it is not production deployment,
retention execution, or acceptance of the still-missing downstream typed
adapters and broader KNO-009 workflow.
