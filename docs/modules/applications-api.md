# Applications API contract

Status: mounted versioned adapter contract
Last updated: 2026-08-09

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
