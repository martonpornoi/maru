# Privacy operations module

Status: Subject requests, exports, corrections, minimization, and receipts implemented  
Last updated: 2026-07-28

## Purpose and requirements

`maru.privacyops` implements the operational core of PRI-001 through PRI-009,
ARC-003, ARC-005, REG-015, and REG-019. It coordinates approved actions through
public services from owning modules; it does not import their private
implementation or claim to replace legal review.

## Owned data

- `SubjectRightsRequest` tracks access, correction, portability, restriction,
  objection, and deletion requests by account and controller scope.
- `PostEditionCorrection` stores a proposed patch, reason, requester,
  independent decision, and application evidence.
- `RetentionPolicy` records purpose category, jurisdiction, version,
  disposition, duration, approval evidence, and activation.
- `DisposalReceipt` records what was minimized or disposed, the policy used,
  safe result, and downstream reference.

The attendee can export their minimized Maru data and submit a request or
post-edition correction. Organization privacy staff see only requests assigned
to their controller, transition them through documented states, independently
decide historical profile corrections, and invoke profile minimization against
an active policy.

## Contracts

```text
GET|POST /api/v1/me/privacy-requests
GET      /api/v1/me/privacy-export
GET|POST /api/v1/me/post-edition-corrections
GET      /api/v1/organizations/{organization_id}/privacy-requests
POST     /api/v1/organizations/{organization_id}/privacy-requests/{request_id}/transition
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/privacy/corrections/{correction_id}/decision
POST     /api/v1/organizations/{organization_id}/editions/{edition_id}/privacy/registration-profile-minimization
```

Current-edition profile editing remains in registration and never rewrites the
submission. Historical correction accepts only a closed safe field set.
Minimization preserves account linkage, registration/finance truth, immutable
audit, and evidence required by another lawful purpose. Media deletion checks
for remaining references first.

## Authorization, operation, and limits

Self routes are relationship scoped. Staff list, decision, transition, and
minimization routes require the corresponding organization/edition privacy
capability and are audited. Retention policy records and disposal receipts are
read-only in bootstrap administration.

Proposed corrections and due disposal work block closure. Automated tests cover
self isolation, controller isolation, export minimization, state transitions,
independent correction review, policy matching, disposal receipts, and
cross-tenant denial.

Production still needs an approved controller register, jurisdiction-specific
policy versions, retention-policy provisioning with independent approval,
storage-provider deletion adapters, response-time ownership, and legal/privacy
sign-off. Platform-global requests require a platform privacy workflow rather
than being exposed to one organizer.
