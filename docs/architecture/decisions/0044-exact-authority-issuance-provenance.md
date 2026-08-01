# ADR 0044: Exact authority issuance provenance and controller lineage

- Status: Accepted
- Date: 2026-08-01
- Clarifies: ADRs 0003, 0023, 0040, 0041, and 0043
- Requirements: IDN-002, IDN-004, IDN-005, IDN-009, IDN-011, IDN-012,
  UX-020, AUD-001, AUD-005, NFR-001 through NFR-004, and NFR-008

## Context

Root capability grants, immutable role-bundle versions, and role assignments
already record the actor and independent approver. Commands prove at issuance
time that both people have sufficient authority and that a time-bounded child
does not outlive either controller. The records do not retain which exact grant
or role assignment supplied that authority.

An account can hold several equivalent sources. If one source later expires or
is revoked, Maru cannot prove whether a child depended on it, and the current
policy may silently continue through another row. Identity fields and an audit
timestamp are useful attribution but are not a dynamic authority chain. This
leaves IDN-005 incomplete even after ADR 0041's exact scope implementation.

The initial Executive Board ceremony is also intentionally different from an
ordinary grant. The platform operator establishes the first root while accepted
controllers cross-approve one another. Requiring those new assignments to be
authorized by themselves would create a cycle; treating platform status as
ordinary organizer authority would violate ADR 0031 and IDN-011.

Maru therefore needs immutable, queryable issuance provenance with a deliberate
root ceremony, exact dynamic controller loss, safe legacy handling, and a
database boundary that cannot be bypassed with direct ORM or SQL writes.

## Decision

### One append-only issuance ledger

`maru.authorization` owns an `AuthorityIssuance` for every capability grant,
role-bundle version, and role assignment created after provenance activation.
Each issuance has one database-generated monotonic ordinal, one non-guessable
stable public identifier, policy version, evaluation time, and exactly one
typed target foreign key. Generic foreign keys, free-form target kinds, and
untyped UUIDs are not allowed.

`AuthorityControl` records the actor and approver evidence for an issuance. A
control contains the exact principal, control role, policy version, evaluation
time, and exactly one basis:

- `persistent_authority` points to an earlier issuance whose target is one
  CapabilityGrant or RoleAssignment;
- `platform_representation_bootstrap` points to the exact Executive Board
  representation activated by that platform operator; or
- `representation_acceptance` points to the exact accepted appointment whose
  account supplied cross-approval during initial activation.

The target, issuance, and controls are immutable, protected from deletion, and
created in one transaction. Deferred PostgreSQL checks require complete
evidence at commit while permitting the target and its provenance to be
inserted in either application-safe order. Source ordinals must precede the
child ordinal. Shape, identity, capability, scope, horizon, and special-basis
guards apply even when model validation is bypassed.

An ordinary root CapabilityGrant, RoleBundle version, or RoleAssignment has
exactly two controls named `actor` and `approver`. The principals are distinct,
the approver is not the authority recipient, and their identities match the
target's existing attribution fields. A delegated CapabilityGrant has one
issuance and zero controls because its exact dynamic source remains the
mandatory `delegated_from` grant. No target may have two issuances.

### Deterministic source selection

Callers do not submit authority-source identifiers. Inside the same transaction
as the target write, the command locks both controller accounts, the resolved
target, and eligible source issuances in stable order. It repeats policy and
horizon evaluation and pins one source for each controller using this order:

1. the closest, narrowest scope that contains the exact target;
2. a direct grant before a role assignment at the same scope;
3. the least surplus expiry that still covers the requested interval, with an
   unbounded source last; and
4. the stable issuance ordinal as the final tie-breaker.

This is a least-authority rule, not a user-editable preference. Sensitive access
explanations may disclose a human label for the pinned source to an authorized
viewer, but ordinary responses and denials do not expose issuance identifiers.

Generic platform-administrator policy is never an eligible persistent source
for ordinary organizer grant, bundle, or assignment commands. Platform
administration may establish root authority only through the code-owned initial
Executive Board ceremony and may contain it through the separate ADR 0043
emergency command. This keeps the Board as the organizer's accountable root.

### Dynamic validity

Root grants and role assignments are effective only while both pinned source
chains remain current. Expiry, revocation, account deactivation, malformed
lineage, or loss of scope/capability at any ancestor immediately makes the
child ineffective. Maru does not silently rebind a child to another equivalent
source. Restoring responsibility requires a new independently approved record.

Role-bundle controls prove that the immutable definition was authorized when
created. Later loss of a controller does not erase or invalidate that historical
definition. Every later assignment still requires fresh current dual control.
An unproven legacy bundle may remain immutable history but cannot be selected
for a new assignment after activation.

Policy keeps its public `PolicyDecision` identifier-free. An internal
source-bearing result selects and validates exact lineage for commands and
sensitive explanations. Evaluation is bounded, cycle-safe, and request-local;
unknown, missing, future, revoked, cross-tenant, malformed, or cyclic sources
fail closed without record-existence disclosure.

### Initial Executive Board provenance

ADR 0040 activation creates provenance without an authority cycle:

- the reserved Executive Board bundle records the activating platform operator
  through `platform_representation_bootstrap` and one accepted controller
  through `representation_acceptance`;
- each initial Executive Board assignment records the same platform activation
  basis for its actor and the exact different appointment selected by the
  deterministic cross-approval cycle for its approver; and
- later ordinary commands by a Board controller pin that controller's exact
  Executive Board RoleAssignment issuance as persistent authority.

Special controls are historical ceremony evidence, not generic reusable
authority. Later platform-operator deactivation does not collapse an active
Board. An activated appointment that later ends remains valid historical
cross-approval evidence as required by ADR 0043, but the controller's own Board
assignment is currently effective only while its linked appointment,
membership, representation, account, and assignment remain Active. Accepted or
ended appointments never authorize ordinary commands by themselves.

Routine replacement, voluntary ending, suspension, reactivation, and quorum
recovery remain explicit representation commands. Each must update current
terms and assignments without rewriting issuance history.

### Migration, reconciliation, and recovery

Provenance is a stopped-writer, staged migration:

1. add issuance/control schema and compatibility readers;
2. deploy provenance-writing ordinary commands and the Executive Board writer;
3. deterministically backfill only evidence that is already provable: exact
   governed Executive Board activation and delegated-grant parent lineage;
4. reconcile effective ordinary legacy authority by revoking and recreating it
   under current dual control, and replace any referenced unproven bundle with a
   newly authorized immutable version; and
5. activate fail-closed policy and deferred database completeness guards, then
   set a durable provenance-write downgrade fence.

Migration never selects a likely historical source merely because one matching
record exists now. Effective or future root grants and role assignments without
provable issuance, and referenced/assignable role bundles without provenance,
are blockers. Expired or revoked unproven authority and unused immutable legacy
bundles remain count-only review debt when no active path can reach them. The
preserved broad workforce bootstrap is recovery debt and cannot establish new
production lineage.

A privacy-minimized readiness command reports counts for missing or malformed
issuance, incomplete controls, identity/capability/scope/horizon disagreement,
non-earlier sources, cycles, invalid Board bases, delegated-parent gaps, and
legacy bootstrap signatures. It prints no person, capability, tenant, or
authority identifiers. Production status becomes ready only when every
effective or reachable authority path has valid lineage and the activation
guards are installed.

Old writers are incompatible once provenance activation begins. After the
first provenance write, recovery keeps compatible code and fixes forward or
restores target records, issuance evidence, representation state, audit, and
outbox to one mutually consistent pre-write point. Reversing only the ledger or
deleting evidence is forbidden. A failed issuance transaction leaves no orphan
target or control; committed asynchronous effects are replayed from the outbox
rather than reissuing authority.

## Consequences

- Immediate revocation now includes the exact authority used by both root
  controllers instead of an existential match at issuance time.
- Equivalent unpinned access cannot silently preserve a child whose selected
  source ended.
- The first Board remains non-cyclic and does not convert platform status into
  organizer participation.
- Root commands require source-aware queries, stable lock ordering, recursive
  validation, more explicit explanations, and broader concurrency tests.
- Historical definitions and controls remain inspectable without making unsafe
  legacy authority usable.
- The contextual hierarchy/access editor can build on an explainable authority
  graph once this production gate is locally verified.

## Alternatives considered

### Store only controller account identifiers

Rejected. Those fields already exist and cannot identify which of several
authority records the command used or propagate that source's loss.

### Add actor-grant, actor-role, approver-grant, and approver-role columns to
every target

Rejected. It duplicates a sparse polymorphic shape across three models, makes
new authority target kinds expensive, and still needs one common graph and
database cycle boundary.

### Re-evaluate against any matching source

Rejected. Automatic rebinding makes revocation ambiguous and lets unrelated
authority silently keep a child alive.

### Let platform administrators issue ordinary organizer authority

Rejected. It would bypass the accountable Executive Board root and blur
platform oversight into convention participation.

### Treat accepted appointments as ordinary authority

Rejected. Acceptance is consent to the initial representation term, not an
open-ended grant-management capability. Ordinary authority comes from the
active linked Executive Board assignment.

### Infer legacy sources during migration

Rejected. Current matching rows do not prove which source was used historically.
Unsafe inference would manufacture audit evidence and make revocation claims
that Maru cannot defend.
