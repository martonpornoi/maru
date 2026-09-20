# ADR 0110: Independent Identity invitation writer cutover

- Status: Accepted; implementation and native acceptance pending
- Date: 2026-09-20
- Extends: ADR 0047
- Partially supersedes: only any combined Registration/Identity interpretation
  of the staged cutover; Registration's own writer gate remains unchanged
- Requirements: IDN-013, IDN-014, NFR-013, AUD-002, PRI-001, OPS-009

## Context

The real #109 Programme candidate reaches its native runtime boundary but refuses
Identity invitation readiness. The invitation stopped-writer generation is
deliberately absent. Unit/component PostgreSQL acceptance did not exercise this
host-only startup. #196 records the prerequisite explicitly under #48; the archive
implementation cannot claim P11 acceptance while startup fails.

The invitation HTML/API adapters already share the reasoned commands, model
administration is inspection-only, and the dedicated delivery/reconciliation/
retention workers own durable invitation delivery. Native additive migrations
already enforce complete invitation/challenge/account/transition/receipt/audit/
delivery lineage and immutable retention evidence. Ordinary account managers,
public bootstrap, verification/recovery, and stopped migration-owner bootstrap
also serve legitimate non-invitation flows. They must not invent an invitation
or become dependent on Registration configuration.

The remaining competing invitation path is the generic challenge interface and
its legacy delivery columns. The generic delivery helper already refuses
invitations, but generic issuance/consumption accepts an open purpose string;
the legacy delivery columns are not independently frozen for every ordinary
invitation challenge update. A future accidental caller or obsolete writer must
not turn those columns into a second delivery authority.

## Decision

Complete the Identity invitation writer generation independently, not the wider
Registration cutover. Keep the existing shared commands and native graph guards.
Generic challenge issuance and consumption admit only email verification and
account recovery, before abuse writes, token work or queries. Invitations use
their dedicated recipient-owned password and versioned command boundary.

An additive migration installs a narrow invoker-rights challenge trigger with
pinned search path and no PUBLIC/runtime EXECUTE grant. A new invitation challenge
must carry the inert legacy delivery defaults. Once an invitation challenge
exists, its legacy delivery status/count/attempt/delivery/error fields cannot
change. A challenge cannot enter or leave the invitation purpose through UPDATE.
Ordinary verification/recovery delivery remains unchanged. Existing retained
historical values are not rewritten or reinterpreted as durable delivery proof;
current invitation readers continue to use the separate canonical delivery rows.
Retention may still tombstone its already-governed private fields without
changing these frozen legacy delivery facts.

The generation is ready only when the actual migration record, trigger timing,
function body/attributes/ACL and source contract match, together with the entire
existing additive invitation catalog. A code constant is only an expected
version label, never activation evidence. Key coverage, actual delivery/expiry/
retention workers, policy control, runtime role and measured search-plan checks
remain mandatory. No rehearsal override disables any of them.

Migration installation serializes challenge writes. Empty unused databases may
reverse the generation; any retained invitation/challenge/transition evidence
refuses downgrade before removing its guard. After use, recovery is fix-forward
or a verified whole-system restore that preserves the generation. This decision
activates no production policy, sends no external message and grants no new
runtime relation rights.

## Verification and consequences

Prove real command creation/reissue/acceptance/revocation/expiry and durable worker
behavior with the guard installed; prove direct legacy-field and purpose changes
fail atomically. Cover ordinary bootstrap/verification/recovery and retention
coexistence, fresh/populated upgrade, unused reversal, used refusal, runtime-role
readiness, disabled/missing/changed guard refusal and restored schema evidence.
Then rerun the genuinely owned #109 candidate; do not close #196 from a mocked
readiness result or treat this as #92 human/#97 restore acceptance.

Rejected: changing `None` to a nonempty string without native enforcement;
disabling invitation encryption/readiness in the fixture; inventing worker
heartbeats; or requiring unadopted Registration redesign to operate Programme.
All other ADR 0047 product, privacy, recipient-consent, evidence and production
acceptance boundaries remain in force.
