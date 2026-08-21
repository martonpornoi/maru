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
| [0024](0024-guarded-first-authority-and-lifecycle-console.md) | Partially superseded | Edition lifecycle controls remain; ADR 0031 removes convention relationships from its platform controller and ADR 0040 replaces the broad ceremony as the normal first-authority path |
| [0025](0025-single-admin-namespace.md) | Superseded | React-at-`/admin/` route placement and compatibility redirects, replaced by ADR 0026 |
| [0026](0026-original-admin-shell-with-embedded-workflows.md) | Accepted | Original `/admin/` shell and menu with embedded API-backed workflows; ADR 0039 selects this unified grammar with reserved platform routes |
| [0027](0027-record-oriented-convention-work.md) | Accepted | Record-oriented embedded workflows and contextual Setup guide without global Quick Start; retained by ADR 0039 |
| [0028](0028-login-handles-and-workforce-structure.md) | Accepted | Human login handles, local public-roster boundary, and minimized workforce hierarchy |
| [0029](0029-append-only-registration-profile-extensions.md) | Accepted | Versioned profile-extension fields with append-only permission-aware values |
| [0030](0030-controlled-empty-experience-rebuild.md) | Partially superseded | Empty-experience preservation and page-contract discipline remain; ADR 0039 replaces its default URL configuration and minimal shell |
| [0031](0031-non-participating-platform-administration.md) | Accepted | Explicit non-participating platform administrator and read-only organization inventory |
| [0032](0032-minimal-draft-organization-creation.md) | Partially superseded | Name-only audited Draft creation remains; ADR 0033 expands the optional profile and navigation |
| [0033](0033-complete-organization-creation-and-platform-navigation.md) | Partially superseded | Complete optional organization profile remains; ADR 0034 compacts its navigation and restores editing |
| [0034](0034-organization-record-management.md) | Partially superseded | Purpose-built organization editing and protected empty-Draft deletion remain; ADR 0036 expands its compact navigation |
| [0035](0035-organization-scoped-series-creation.md) | Partially superseded | Organization-scoped creation remains; ADR 0036 adds a scoped Series menu destination without making it global |
| [0036](0036-progressive-context-scoped-administration-navigation.md) | Accepted | Progressive global and selected-organization navigation aligned to the viewport edge |
| [0037](0037-executable-journey-production-consolidation.md) | Accepted | Consolidate the retained domain kernel through executable convention journeys in one management shell; ADR 0039 selects its unified route and visual grammar |
| [0038](0038-stage-governance-after-edition-spine.md) | Accepted | Stage governance and computed scoped access after the edition workspace record spine |
| [0039](0039-unified-admin-shell-and-platform-route-space.md) | Accepted | Use the original unified `/admin/` shell grammar and reserve `/admin/platform/` for Pages 1 through 7 |
| [0040](0040-explicit-executive-board-representation-lifecycle.md) | Accepted | Establish first organization authority through exact Executive Board invitations, self-acceptance, two-person cross-approval, and atomic Draft-to-Active activation |
| [0041](0041-exact-department-and-typed-resource-authorization-scope.md) | Accepted | Add exact department and typed-resource scope with trusted resolved targets and no implicit department-tree inheritance |
| [0042](0042-synthetic-only-educational-fixtures.md) | Accepted | Retire live public-roster rehearsal imports and require deterministic synthetic people for fixtures, tests, and tutorials |
| [0043](0043-global-emergency-executive-board-controller-containment.md) | Accepted | Contain a compromised controller across every organization, suspend Boards that lose quorum, and deactivate the global account atomically |
| [0044](0044-exact-authority-issuance-provenance.md) | Accepted | Pin immutable actor and approver authority sources, propagate controller loss, and preserve a non-cyclic initial Executive Board root |
| [0045](0045-governance-anchored-copy-on-write-edition-structure.md) | Accepted | Present organization governance above an edition-owned, copy-on-write, versioned and safely editable workforce Department tree |
| [0046](0046-nondelegable-runtime-database-login.md) | Accepted | Require a genuine non-delegable PostgreSQL runtime login, select-only cutover controls, and trigger-integrity ACL proof |
| [0047](0047-governed-registration-setup-and-platform-account-invitations.md) | Accepted | Govern Page 10 registration setup and optional recipient-owned platform account invitations through strict shared commands and staged direct-writer retirement |
| [0048](0048-automatic-browser-department-ordering.md) | Accepted | Keep Department sibling order automatic in the browser while preserving explicit bounded API ordering |
| [0049](0049-coherent-navigation-personal-surface-and-access-preview.md) | Accepted | Flatten selected-edition navigation, add one searchable/pinnable registry and My Maru, and provide capped read-only access preview |
| [0050](0050-governed-admission-upgrades-capacity-and-edition-commerce.md) | Accepted | Use held exact-delta admission replacements, append-only bounded capacity, strict FIFO offers, and a separate edition catalog |
| [0051](0051-typed-applications-and-policy-governed-profile-extensions.md) | Accepted | Copy immutable starters into owned drafts, use closed profile audiences, and keep contribution forms in typed application workflows |
| [0052](0052-governed-charity-partners-and-edition-publication.md) | Accepted | Keep reusable charity partners separate from tenants and govern each edition decision and public snapshot independently |
| [0053](0053-reusable-venue-catalog-and-physical-space-occupancy.md) | Accepted | Reuse governed venue facts through edition selections and enforce physical occupancy with turnover-safe interval constraints |
| [0054](0054-event-sourced-logistics-containment-and-custody.md) | Accepted | Track physical containment and custody through typed acyclic nodes, append-only movements, manifests, and bounded offline reconciliation |
| [0055](0055-task-oriented-responsive-management-experience.md) | Accepted | Present task-oriented management navigation, an accessible intermediate-width drawer, and a coherent person-account to governance handoff without changing domain authority |
| [0056](0056-private-schema-backed-api-reference.md) | Accepted | Render the canonical OpenAPI contract through private, locally served Swagger and ReDoc views without enabling per-endpoint browsable APIs |
| [0057](0057-numpy-docstrings-and-generated-contributor-reference.md) | Partially superseded | Enforce NumPy-style Python contracts and build a warning-fatal Sphinx contributor reference in CI; ADR 0058 strengthens semantic depth |
| [0058](0058-professional-python-documentation-contracts.md) | Partially superseded | Require complete public NumPy contracts and reject generated boilerplate; ADR 0059 strengthens signature synchronization and exact raises |
| [0059](0059-strict-pydoclint-and-bounded-ruff-exemptions.md) | Accepted | Enable the strictest useful PyDocLint contract and replace broad Ruff exemptions with eight bounded global categories |
| [0060](0060-protected-collaboration-and-release-evidence.md) | Partially superseded | Protected GitHub flow, CalVer, and evidence-bearing OCI releases; ADR 0061 replaces its six-shard full-acceptance decision |
| [0061](0061-latency-bounded-full-acceptance.md) | Accepted | Change-aware hosted acceptance with eight measured PostgreSQL shards, restored for public collaboration by ADR 0063 |
| [0062](0062-local-exact-commit-certification.md) | Superseded | Historical private-repository local certification topology; ADR 0063 restores hosted execution after the public transition |
| [0063](0063-public-hosted-protected-collaboration.md) | Partially superseded | Public hosted merge-candidate acceptance, no-bypass rulesets, immutable Action allowlisting, and no persistent runner; ADR 0066 replaces merge-group, exact-head, and nine-database details |
| [0064](0064-repository-supply-chain-and-code-scanning-policy.md) | Accepted | Security-only dependency automation, fail-fast lock and Actions policy checks, and reconciled CodeQL merge thresholds |
| [0065](0065-immutable-release-publication-and-verification.md) | Accepted | Administrator-confirmed immutable-release policy, verified draft publication, and exact post-publication release and OCI evidence |
| [0066](0066-event-efficient-fail-closed-hosted-acceptance.md) | Accepted | Draft-light ready-authoritative acceptance, fail-closed destructive routing, and eight-database full certification |

New ADRs use the next four-digit number and contain:

- status and date;
- context;
- decision;
- consequences;
- alternatives considered;
- requirements affected.

An accepted ADR is not edited to make a later decision appear original.
Supersede it with a new ADR and update this index.
