# Page 10 invitation-retention adversarial findings

Date: 2026-08-03

Status: **v7 stability claim rejected; v8 repair in progress**

This append-only checkpoint supersedes the release verdict, but not the
historical implementation evidence, in
`2026-08-03-page10-invitation-retention-production-gate.md`. An independent
review reproduced the reported v7 green baseline and then found behavior that
violates the accepted retention contract. Maru must not activate an invitation
retention policy or run this disposition path with production personal data
until the complete defect set is repaired and independently accepted.

## Reproduced baseline

- Fresh PostgreSQL retention/readiness matrix: **152 passed**.
- Runtime-role safety matrix: **117 passed**.
- Fresh forward migration, genuine empty `0017` to `0016` reversal, and `0017`
  reapplication succeeded.
- The reviewer made no implementation edits while producing the verdict.

## Release blockers

1. A successful receipt is not a durable tombstone. Raw updates can restore a
   disposed account's handle/display label and can replace retained challenge
   digests/fingerprints while the receipt remains apparently complete.
2. Delivery, attempt, and late-outcome provider references are not anonymized,
   contradicting the approved security/retention documentation.
3. Legitimate reissue histories above 32 challenges are permanently blocked
   even though the public invitation command enforces no matching ceiling.
4. The oldest blocked candidates can starve later eligible candidates on every
   bounded scheduler run.
5. The exact sole provisioning-origin invariant is not persistent: a later
   complete sibling invitation graph can be attached to the reserved account.

## Additional defects

- Hold placement and release accept arbitrary source-channel text and can place
  sensitive-looking values in permanent audit evidence.
- Several raw guards allow evidence approximately one second in the future.
- Invalid retention command limits escape as a traceback instead of a stable
  command error.
- Approved policy JSON accepts duplicate object members, leaving the human
  approval document ambiguous even though canonical digesting is deterministic.

## Required v8 acceptance

The repair must add permanent receipt-bound account/challenge freezes,
provider-reference anonymization compatible with append-only evidence, a
persistent sole-invitation invariant, arbitrary bounded challenge-history
handling, and fair durable candidate progress. It must also close source
channels, future timestamps, command errors, and duplicate JSON members.

Any schema change requires updated exact readiness fingerprints and counts,
runtime least-privilege proof, populated migration preflight, downgrade fence,
fresh forward/reverse/reapply evidence, raw-mutation and concurrency tests, and
an independent adversarial rerun. Conservative future-foreign-key failure and
the no-default-policy rule must remain intact.
