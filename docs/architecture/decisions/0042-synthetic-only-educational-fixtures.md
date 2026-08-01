# ADR 0042: Synthetic-only educational fixtures

- Status: Accepted
- Date: 2026-08-01
- Supersedes in part: ADR 0028's local public-roster import boundary
- Requirements: IDN-006, IDN-011, PRI-001, PRI-007, INT-005, NFR-001 through
  NFR-004, and NFR-009

## Context

ADR 0028 allowed an explicitly acknowledged local/test adapter to copy public
volunteer handles, department descriptions, and role labels from a convention
website into a disposable Maru rehearsal. The implementation minimized the
source and excluded images and contact details, but it still turned identifiable
real people into local accounts and coupled the educational journey to a live
external roster.

Maru's current repository rule prohibits production personal data in tests,
examples, and fixtures. ADRs 0031 and 0040 also require the platform
administrator to remain outside convention relationships and replace the old
broad bootstrap with an exact Executive Board invitation and acceptance
lifecycle. Retaining the live adapter or its command would leave a hidden path
around those current boundaries.

Public organizational taxonomy can be useful product research, but copying
identifiable people is unnecessary to demonstrate hierarchy, multiple roles,
registration, access, or convention operations.

## Decision

All repository-controlled demonstrations, tests, tutorials, screenshots,
fixtures, and educational smoke journeys use deterministic synthetic people,
`.invalid` contact identifiers, and synthetic convention records. A public
website may inform a reviewed taxonomy or requirement, but its real handles,
names, images, contact details, and person-to-role assignments are not fixture
input.

The `seed_marucon_rehearsal` compatibility command is fail-closed. It accepts
its former option names only so old automation receives one stable retirement
error before password validation, file access, network access, or database
mutation. The former Awoostria network adapter always raises its retired error
before URL handling or network I/O.

The bounded HTML parser may remain for synthetic taxonomy unit tests. It is not
a supported import boundary. A future organizer migration must satisfy INT-005
with declared purpose, mapping, preview, provenance, validation, duplicate
strategy, staging, access, retention, and operator approval; it cannot revive
the rehearsal adapter.

`seed_demo_data` is the canonical local educational fixture. It establishes
organization representation through the same provision, exact invitation,
self-response, and two-controller activation services as Page 8. The platform
administrator is an attributed operator only and receives no convention
relationship or authority-principal record.

Historical checkpoints remain as evidence. The retired scenario implementation
is removed from the production package; only the small fail-closed command and
synthetic parser tests remain. Historical prose is not current instruction or
permission to import a live roster.

## Consequences

- Local demos remain deterministic, offline, idempotent, and safe to share.
- Tests cannot drift when a public roster changes and cannot accidentally
  preserve real-person role history.
- Tutorials use recognizable synthetic roles instead of real usernames.
- Product research may cite public department patterns without creating
  accounts or presenting the source roster as Maru data.
- The old command remains visible only to fail clearly; no silent compatibility
  import exists.
- Any future real migration needs a separate accepted contract and production
  data-governance review.

## Alternatives considered

### Keep the network import behind local settings and acknowledgement

Rejected. Local scope and acknowledgement do not make identifiable real people
necessary test data, and the live source remains mutable and externally
coupled.

### Check in a snapshot of the public roster

Rejected. A snapshot would make real identities more durable, lose source
correction context, and violate the synthetic-fixture rule more directly.

### Replace handles but retain exact person-to-role combinations

Rejected. That mapping can remain identifying in a small community. Synthetic
roles and deliberately recombined assignments demonstrate the same behavior.

### Delete the compatibility command as well as the scenario implementation

Rejected for this checkpoint. The scenario implementation is deleted because
it has no legitimate caller and keeping it would preserve an unnecessary
personal-data import path. The fail-closed compatibility command remains so old
automation receives a clear, side-effect-free retirement error.
