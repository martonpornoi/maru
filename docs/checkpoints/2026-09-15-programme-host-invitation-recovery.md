# Exact-person Programme host invitation recovery

Date: 2026-09-15. Candidate on `codex/programme-host-invitation-recovery`, based
on protected PR #127 (`33d8391315dbbf8cdacd1daac557c55b9f901c33`). This is a
bounded, previously recorded #108 follow-up within #48, not umbrella completion.

## Outcome and contract

Initial hosting invitations now require exact-address selection preview followed
by deliberate confirmation. The existing Identity identifier-only query runs
once during currently authorized, locked and audited preparation. A purpose-signed
person identifier and normalized-intent digest bind actor, organization, edition,
item, original version/retry, selector, role, host-visible copy and private reason.
The proof contains no copied email or private text, grants no authority, follows
configured signing fallbacks and adds no arbitrary expiry.

Confirmation verifies the original selection without email resolution, then
calls the unchanged canonical invitation command before fresh private/roster
reads. Mutable or reassigned email cannot retarget that original confirmation.
Current actor/tenant/adoption admission is mandatory; the owner retains fresh
manager/person/state checks when there is no original receipt. An original
receipt supplies only historical result identifiers/versions and no current
hosting or consent. Optional roster navigation has separate current read/audit
admission; losing it preserves the admitted minimal result.

Stale/unavailable requests preserve original proof, version, retry, selector,
copy and confirmation. Missing or invalid proof, including legacy forms, cannot
reconstruct a target from today's address or fabricate success. Inspect retained
history before choosing new intent; re-preview is explicit and never silently
rotates the retry key. Reinvitation still selects the retained roster person.

PRG-005/006/008, IDN-014, UX-013/029, NFR-013 and ADR 0087 remain authoritative.
Requirements, owning page/module/recovery guidance and changelog were updated.
No migration, runtime permission, owner writer, profile, production route,
directory, account creation, email delivery or CI policy changed.

## Verification performed

- Complete inexpensive database-free preflight: 7,279 passed in 56.50 seconds;
  three existing Django URLField warnings. Two final render-revocation tests
  were then added; the focused host suite passed 135 cases in 1.81 seconds.
- Real forms/signing, minimized required audit, locked/final denial, no address
  lookup on confirmation, actor/tenant/item/intent binding, malformed/tampered/
  wrong-purpose/oversize proof, old-key fallback with an aged proof, explicit
  re-preview, missing proof, original canonical replay before fresh reads,
  optional-read loss, final render revocation and unchanged owner transport.
- Focused Ruff, strict typing (five source files), NumPy and semantic docstrings
  passed. Initial test-fixture snapshot/textarea assertions and a tuple annotation
  were corrected before certification; no acceptance gate was weakened.
- Synthetic loopback browser used actual Django forms, signatures, templates,
  CSS and JavaScript with stub owner/authorization boundaries. Database access
  was forbidden and fixture-only CSRF bypass explicit (HTTP tests retain real
  CSRF enforcement). Observed blank deliberate input, separated host/private
  preview copy, focused stale alert with preserved values/checkmark/version,
  minimal original receipt without private roster continuation, and generic denial.
  At 1280 CSS pixels the document measured 1265 pixels, with one H1/main and no
  page overflow. The receipt screenshot was visually inspected. Owned tabs and
  the synthetic server were stopped afterward.

Clean exact-commit certification and independent hosted protected acceptance
are pending at this snapshot. These focused/browser results are not a native
database, full accessibility, human-owner or production-readiness claim.

## Retained debt and next steps

The existing `test_guided_forms_preserve_real_host_versions_and_local_minute_intent`
in `tests/integration/test_programme_hosts.py` now prepares and verifies the real
selection, changes a synthetic person's email and assigns the old address to
another synthetic account before confirmation, then asserts original-person
ownership and canonical replay without a duplicate revision. It is maintained
but neither collected nor run under ADR 0100; #102 must execute it with full
native/runtime/concurrency/coverage/measured-budget acceptance. No timing weights
were invented. Human/assistive/zoom/reduced-motion checks remain #92.

Certify this clean candidate, obtain its exact-head PR gate/CodeQL acceptance,
merge normally and synchronize main. Continue the remaining #108 structured
selectors/viewers, workflow connections and accountable setup. #102, #97 logical
restore, #109 integrated journey and #92 human evidence remain final gates
before Programme promotion and #48/#108 closure.
