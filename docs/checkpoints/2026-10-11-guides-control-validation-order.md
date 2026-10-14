# Guides control validation order

- Date: 2026-10-11
- Requirements: IDN-005, KNO-013, NFR-001; ADRs 0044 and 0119.

Full certification of `614e6a2` failed after 5788.171 seconds. Forty-four batches
passed. Shard 45 passed 99 cases and failed one established unknown-control-role
assertion: the new Guides expected-source guard raised its error before the
existing closed-role validation. Seven other batches were interrupted, and all
52 owned containers were removed. Complete evidence is preserved under
`.tools/guides-certification-614e6a2/failed-local-ci-evidence/`.

The unmerged Authorization 0046 source helper now identifies non-Guides targets
before applying Guides role validation. Ordinary unknown roles reach their unchanged
native rejection; Guides targets still require their exact accepted source and
closed role. The source digest is updated to the exact edited migration; readiness
checks remain mandatory. No test expectation,
permission, source identity rule or readiness contract is relaxed. This changes
validation ordering in the candidate migration, not a deployed database.

The original regression and complete Guides foundation file passed all 16 native
cases in 253.92 seconds (260.313-second wrapper), with no skips or errors.
Before/after source inventories matched digest
`13dec282f2b141c34a5a2c89d6ef762505c1ab67a04031e58990fb3ad20443ed`,
and the exact owned container was removed. Evidence remains under
`.tools/guides-control-order-20261011/native-reserve-20261011T171100Z-1828995d/`.
Owner lint, formatting, documentation and whitespace checks passed. Migrations
retain the repository's existing Ruff exclusion; a direct lint invocation ignored
that exclusion and reported pre-existing migration style findings, not native
failures. A changed commit requires fresh full certification. Browser and operational acceptance remain separate, including the
binding V6 credential-entry refusal. Demo coverage is unaffected.
