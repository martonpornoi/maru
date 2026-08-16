# Page 10 registration definition builder

Date: 2026-08-03

This checkpoint records the governed Page 10 definition-builder milestone. It
is a focused working-tree result, not a production deployment or a claim that
the complete Page 10 journey is finished.

Independent adversarial release review is complete for this builder boundary.
The reviewer reproduced the previously reported graph/replay defects, verified
their fixes against the command, browser, API, activation-validation, and
receipt contracts, and records the focused builder as **STABLE**.

## Outcome

- The shared administration shell now exposes record-oriented question,
  admission-product, minor-policy, and profile-extension-definition workflows.
- Question and product definitions support create, complete update, bounded
  move, and dependency-safe non-cascading removal.
- Minor policy supports create/update and explicit removal while attributing
  review evidence to the actual actor and server time.
- Profile-extension definitions support create, draft update, bounded ordering,
  and retirement. The catalog projects definitions only and never attendee
  values.
- The canonical v1 configuration-command endpoint accepts closed section,
  question, product, and minor-policy discriminators. The profile catalog and
  field-command endpoints share the same commands as HTML.
- API mutations require a canonical UUID `Idempotency-Key` header and reject a
  JSON retry key. Browser mutations use server-created hidden UUID retry keys.
- Authorization is resolved before form or JSON parsing, then repeated under
  the exact locked organization/series/edition/setup scope.
- Every successful mutation advances the optimistic setup version and commits
  its retry receipt, minimized audit, domain event, and outbox evidence in the
  same transaction.
- Question commands and activation now use one condition-value compatibility
  helper. Scalar conditions reject multiple-choice sources, integer conditions
  accept only canonical signed 32-bit values, and both exact boundary values
  remain valid.
- Minor-policy replay derives the historical target and action from immutable
  receipt evidence, including after the live policy has been removed. An exact
  retry returns the original result; changed intent under the same key returns
  the documented retry conflict.
- OpenAPI exposes one exact closed discriminator mapping per command variant
  and declares the required `Idempotent-Replay` response header for every
  successful response shape.

## Schema and recovery

Registration migration `0033_page10_definition_command_actions` adds receipt
actions for minor-policy creation/removal and profile-field movement, and makes
minor review-evidence fields form-optional so a disabled policy can truthfully
carry no review evidence. The migration has no data rewrite. A historical-state
test proves the exact receipt choices and form-state flags before, after, and
after reversing `0033`.

## Verification

- The final unique fresh-PostgreSQL focused matrix passes all **48 tests in
  106.01 seconds**. It covers setup HTML, definition HTML/API/commands, exact
  `0033` forward/backward schema state, setup-start, and section commands.
- A separate compact fresh-PostgreSQL concurrency probe passes **1 test in
  29.04 seconds**. Same-version writes with different retry keys produce one
  commit and one exact version conflict; simultaneous same-key writes produce
  one result plus one replay, one receipt, one question, and one aggregate
  advance.
- The condition matrix rejects a multiple-choice source, `-0`, and values
  outside `-2147483648` through `2147483647`, while accepting both exact signed
  32-bit boundaries through the shared rule used by activation.
- The minor-policy matrix replays create and remove after deletion and rejects
  changed create/remove intent under either retained retry key.
- Runtime OpenAPI contract tests prove exact closed discriminator mappings and
  replay headers. Schema generation validates with **0 errors** and seven
  pre-existing enum-naming warnings.
- Repository-wide Ruff lint passes; the changed builder boundary also passes
  Ruff format checking. Strict mypy passes across **255 source files**.
- Django reports no migration drift. Documentation validation passes for **186
  Markdown files and 198 unique requirement identifiers**; `git diff --check`
  is clean. Development correctly warns that invitation delivery remains
  fail-closed without deployment keys.

These focused invocations overlap and are not a repository-wide release or
coverage claim.

## Known limits and next boundary

- Preview and immutable configuration activation remain separate work.
- Profile-definition approval, activation, successor creation, and explicit
  supersession remain separate commands required by ADR 0047.
- Compatibility configuration draft/activation and profile-value APIs still
  need reconciliation before old writers can be retired.
- Django model-admin and other repository-owned direct writers have not yet
  passed the stopped-writer cutover.
- Authenticated desktop/390-pixel visual QA, keyboard/screen-reader evidence,
  and the complete denied/stale/dependency state matrix remain open.
- Production cutover still requires runtime-role proof, representative
  backup/PITR rehearsal, owner tutorial rehearsal, and the other gates in
  `docs/project/CURRENT.md`.
