# Named Programme reviewer management

Date: 2026-09-14. Issue: #108 within #48. Candidate, not protected delivery or
activated Programme Operations. Base: PR #122's protected squash
`91e02f4633b497b7bd00f93aeb609cb344ccfb0e`.

## Bounded outcome

Applications now supplies dormant exact-Department case discovery/overview,
complete retained named rosters, known-email preview, exact-person assignment
confirmation and reasoned removal. Independent `review_context` admission does
not inherit setup fields, answers or private review evidence. Setup and opening
receipts separately test their manager continuation; manager setup links have
their own `review_setup` check. Current source, roster and selected-person labels
are verified before and after rendering, including refreshed removal state.

Identity owns exact-email normalization and bounded current person labels. A
purpose-signed identifier-only selection binds original actor/scope/case/person/
version/retry, not email or cached name. Confirmation never resolves email again.
Inactive retained people have a neutral label without preempting canonical
old-receipt replay. Signature purpose, tampering, key fallback and lost-key
recovery are documented and tested; the selection is not authority. Existing
writer exclusions, source/planning/version locks, audit, transaction and replay
rules are unchanged. No reviewer capability, email/invitation, host or volunteer
record is created. All historical assignment stages/states remain visible;
removal is explicit and preserves original evidence.

PRG-003/004, QRY-005–008, AUD-001 and UX-005–008/029 map this work to ADR 0085;
ADR 0100 continues to defer PostgreSQL execution. Owning page, Applications,
Identity, API, recovery, requirements, changelog and CURRENT documentation changed.
No schema, migration, profile, runtime privilege, production route, dependency,
CI policy or invented test-timing weight changed.

## Verification and corrections

- Full inexpensive unit preflight: **6,887 passed in 42.24 seconds**, three
  existing Django URLField transition warnings; no database tests collected.
- Focused tests cover complete bounds/labels/fields, all retained exclusions,
  scope before Identity access, mandatory audit, signed original intent and
  fallback keys, real forms/CSRF/closed transport, independent navigation,
  original replay after lifecycle/person changes, late removal, refreshed state,
  denied/dependency/render-race behavior and safe headers/unmounted routes.
- Ruff, focused strict typing, NumPy and semantic docstring checks pass. One
  form transport mismatch found by the first focused run was corrected by
  explicitly allowing only its already-validated action control. A synthetic
  policy fixture initially used the typed policy as a dictionary; it now uses
  the actual JSON-compatible representation. No acceptance threshold changed.
- The canonical clean-commit local gate and exact-head GitHub acceptance are
  still required; this checkpoint claims neither yet.

## Synthetic browser evidence and limitations

The real HTML/forms/shared assets ran at 1280 CSS pixels with owner/auth/command
stubs and every database connection forbidden. Fixture-only CSRF bypass is not
production behavior; real CSRF rejection is tested by HTTP units. Observed:
labelled case discovery, all four retained assignment states, preview without
assignment, explicit reason/confirmation and receipt, prior-stage removal with
409 recovery retaining visible reason/checked confirmation and focusing the
error, read-only context without new actions, and generic denied text without
names. Confirmation/stale pages had one H1/main and document width 1265 against
viewport 1280. A screenshot was visually inspected. Task-owned two tabs and
fixture server were closed/stopped; no unrelated browser/service was changed.

This is not database persistence, genuine multi-person review, comprehensive
keyboard/accessibility, console, full-width, real zoom or screen-reader evidence.
Those remaining human checks are explicit #92 debt. Original hidden intent
binding is HTTP/unit evidence, not inspected hidden browser state.

## Maintained native debt and next steps

One new scenario in the existing review-services integration file maintains
real contributor/opener exclusion, exact-email preview and changed-email/person
binding, assignment/clearance/scoring, independent moderation/decision, late
removal, complete retained roster, inactive-person fallback and original receipt
recovery without another version increment. It is **unexecuted #102 debt**;
no new file/timing weight or PostgreSQL collection/execution was introduced.

After protected delivery, continue #108's separately authorized reviewer,
moderator, decision and accepted-conversion tasks, reference/file choices,
connections and accountable setup. #102 restoration, #97 logical recovery,
#109 integrated and #92 human acceptance remain mandatory before final promotion;
this component does not close #108 or umbrella #48.
