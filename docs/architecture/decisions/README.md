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
| [0006](0006-react-typescript-staff-console.md) | Partially superseded | React and TypeScript for the API-backed operations frontend; ADR 0023 unifies the visible management experience |
| [0007](0007-copy-on-write-registration-configuration.md) | Accepted | Copy-on-write registration configuration and templates |
| [0008](0008-persistent-edition-working-context.md) | Partially superseded | Persistent edition working context; ADR 0023 replaces the workspace-less staff redirect |
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
| [0019](0019-staff-assisted-registration-and-workforce-onboarding.md) | Partially superseded | Staff-assisted registration and workforce onboarding remain; ADR 0031 removes convention relationships from the platform bootstrap controller |
| [0020](0020-guided-bootstrap-and-localized-data-entry.md) | Partially superseded | Organizer/series identity, locale entry, draft removal, and staff account creation remain; later ADRs replace the web adapter and controller participation |
| [0021](0021-platform-brand-and-legacy-reference.md) | Accepted | Accessible platform brand and behavior-only use of the legacy Maru prototype |
| [0022](0022-ordered-admin-quick-start.md) | Superseded | Ordered global Quick Start; ADR 0024 replaces its command-only first-authority experience and ADR 0027 moves guidance out of global chrome |
| [0023](0023-unified-management-console-and-access-sharing.md) | Partially superseded | Contextual role sharing and a forms hub remain; ADR 0026 replaces its React shell and route placement |
| [0024](0024-guarded-first-authority-and-lifecycle-console.md) | Partially superseded | The guarded ceremony and lifecycle controls remain; ADR 0031 removes convention relationships from its platform controller |
| [0025](0025-single-admin-namespace.md) | Superseded | React-at-`/admin/` route placement and compatibility redirects, replaced by ADR 0026 |
| [0026](0026-original-admin-shell-with-embedded-workflows.md) | Accepted | Original `/admin/` shell and menu with embedded API-backed workflows and no standalone management routes |
| [0027](0027-record-oriented-convention-work.md) | Accepted | Record-oriented embedded workflows and contextual Setup guide without global Quick Start |
| [0028](0028-login-handles-and-workforce-structure.md) | Accepted | Human login handles, local public-roster boundary, and minimized workforce hierarchy |
| [0029](0029-append-only-registration-profile-extensions.md) | Accepted | Versioned profile-extension fields with append-only permission-aware values |
| [0030](0030-controlled-empty-experience-rebuild.md) | Accepted | Default two-page browser baseline with preserved backend/API foundation and page-by-page reintroduction |
| [0031](0031-non-participating-platform-administration.md) | Accepted | Explicit non-participating platform administrator and read-only organization inventory |
| [0032](0032-minimal-draft-organization-creation.md) | Partially superseded | Name-only audited Draft creation remains; ADR 0033 expands the optional profile and navigation |
| [0033](0033-complete-organization-creation-and-platform-navigation.md) | Partially superseded | Complete optional organization profile remains; ADR 0034 compacts its navigation and restores editing |
| [0034](0034-organization-record-management.md) | Accepted | Purpose-built organization editing, compact navigation, and protected empty-Draft deletion |

New ADRs use the next four-digit number and contain:

- status and date;
- context;
- decision;
- consequences;
- alternatives considered;
- requirements affected.

An accepted ADR is not edited to make a later decision appear original.
Supersede it with a new ADR and update this index.
