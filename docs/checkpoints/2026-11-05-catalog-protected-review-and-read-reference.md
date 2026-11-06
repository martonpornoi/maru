# Catalog protected review and combined read reference

Date: 2026-11-05
Requirements: REG-026, INT-001, AUD-001
Decisions retained: ADRs 0003, 0050 and 0056

## Protected predecessors

[PR #241](https://github.com/martonpornoi/maru/pull/241) delivered the existing
product and variant creation response reference through protected squash
`f8510bcf01994bd76e67af56e3b4bdcbc189d60d`, with the certified tree
`df4f428a82ceadceb8d772a597c17dd47dd80ae0` and sole parent
`e20e845b5c65654f835be6309c16a9e8d98053b8`.

[PR #242](https://github.com/martonpornoi/maru/pull/242) delivered the attendee
stock projection through protected squash
`8c243d8d88f1973704f93105b8b83f58146f4daf`, with certified tree
`b7bb4aa807578adfc72f65217eca8ee95dea9100` and the #241 result as sole parent.
Independent local verification passed 14,979 unit cases plus the exact Windows
POSIX skip, 5,242 native cases and 128 frontend cases. Local coverage was
91.241962%. Hosted verification passed 14,980 Linux unit cases, all 5,242 native
cases and 128 frontend cases. All 26 original coverage parts reconstructed
91.237084% and every original XML condition. Current CodeQL, the protected
PR gate, no-bypass rules, reviews and threads passed. Each delivery verified
the protected tree and parent, then normal fetch/ff-only synchronization with
local, origin, remote and GitHub equality.

The stock query retains the current quantity calculation and exact authorized
variant selection. Commands continue to calculate live availability under their
existing locks. The one- and twelve-variant regression uses five SQL statements
and checks latest adjustments, pending and paid quantities, exhausted stock and
stockless values. Broader response-wide consistency and production latency
remain under #36.

## Combined read-reference scope

The [read-reference PR #243](https://github.com/martonpornoi/maru/pull/243)
documents the existing own-order and staff-activity responses. Own orders are
self-scoped and can return an empty list without a catalog. Staff activity
requires the existing edition authority and records its allowed-read audit
before unsupported-query rejection. The response schemas, examples and generated
TypeScript follow those observed effects. Command/query behavior, profiles,
permissions, retained data and audit purpose are unchanged.

The two documentation conflicts retain the creation reference, stock projection
and read reference together. The module contract now accounts for six documented
handled-response operations across the existing eleven-operation route inventory.
The changelog includes the stock read improvement and the read-reference outcome.
Existing fictional Catalog data and role walkthroughs cover the same attendee
journey; these API-reference changes add no new demo journey.

## Verification and remaining scope

Combined preparation passed 136 focused unit cases, with two existing DRF
warnings, and documentation validation. The final integrated candidate requires
ordinary exact-head Auto against the actual protected #242 base and independent
hosted verification before protected squash. PR #243 records those final results,
source identities and any failures; earlier standalone results do not certify
the combined head. Recovery implications are limited to a code rollback because
these changes introduce no migration or retained-data repair.

Issue #36 remains open. The remaining handled response contracts, pagination or
complete-or-unavailable limits, full response consistency, read-audit purpose,
dependency failures, concurrent changes and compatibility need their owning
implementation or decisions under the [conformance plan](../development/catalog-edition-api-conformance-plan.md).
Browser and production acceptance remain separate. The preserved Workforce
manual trial, credentials, records, stopped fixtures and outstanding issues are
outside this Catalog delivery.
