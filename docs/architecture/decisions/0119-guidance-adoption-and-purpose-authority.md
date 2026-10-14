# ADR 0119: Explicit Guidance adoption and separately accepted authority

- Status: Accepted; implementation in progress
- Date: 2026-10-09
- Partially supersedes: ADR 0080 only for the absolute immutability of an
  edition's selected profile; exact manifest meanings remain immutable
- Extends: ADRs 0031, 0041, 0044, 0117 and 0118
- Requirements: EVT-006, EVT-008, IDN-002, IDN-005, IDN-009, IDN-011,
  KNO-010 through KNO-013, UX-031 and NFR-013

## Context

An organization trying Announcements must be able to add useful internal Guidance
without creating a second copy of its event. Ordinary edition editing cannot do
this: adoption is immutable, existing representations have exact purposes, and an
Announcements root already holds generic grant and role-management powers.
Merely adding Knowledge capabilities to a new profile would allow those old powers
to control a purpose their holders never accepted.

A standalone Guidance organization needs the same truthful boundaries. A new
Guidance-specific organization root containing every content capability would
create a second authority architecture beside supplemental Guidance access.
The first increment instead separates foundation stewardship from exact-edition
Guidance responsibilities and uses one qualified ceremony for both entry paths.

## Decision

### Preserve exact manifests and event identity

Add two literal executable profiles: `guidance_only@1` and
`announcements_guidance@1`. Guidance-only contains Knowledge and required Identity,
Organizations, Events, Authorization, Audit, Effects and Privacy foundations. The
combined profile deliberately pins the Announcements and Knowledge capabilities,
destinations, effect routes, catalogs, adapters and reserved roles it admits.
It is a new manifest, not a widened `announcements_only@1` or other existing v1.

Support fresh Guidance-only setup and one directed expansion:
`announcements_only@1 -> announcements_guidance@1`. Initial combined creation,
other transitions and downgrade are outside this increment. Active organizations
and convention series with editions in Draft, Preparing, Ready or Live may use the
edge; closing, archived, cancelled, disabled or unknown scopes fail closed.
Ordinary edition writes still cannot change adoption.

Events owns proposal, exact preview, decisions and the append-only transition
receipt. The preview names the existing event, selected workflow, both responsible
people, resulting responsibilities and retained Announcements access. Two current
accountable organization controllers approve the same normalized terms through
their own authenticated actions. A platform administrator separately approves the
setup decision. Pending, declined, cancelled, expired or changed terms grant
nothing. Apply locks and rechecks current parents, people, source authority,
versions and exact manifest fingerprints before changing anything.

Apply preserves organization, series and edition identifiers, existing
Announcements records and original creation/setup receipts. The transition receipt
retains source and target pairs/digests, prior edition cursor, actual decisions,
reason, retry identity and exact resulting authority references. A retry binds the
original input and returns the original output only after current authorization.
Edition-creation replay continues to compare its original creation facts, not the
edition's later selected profile. Native guards require transition evidence for
the exact persisted change, and exact persisted outputs for every receipt.

### One foundation-only representation for fresh setup

Add immutable `workspace_operators` representation and root for people responsible
for operating the necessary Maru foundations without claiming constitutional
office. Its literal ten capabilities are:

- `organizations.view_basic`, `organizations.change_profile`,
  `organizations.create_series`, `organizations.change_series`,
  `organizations.manage_representation`;
- `events.view_basic`, `events.create`, `events.change_profile`,
  `events.transition`; and
- `audit.view_security`.

It contains no generic grant, role-management, delegation or revocation power and
no Knowledge content capability. Initial invitation, self-acceptance, organization
activation and later representation recovery use the existing accountable
representation ceremony. Existing Executive Board, Workforce and Announcements
representations and their root versions stay unchanged. Reusing an eligible
organization does not replace its representation. No ordinary creation or profile
path may turn the new foundation root into authority for another product.

### One closed supplemental authority scheme

Authorization owns the non-delegable `authorization.manage_guidance_access`
capability and canonical immutable `guidance-access-controller@1` bundle containing
only that capability. Assignment is exact organization and edition only. It is
not a content permission, organization-wide controller or platform-policy bypass.
Direct grants of the control capability and mixed or custom bundles containing it
are forbidden.

Only the small reviewed Guidance recipe set may contain first-version Knowledge
capabilities. A reader recipe grants current reading only. The operator content
recipe contains the seven separately checked Knowledge capabilities. Definitions
remain organization-scoped historical facts; an edition-scoped controller cannot
create arbitrary organization-wide definitions. The qualified setup ceremony
creates or reuses the exact immutable recipes under organization-root decisions.
Definitions themselves grant nobody access.

An immutable Authorization setup qualification receipt links the accepted Events
setup/expansion, exact principals and decisions, stable edition Guidance team,
canonical recipes and exact first controller assignments. It qualifies two current
linked organization-root sources through `organizations.manage_representation`
only for those named bootstrap targets. The receipt is not a reusable source or a
new platform authority basis. Native checks enforce both receipt-to-output and
output-to-receipt correspondence.

For this initial ceremony, the two selected Guidance operators are the same two
current accepted organization-root controllers. Each independently accepts their
own controller and content responsibilities and approves the other's exact
responsibilities. Selecting different initial recipients requires a later
invitation/approval contract; entering another identity does not substitute for it.
For operators A and B:

1. Issue A's controller assignment with actor A and approver B, and B's with actor
   B and approver A, pinning their earlier qualified organization-root issuances.
2. Once both controller assignments exist and are current, issue A's content role
   with actor A and approver B, and B's with actor B and approver A, using those
   earlier Guidance-controller issuances.

The acceptances explicitly retain the conditional instruction for content-role
cross-approval. They do not claim Guidance authority existed before activation.
No recipient approves their own assignment, no control points to a later issuance,
and no platform administrator becomes an ordinary recipient or controller.
The profile transition and all outputs commit atomically; deferred guards validate
the complete graph. The same ceremony applies after fresh foundation activation.

### Preserve purpose throughout later access and recovery

Every later Guidance content assignment uses a typed canonical-role request and
the named approver's own authenticated decision. It requires two distinct current
Guidance controllers, exact pinned sources and complete scope/time containment.
An actor may request their own access, but the approver cannot be the recipient.
All eight protected Guidance capabilities reject generic direct grants and
delegation. Controller assignments remain ceremony-only in this increment.
Canonical reader, editor, reviewer and operator recipes provide ordinary content
sharing without an approver-identity field standing in for actual consent.
Generic assignment is a persistence primitive only inside a validated accepted
typed request or ceremony; inverse native receipt checks reject other paths.
Generic Announcements/Board grant and role-management authority cannot bypass
this boundary, including through compatibility commands or raw SQL.

One current Guidance controller may revoke Guidance access immediately with a
reason and retained source-backed revocation evidence. Generic revocation alone
does not qualify. Emergency platform containment keeps its separate accepted
purpose. Guidance controllers acquire no authority over Announcements or other
modules. Access inventory, policy explanations, selectors, historical and current
provenance validation, native guards and readiness use the same closed target
classification; a hidden UI control is not an enforcement boundary.

Both pinned ancestor chains remain live dependencies. Expiry, revocation,
deactivation, malformed provenance or scope loss invalidates descendants without
rebinding to equivalent authority. A fresh recovery ceremony may issue replacement
responsibility through current organization roots and new actual decisions. It
cannot reuse old expansion consent or silently repair descendants. The Guidance
team identity remains stable; content retains its historical ownership evidence.
Existing representation recovery remains necessary when the root pair itself is
unavailable.

### Stop and recover without erasing adoption

Stopping Guidance follows ADR 0118 and never reverses the manifest or stops
Announcements. Authority, current content and retained history keep their separate
checks. Used setup, transition or supplemental authority evidence fences downgrade;
recovery fixes forward or restores the mutually consistent owner graph. Unused
migration reversal is tested. New runtime relations, exact helper generations,
source pins and readiness are reviewed without widening old function closures.

## Consequences

A small team can start with one workflow and add Guidance to the same event.
Advanced profile and receipt identifiers stay under technical details, while
people, purpose, approval consequences and errors remain visible. The foundation
work is substantial because a new workflow must not silently widen existing
control. Native tests must exercise generic-command and raw-SQL bypasses, foreign
scope, mixed roles, platform denial, either pinned-source loss, stale/retried
apply, explicit recovery and a real restricted-runtime expansion with retained
Announcements history.

## Alternatives considered

- Editing the old manifest or relabelling an existing root would change accepted
  authority without a new decision.
- Duplicating the edition would fragment Announcements history and context.
- Giving a new Guidance root generic administration powers would reproduce the
  same expansion trap for the next workflow.
- A general purpose-tagged authorization framework is deferred. This decision
  introduces one closed purpose and recipe set through existing issuance/control
  primitives, with typed qualification and recovery evidence.
