# Convention demo hosted retention-clock fixture repair

Date: 2026-10-15

PR #213 candidate `7ac2925ce2b3a3b9fb13adac8870a28acd5a7be7` passed complete
local certification against `c4a988d0808c6ee054c7ed7c726c5a111e934579`:
14,278 units, 5,249 native cases in 89 batches, no failures/errors/skips,
91.24 percent combined coverage and all timing gates in 16,426.378 seconds.
Every owned container was independently absent. Its complete 5,438-file evidence
archive hash-matches the original. CodeQL passed; exact-head Copilot review
reported zero open findings and the clipboard conversation was resolved.

Hosted run `38748503767`, job `116469424872` (database batch 52), failed the
existing `test_database_clock_rejects_plus_250ms_hold_and_receipt` assertion;
88 other cases passed in 992.30 seconds. The test reused one database-derived
future value across separate hold and receipt transactions. The receipt reached
the deferred completeness guard rather than the expected strict-time guard once
the 250 ms future window had elapsed. The full job log and uploaded diagnostics
are retained separately; remaining jobs were still running when this repair began.
This is a failed hosted acceptance, not a successful delivery.

The test-only repair takes one materialized database clock sample inside each
policy, hold and receipt insertion. It retains the exact 250 ms offset and the
existing native-error assertions. Hold/receipt coverage now also waits 350 ms
between the writes so the second insertion must use its own fresh sample.
All production guards, migrations, source fingerprints, authority boundaries,
coverage requirements, concurrency and timing budgets are unchanged. This maps
to IDN-013 and the Identity module's existing database-clock retention contract;
no new architecture or product behavior is introduced.

Focused native validation and fresh exact-commit local and hosted acceptance
remain required. No repair verification, merge, independent-human or production
acceptance is claimed by this checkpoint's initial record.

## Focused repair verification

The policy/naive-time case and both immediate/delayed hold-receipt cases passed
on the unchanged source in 192.42 seconds (199.765 including wrapper and cleanup).
The source inventory digest was
`a9f18d64082cfa21009e23abb49c47d850da600b3867ee48ce6108e1322e1a5d`;
complete before/after inventories matched. All three JUnit cases had zero
failures, errors or skips. The exact owned container was independently absent.
The deliberately delayed case retained the expected strict-time refusal after
350 ms between writes, without accepting the different completeness error.

All 14,278 database-free units passed in 78.59 seconds using an isolated owned
temporary directory. Scoped Ruff lint/format, the 752-file documentation
validator and whitespace checks passed. These results validate the focused
repair; the changed candidate still requires fresh complete exact-commit local
certification and independent hosted acceptance before protected merge.
