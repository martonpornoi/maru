# Guides approval event identities

- Date: 2026-10-09
- Status: Identity repair passed initial native cases; transition routing repair in progress
- Requirements: EVT-008, KNO-012, KNO-013
- Contract: [ADR 0119](../architecture/decisions/0119-guidance-adoption-and-purpose-authority.md)

A fresh workflow run passed the previously failing setup-readiness boundary,
then failed on the first controller decision: the proposal had already occupied
the request aggregate's version-one slot. Responses and application incorrectly
reused that slot. Staff access responses had the same producer/native-guard
pattern. The retained run is `native-first-20261009T171907Z-9025416b.log`;
pytest took 203.15 seconds and the wrapper 205.297 seconds. Its exact owned
container was removed. This fixture substitutes only the runtime-role probe;
it does not establish a genuine restricted-login boundary.

Proposals now retain their own request identity. Every actual decision and
activation receipt uses its own canonical type and row ID, at version one.
Access decisions use their own identity; revocation already did so. Matching
Events 0023 and Authorization 0046 guards retain the same event names, closed
payloads, exact actor, scope, correlation, source audit and internal outbox.
The owning transaction and replay behavior remain unchanged.

Seven original implementation files and the failed native log were preserved
with verified hashes before repair. Only normalized owning migration-source pins
changed; observed relation/helper fingerprints remain unchanged. The prior
Events execute-ACL repair stays in place.

Forty-eight focused units pass in 1.52 seconds. Five-file strict typing, Ruff,
formatting, Python documentation and scoped whitespace checks pass. Native
assertions now inspect both controller decisions and the final receipt, and
access acceptance/decline, revocation and exact replay. They await the fresh
workflow run; full certification, restricted-runtime and browser acceptance
remain separate gates.

## Native follow-up

The next fresh run passed nine cases, including the formerly failing two-person
ceremony, then failed when expanding an existing Announcements edition. The
pre-adoption proposal event was absent from its immutable old profile's allowed
routes. Pytest reported 303.01 seconds; the wrapper took 305.219 seconds. Log
`native-first-20261009T173303Z-cd411c30.log` is preserved and its owned container
was removed. Later access-decision parameter cases and Knowledge cases did not
run. Earlier passes do not certify the remaining workflow.

[ADR 0124](../architecture/decisions/0124-evidence-bound-adoption-transition-effects.md)
contracts a narrow retained-evidence route without changing any profile meaning.
Source implementation and negative routing regressions are in progress. Native
capacity is now owned by fresh Announcements certification; no overlapping Guides
fixture or acceptance run is active.

## Routing source verification

The closed transition route and complete original identity now reach all four
Effects gates. Ninety-four focused units pass in 0.88 seconds; scoped typing,
lint, formatting and Python documentation pass. Independent review found no
additional production defect, but caught a missing fixture import in the new
native regression. The actual pytest fixture manager reproduced that failure;
the repaired closure resolves the existing real fixture and its dependencies
without running any fixture setup or database connection.

The native expiry/delivery/replay case is prepared, not executed. It stays a
current-schema case with the conservative unmeasured timing fallback; no
historical group or measured provenance is invented. Eight original application/
test hashes bind the reviewed source; only the native fixture wiring changed
between the preserved first and second freezes. Complete combined source feedback
and all pending native gates remain required.

The integrated repair passes all 14,156 database-free cases in 121.41 seconds
(wrapper 127.859 seconds), retaining three existing Django URL-field warnings.
Strict typing passes 881 source files; Ruff/formatting, both Python documentation
gates, 728-file documentation references and whitespace checks pass. Exact
before/after source inventories match. These results cover the repaired inherited
empty-observation unit assumption and the main-path certification-runner repair.
A fresh warning-fatal handbook build is next; native, restricted-runtime and
browser acceptance remain pending.
