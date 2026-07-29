# Architecture decision records

ADRs preserve decisions that future maintainers must understand before changing
the system.

| ADR | Status | Decision |
| --- | --- | --- |
| [0001](0001-python-django-modular-monolith.md) | Accepted | Python, Django, PostgreSQL, modular monolith |
| [0002](0002-multi-convention-event-history.md) | Accepted | Multi-tenant event editions with durable history |
| [0003](0003-capability-and-scope-authorization.md) | Accepted | Capability, scope, relationship, and field authorization |
| [0004](0004-bounded-offline-relay.md) | Accepted | Bounded offline relay for venue-critical workflows |
| [0005](0005-transactional-outbox.md) | Accepted | Transactional outbox and idempotent asynchronous work |
| [0006](0006-react-typescript-staff-console.md) | Accepted | React and TypeScript for the separate Staff Console |
| [0007](0007-copy-on-write-registration-configuration.md) | Accepted | Copy-on-write registration configuration and templates |
| [0008](0008-persistent-edition-working-context.md) | Accepted | Persistent edition working context across staff and bootstrap administration |
| [0009](0009-public-registration-and-edition-profile.md) | Accepted | Public registration and purpose-partitioned edition profiles |
| [0010](0010-headless-registration-and-reference-client.md) | Accepted | Headless registration contract and neutral reference client |
| [0011](0011-registration-offers-reservations-and-waitlists.md) | Accepted | Phased offers, payment reservations, waitlists, and controlled exceptions |
| [0012](0012-profile-suggestions-and-moderated-public-attendance.md) | Accepted | Edition profile suggestions, multiple fursuits, moderated reusable media, and public attendance |
| [0013](0013-identity-assurance-and-scoped-restrictions.md) | Accepted | Verified identity lifecycle, session controls, privileged step-up, and scoped appealable restrictions |
| [0014](0014-hosted-payments-and-operational-finance.md) | Accepted | Provider-hosted payment boundary, authenticated reconciliation, and append-only operational finance |
| [0015](0015-canonical-service-notifications.md) | Accepted | Canonical inbox messages with optional idempotent email delivery and failure queues |
| [0016](0016-minors-media-and-privacy-operations.md) | Accepted | Versioned minor policy, safe media pipeline, and evidence-bearing privacy operations |
| [0017](0017-credentials-offline-check-in-and-closure.md) | Accepted | Revocable credentials, signed bounded offline check-in, and gated edition closure |
| [0018](0018-attendee-directory-labels-and-reporting-preset.md) | Accepted | Separately consented public country, authoritative attendee labels, and minimized badge reporting |
| [0019](0019-staff-assisted-registration-and-workforce-onboarding.md) | Accepted | Clean organizer bootstrap, staff-assisted registration, reviewed onboarding documents, and position-driven access |
| [0020](0020-guided-bootstrap-and-localized-data-entry.md) | Accepted | Guided first-authority setup, organizer/series identity, code-backed locale entry, draft removal, and explicit staff account creation |
| [0021](0021-platform-brand-and-legacy-reference.md) | Accepted | Accessible platform brand and behavior-only use of the legacy Maru prototype |

New ADRs use the next four-digit number and contain:

- status and date;
- context;
- decision;
- consequences;
- alternatives considered;
- requirements affected.

An accepted ADR is not edited to make a later decision appear original.
Supersede it with a new ADR and update this index.
