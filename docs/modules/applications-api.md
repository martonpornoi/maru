# Applications API contract

The dormant [named-reviewer management forms](../product/page-contracts/programme-review-management.md)
reserve `cases/`, `cases/{case_id}/`, `cases/{case_id}/assign/` and
`cases/{case_id}/assignments/{assignment_id}/remove/` beneath the exact Department
review root. They are not mounted production or generic REST endpoints. Every
request requires `applications.manage_programme_review` with only `review_context`;
setup links independently require `review_setup`. GET is read-only. Closed POST
actions preview one known email, confirm one signed original person selection,
or remove one URL-bound assignment. Final changes require original strict case
version, retry UUID, bounded reason and explicit confirmation, using unchanged
`REVIEWER_ASSIGNED`/`REVIEWER_REMOVED` owner commands. Unknown/duplicate inputs and
files fail closed. Conflict/service failures preserve intent when fresh reads
remain safe; read/audit failure releases no cached roster or selected-person label.
No invitation, permission grant, new schema or JSON adapter is added.

Status: mounted versioned adapter contract
Last updated: 2026-09-14

All routes are organization- and edition-explicit. They require an active Maru
person session, reject query parameters and unknown JSON fields, and authorize
inside the shared command or query service. A route identifier from another
tenant or edition is handled through the same non-disclosing unavailable
boundary as a missing identifier.

Every mutation requires one canonical lower-case UUID in the
`Idempotency-Key` header. Versioned mutations also require the current positive
`expected_version`. A same-key, same-intent retry returns the original receipt
with `Idempotent-Replay: true`; a changed intent or stale aggregate version
returns a conflict without applying a partial write.

## Dormant Programme boundary

The dormant Programme milestones add no production route or API operation. Applications-owned Programme calls,
proposal collaborators, shared answers, contributor profiles, exact sealed
revisions, acknowledgements, reopening, submission, and withdrawal remain a
dormant command/query kernel. Preview-first import, Department ownership
transitions, the retirement dependency seam, and exact-ID orphan recovery are
also excluded from the generic API. They have no serializer, OpenAPI component,
schema operation, mounted browser view or Django admin writer. The separate
guided call workspace has reserved, unmounted HTML routes and templates for
manager inventory, creation/composition, exact-authority Department selection
and confirmed Draft ownership transfer. See its
[page contract](../product/page-contracts/programme-call-workspace.md); these
adapters do not make Programme available through the mounted API below.
The [personal intake companion](../product/page-contracts/programme-proposal-workspace.md)
likewise reserves unmounted HTML routes for own inventory, available calls,
private draft creation, role-bounded overview and separate exact-proposal personal
editing, collaboration, sealing, acknowledgement, submission and withdrawal tasks.
These HTML adapters add no API operation or generic Programme discriminator access.
Read and mutation authority remain independent; original version and exact seal/
subject-profile proof fields are not accepted through the mounted API below.
The new `workflow_context` and `frozen_revision` self-view fields are dedicated
owner-query contracts, not new mounted API fields or grants. The former is
role-minimized existing-proposal context; the latter projects exact sealed shared
content and only the current actor's included frozen profile. Generic API
serializers/discriminator exclusions remain unchanged.

The [personal decision receipt companion](../product/page-contracts/programme-decision-receipts.md)
reserves `/my/applications/programme/{organization_id}/{edition_id}/decisions/`
and its exact `{decision_id}/` detail/POST route. It admits independently
authorized exact-recipient history and deliberate own receipt only. The
original optimistic proof belongs to the review case, not the proposal.
`get_self_programme_decision` is a protected owner query, not a mounted API
operation. No generic review, decision, target or profile exclusion changes.

The [review setup companion](../product/page-contracts/programme-review-setup.md)
reserves `/admin/applications/programme-review/{organization_id}/{edition_id}/{department_id}/`,
its `{call_id}/` composer and `{call_id}/policies/{version}/` immutable history.
That history's `cases/` chooser and `cases/{revision_id}/` confirmation pin one
policy and exact seal without UUID discovery or proposal-content access.
Its `review_setup` manager field, configuration and two case-intake owner queries
are not mounted API operations. Proposed form state is closed, bounded and non-authoritative;
only final confirmation calls the existing review writer. The optional exact
seal in `CASE_OPENED.reference_id` is an owner-command contract, not a generic
API field. Legacy absent-reference retry shapes remain compatible. No OpenAPI,
serializer, generic discriminator or production profile is widened.

The routes below omit Programme definitions from starter and definition
discovery and deny Programme submissions in generic applicant, answer, submit,
review, decision, acceptance, target-record, and target-result paths. The
reserved `programme_item` target kind is not a usable generic adapter. A later
surface must expose the exact lead/collaborator/profile/seal authorization
contract deliberately; it cannot inherit these mounted endpoints by changing
only a discriminator.

Structured review and decisions are the immediate successors. The typed
accepted Programme adapter, Programme items and host relationships,
publication, scheduling, and staffing remain outside this API contract. The
existing Organization-structure retirement API may return only its generic
`409 structure_department_has_dependencies` or `503 service_unavailable`
envelope; it does not expose whether a call, import batch, or another protected
dependency caused the result.

```text
GET      /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/starters
GET|POST /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/definitions
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/definitions/{definition_id}/commands
GET      /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/me
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/definitions/{definition_id}/submissions
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/submissions/{submission_id}/answers
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/submissions/{submission_id}/submit
GET      /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/review-queue
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/applications/submissions/{submission_id}/review-decisions
```

The definition command body uses one closed `operation` discriminator:
`definition.configure`, `section.add`, `question.add`,
`definition.activate`, `definition.retire`, or `definition.successor`.
Organizer responses expose exact owner Departments, immutable reviewer-role
versions, optional named reviewers, policy codes, provenance, and schema.
Starter creation copies catalog content into independent organizer-owned rows;
the response contains a receipt and target identifiers, never a live catalog
binding.

The self workspace returns only currently eligible active definitions and the
authenticated person's submissions. Applicant definitions omit staff-only
policy and field metadata. Answer requests name one canonical question UUID,
the expected submission version, and one typed JSON value; successful writes
append a revision rather than updating an answer row.

The review queue requires both current review capability and an exact named or
immutable-role assignment. Sensitive queues additionally require the
non-delegable sensitive-review capability. Reviewer answer projection includes
only fields marked both staff-visible and reviewer-visible. Decisions are
closed to `start_review`, `request_changes`, `accept`, and `reject`; an accepted
result returns the immutable typed target receipt when the configured adapter
performs that transition.

Read adapters append minimized sensitive-read audit evidence. Successful
mutations atomically append command receipt, audit, domain-event, outbox, and
aggregate evidence. Error responses do not reveal foreign edition, definition,
submission, reviewer-assignment, or answer details.
