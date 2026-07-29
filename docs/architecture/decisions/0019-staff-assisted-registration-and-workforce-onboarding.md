# ADR 0019: Staff-assisted registration and workforce onboarding

- Status: Accepted
- Date: 2026-07-29
- Requirements: IDN-002 through IDN-005, AUD-001 through AUD-003, HR-001,
  HR-002, HR-004 through HR-008, REG-002, REG-006, REG-008, REG-013,
  REG-017, REG-021, UX-001, UX-006, PRI-001, NFR-001 through NFR-003

## Context

A clean organizer must be able to nominate its first convention chair before
ordinary scoped authority exists. Registration staff sometimes need to admit a
known person outside the public registration window while preserving payment,
capacity, policy, and historical truth. A person becoming a volunteer may then
need to submit a signed agreement and join an edition position whose hierarchy
and privileges are authoritative.

Direct Django-admin inserts would create a second registration lifecycle,
publish unreviewed files, and let a role label masquerade as access. Treating an
uploaded NDA as a generic registration answer would mix HR evidence into the
attendee profile and immutable public-registration schema.

## Decision

### Initial organizer authority

Provide one trust-on-first-use operator command for an organization that has no
existing authority records. It requires:

- one existing active Django superuser as bootstrap controller;
- one distinct active account as convention chair;
- an active organization and matching non-archived edition;
- an exact organization confirmation and a recorded reason; and
- an empty organization authority boundary.

The command installs versioned starter role/position templates, creates the
minimum organization/edition relationships, and records the initial controller
and chair assignments. It is one-shot. Later role changes use ordinary
dual-control authorization; the bootstrap command cannot repair or broaden an
already governed organization.

### Staff-assisted registration

Staff-on-behalf is an explicit edition command with separate actor and subject.
It may ignore only the public configuration and product sale windows. It still:

- uses the active frozen configuration and exact selected product;
- validates answers, age policy, restrictions, product eligibility, capacity,
  price, currency, and duplicate registration;
- creates the normal participation, registration, submission, deadline,
  timeline, audit, and domain event;
- records the staff source and reason;
- creates a private incomplete edition profile for the subject to finish; and
- leaves a paid product in `payment_pending`.

It cannot treat a browser return, staff claim, or registration creation as
payment. Local rehearsal may still use the existing non-production demo
payment adapter; production uses authenticated provider evidence.

### Workforce structure and applications

`maru.workforce` owns edition departments, positions, public volunteer
opportunities, applications, onboarding document requirements, and position
assignments.

- Position templates are organization-owned and versioned; positions are
  edition-owned copies with a title, department, headcount, optional reporting
  position, required document types, capacity labels, and one exact immutable
  authorization role version.
- Every position has one application opportunity. Publication remains visible
  after headcount is filled by default, but the public projection states that
  applications are closed because the position is filled. Organizers may
  explicitly close or withdraw publication.
- Several people may hold one position up to its headcount. Reporting links
  cannot cross edition scope or form a cycle.
- Applications are attendee-authored expressions of interest, never automatic
  selection or access.

### Reviewed onboarding documents

Agreement types are versioned within one organization/edition. A named document
request is separate from the registration profile and application answer.

- The attendee may upload only to their own active request.
- The delivered slice accepts PDF evidence with bounded size, file-signature
  validation, a SHA-256 receipt, and the configured malware scanner.
- Source files remain private behind an owner-or-authorized-reviewer download
  command with sensitive-read audit.
- Human approval or rejection requires a reason. “Approved” records review
  evidence; it does not claim cryptographic signature validation.
- Replacing a rejected file returns it to pending review.

Local development may opt into an explicitly labelled debug-only clean scanner
so the workflow can be rehearsed without ClamAV. Production continues to fail
closed unless the approved scanner is configured.

### Assignment and access

Activating a position assignment requires:

- available headcount;
- every position document requirement approved for the same account and
  edition;
- two distinct active controllers with both workforce-assignment and
  authorization-role authority;
- one exact role-bundle version and bounded effective dates; and
- a recorded reason.

Activation creates the ordinary role assignment through the authorization
command, plus the participation capacity used by people/history projections.
Removing or expiring a position must reconcile both authority and capacity;
ordinary model editing cannot manufacture access.

## Consequences

The requested clean-database rehearsal becomes possible without a demo fixture,
while registration and privileges keep one source of truth. Position names,
headcount, applications, agreements, and authorization no longer collapse into
one editable role label.

The first-authority command is intentionally exceptional and must be protected
like a deployment credential. Signed PDF review is document evidence, not a
full electronic-signature service. The first slice does not yet implement
interviews, scheduling, qualification matching, automatic reminders, or
offboarding reconciliation beyond explicit assignment end/revocation.

## Alternatives considered

- Let a Django superuser add role assignments directly: rejected because it
  bypasses immutable role versions, dual control, audit, and scope validation.
- Add a hidden “registration open” bypass: rejected because it would also risk
  bypassing product, capacity, payment, and policy rules.
- Put NDAs in registration answers or public-profile media: rejected because
  purpose, sensitivity, review, retention, and access differ.
- Hide filled positions automatically: rejected because applicants and future
  volunteers still need to understand the convention structure and whether a
  role is currently accepting applications.
- Grant capabilities directly from an editable position title: rejected
  because access must reference an immutable authorization role version.
