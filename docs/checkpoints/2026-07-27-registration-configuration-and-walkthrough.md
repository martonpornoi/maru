# Checkpoint: Configurable registration and Danube walkthrough

- Date: 2026-07-27
- Phase: Initial registration vertical across V03/V08/V09 boundaries
- Related requirements: EVT-002, EVT-003, AUD-002, ACT-001, UX-001 through
  UX-008, REG-001 through REG-003, REG-005, REG-007, REG-009, REG-010
- Related ADRs: 0002, 0003, 0005, 0006, 0007

## Outcome

Maru can now demonstrate a coherent synthetic convention registration:

1. An organizer creates an edition-owned draft from a blank setup, published
   template, or another edition in the same organization.
2. The organizer reviews and activates an immutable version.
3. An attendee chooses a product and answers the convention's conditional
   purpose-disclosed questions.
4. A local/test adapter reconciles payment without receiving card data.
5. Maru grants admission and exposes attendee-appropriate history.
6. Authorized Front Desk staff see a minimized service record and check in the
   attendee with a reason.

Danube and Aurora have different questions and products. Published templates
and prior-edition copying prove reuse without mutable coupling.

The V02 activity gap also closed: sign-in/sign-out security history is
subject-visible, while registration workflow history is a separate operational
timeline.

## Decisions

ADR 0007 was accepted. Registration configuration is edition-owned,
copy-on-write, and versioned. Imports retain provenance and require review;
activation freezes a version; published templates are immutable versions;
cross-organization copying is denied.

The first question builder supports C1/C2 only. C3/C4 collection remains
unavailable until a restricted domain, retention rule, and access workflow own
it.

The payment boundary is real but the only adapter is explicitly local/test.
It is not a prototype production card integration.

## Changed areas

- New `maru.registration` module, models, migrations, services, serializers,
  APIs, capability definitions, admin, audit, and effect registrations.
- New account-security event model, authentication signals, self API, admin,
  and append-only database guard.
- Staff Console `My registration`, `Commerce`, `Security`, and typed Today
  actions.
- Template and prior-edition copy, draft activation, template publication,
  attendee submission/payment, staff queue/detail, and check-in APIs.
- Synthetic fixture v2 with two convention-specific configurations, two
  templates, future inherited drafts, and four registrations.
- OpenAPI and generated TypeScript client updated.

## Verification

- Ruff formatting/lint pass.
- Strict mypy passes 100 source files.
- 267 PostgreSQL-backed tests pass.
- Branch-aware coverage is 90.02%, meeting the 90% gate.
- Ten frontend tests, typecheck, and production build pass.
- Migrations apply and drift check pass.
- OpenAPI generation and validation pass.
- Real-browser desktop and 390-pixel mobile walkthrough passed with no runtime
  console errors or horizontal overflow.

## Data, migration, and deployment notes

The migrations add registration tables, account-security events, and
PostgreSQL scope/immutability/append-only guards. Existing account,
participation, authority, audit, and effect records remain in place.

The local fixture was reseeded idempotently. Existing local fixture passwords
were preserved. Production settings keep the demo payment adapter disabled and
do not install the demo management command.

Rollback must not drop registration, submission, payment, entitlement,
check-in, or timeline data without an explicit export and recovery decision.

## Known risks and incomplete work

- No production payment provider/webhook/refund flow.
- No reservation expiry, wait list, discount/voucher, transfer, or dispute.
- No visual form builder; draft question/product content uses bootstrap admin.
- No eligibility engine, badge printing, fulfilment, or offline check-in.
- Capacity needs concurrency/load evidence before public sales.
- Partner and jurisdiction-specific validation remain.

## Recommended next actions

1. Specify and implement the first production payment adapter and reconciliation
   contract.
2. Add reservations/expiry and concurrency-tested capacity.
3. Build configuration comparison, preview, and visual draft editing.
4. Continue into badge/credential issuance and bounded offline arrival.
