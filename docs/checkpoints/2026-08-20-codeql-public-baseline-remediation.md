# CodeQL public-baseline remediation

Date: 2026-08-20
Status: Local corrective candidate; replacement CodeQL acceptance pending

## Outcome

The first public pull-request acceptance run passed every repository-owned job,
including all eight PostgreSQL shards, combined coverage, documentation,
dependency security, the full aggregate gate, and the required `PR gate`.
GitHub's separate CodeQL policy check reported seven alerts in files changed by
the large documentation patch: two high-severity polynomial-regex findings and
five medium exception-detail findings. The public baseline contained twelve
open findings in total: those two, one frontend DOM-XSS path, eight exception-
detail paths, and one request-derived redirect.

The corrective candidate fixes the complete twelve-alert baseline rather than
dismissing or limiting the change to the seven PR annotations:

- unsigned and signed canonical integers now use bounded linear ASCII-decimal
  checks instead of repeated regex branches;
- Events and Authorization API adapters retain stable public reason codes while
  replacing caught exception text with code-owned operation messages;
- the closed Logistics JSON parser exposes one generic malformed-document
  message while retaining the exception chain for internal diagnostics;
- successful equipment-offer submission reverses the exact named same-origin
  route instead of redirecting to `request.path`; and
- the Staff Console percent-encodes the selected registration-configuration ID
  before placing it in a Django admin path segment.

No model, migration, tenancy, authority, audit, API schema shape, or release
contract changes. Existing ADRs and the threat model already require these
non-disclosing, strict-input, and same-origin boundaries, so no new ADR is
needed.

## Verification

- PR run `32379350090` passed every repository-owned job and `PR gate`; CodeQL
  run `32379348235` passed Actions, Python, and JavaScript/TypeScript analysis.
  The policy check `96458615130` alone failed with seven annotations.
- Focused Python unit coverage passes 80 tests for canonical integers,
  Logistics parsing, redirect behavior, and adjacent adapters.
- The complete Python unit suite passes 1,887 tests. The focused PostgreSQL
  edition-creation and access-management API files pass 28 tests, including
  hostile caught-exception messages that remain absent from HTTP responses.
- Staff Console tests pass 20 of 20 and TypeScript typechecking succeeds.
- Its production Vite bundle succeeds and refreshes the checked-in static
  JavaScript with the encoded path boundary.
- Ruff formatting and ALL-rule lint pass all 642 files; strict mypy passes 356
  source files. Strict PyDocLint and semantic validation pass 363 production/
  tooling files, and documentation validation passes 269 Markdown files with
  202 requirement identifiers. A fresh warning-fatal Sphinx/AutoAPI build
  succeeds.

## Known limits

- Local tests cannot certify that GitHub has closed the CodeQL data-flow paths.
  A pushed replacement analysis remains authoritative.
- Five review threads are currently visible although the failed policy check
  contains seven annotations and the baseline contains twelve alerts. Resolve
  threads only after replacement analysis confirms the corresponding path is
  closed; do not equate a missing inline thread with a dismissed alert.
- The broader history/public-material audit and the push banner versus
  Dependabot-alert discrepancy remain separate public-readiness work.

## Smallest next actions

1. Publish the corrective commit to pull request 2 and inspect every replacement
   CodeQL result and alert state.
2. With explicit authorization, reply to or resolve the five verified review
   threads; do not dismiss any remaining alert without evidence and rationale.
