# Typed application studio milestone

Date: 2026-08-08

## Outcome

Maru now has a bounded `maru.applications` module implementing REG-023 and an
intake/review slice of KNO-009 without changing attendee registration
ownership. It provides edition-owned definition drafts, immutable
activation/retirement and successor versions, the shared typed field
vocabulary, applicant drafts with append-only answer revisions,
exact-role/named-person review queues, append-only decisions, and closed typed
target-transition receipts.

The code-owned catalog contains Registration as one external studio entry and
ten copyable application-owned starters: merchandise, DJ, Fursuit Dance
Competition, Maid Cafe, adult Fursuit Striptease, volunteer, feedback, ideas,
SecOps damage reports, and time-bounded helpers. Adult, C3/C4, and case
workflows fail closed until local audience, retention, and age policy is
explicit. No host-panel starter or programme adapter is part of this slice.

Strict v1 APIs and minimal shared-shell/My Maru pages are mounted. The unified
searchable navigation shows applicant, definition-studio, and review links only
after current self or exact-edition authorization and supports live pins.

## Durable decisions

- Registration remains one attendee-owned workflow; contribution forms are
  separate typed applications.
- Activated schemas and child rows are immutable. Change uses a successor
  draft rather than in-place edits.
- Answers and decisions are append-only evidence. Audience projections are
  field-policy filtered.
- Acceptance records a closed adapter discriminator and never promotes a
  generic response sheet into target-domain truth.
- Every command uses tenant scope, expected versions where stale state matters,
  idempotent receipts, minimized audit, registered domain events, and outbox.
- PostgreSQL repeats the sensitive-policy, activation graph, tenant, subject,
  contiguous history, queue-basis, append-only, and target-adapter invariants.

## Verification

- Focused Ruff gate for the module, catalog, migrations, event registry,
  navigation, URLs, and tests: passed.
- Starter, capability, and event contract tests: `4 passed`.
- PostgreSQL application workflow tests after final trigger hardening:
  `2 passed in 36.46s`.
- Django system check: passed with only the already documented invitation
  delivery encryption warning.
- Application HTML and API route reversal smoke check: all five representative
  route families resolved.

## Remaining work

- Target-domain modules may add their own consumers for the explicit adapter
  receipts; they must not read a generic response sheet as authoritative state.
- Configurable staff answer-correction windows and an approved public answer
  rendition remain future KNO-009 work; current answer projections are for the
  applicant and assigned reviewer only.
- The HTML workspaces are minimal projections. A richer visual editor can call
  the existing strict command APIs without changing the domain boundary.
- Governed retention/disposal commands for expired definitions, answers, file
  receipts, and decisions remain future privacy-operations work; ordinary
  deletion remains blocked.
