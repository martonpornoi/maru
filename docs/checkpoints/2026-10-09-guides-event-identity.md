# Guides approval event identities

- Date: 2026-10-09
- Status: Focused native routing/recovery and genuine restricted-runtime commands pass; browser and full certification remain open
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

## 2026-10-10: Native workflow continuation

After Announcements released local capacity, clean snapshot
`c49bb5bd5db05516a24dfde3fc12d317d18afb26` reached 42 passing native cases before
`test_later_same_transaction_coauthor_does_not_invalidate_previous_review` failed
because its `revise_guidance` call omitted the required `reason`. The target
coauthor invariant was not exercised; this is a fixture defect, not a successful
native result. The earlier existing-Announcements expansion case passed.

Pytest reported 419.64 seconds; the complete wrapper took 425.906 seconds with
unchanged source and exact owned-container removal. The full failed logs and
inventories remain in
`.tools/guidance-development/native-routes-20261009T222749Z-0c923f89/`.
Repair the caller without relaxing the production command, then rerun the selected
foundation, Knowledge domain and transition tests in a fresh owned database.
Recovery and genuine restricted-login/browser proof remain separate pending gates.

The fixture now supplies an explicit synthetic revision reason. An audit of 332
command calls found no other missing required arguments; all 44 real fixture
closures collect with zero setup or database calls. Scoped lint, formatting and
whitespace checks pass, and all 1,438 production files remain unchanged. The
original failed evidence and test-only repair freeze are retained; the corrected
native case has not yet run.

## 2026-10-10: Native and genuine restricted-runtime evidence

The corrected selection passed all 44 cases in `test_guidance_foundation.py`,
`test_knowledge_domain.py` and `test_guidance_transition_effects.py`: pytest
431.76 seconds, complete wrapper 438.062 seconds. The separate foundation and
Knowledge migration/recovery selection passed eight cases: pytest 350.78 seconds,
wrapper 357.156 seconds. Both before/after source inventories match and each
runner removed only its exact owned container. The earlier failed fixtures remain
preserved. These selections use the established owner-login native test harness;
they do not themselves establish a restricted-login boundary.

The successful native artifacts are:

- `.tools/guidance-development/native-routes-20261009T224358Z-4ce63004/`;
- `.tools/guidance-development/native-recovery-20261009T225211Z-30e55dbe/`.

A separate reviewed V6 fixture then provisioned a nonsuperuser migration owner and
the genuine `maru_runtime` login using the unchanged canonical ACL script. Actual
runtime probes passed all 25 constituent role/ACL flags plus the derived
current-session check. Knowledge, Guides foundation/authority and Announcements
owner/setup integrity were true; exact provenance was ready with zero blockers;
health returned HTTP 200. Django and migration checks passed. Real Identity
challenges, representation invitations and each person's acceptance established
separate synthetic Announcements and Guides-only scopes. The independently
accepted reader has current-copy permission and is denied the six private/write
Knowledge capabilities, Announcements and access management. No test authorizer,
raw authority grant or owner operational fallback was used.

The initial content helper committed synthetic rules, one draft and its review
request, then failed because it supplied `create_guidance.object_id` (the item)
as the revision ID. Its earlier self-review refusal used the same wrong revision
and is **not independence evidence**. The entire failed execution remains in
`.tools/guidance-development/genuine-runtime-continuation-20261010/execution/`.
No production source or existing row was repaired, erased or reset to hide it.

The separately reviewed recovery bound the sole retained pending item, exact
rules/control cursors, original authored content/date, one revision, three
receipts and zero reviews through authorized owner queries. It then exercised
self-review against the correct pending revision, proving unchanged working and
private evidence. The independently authenticated reviewer approved copy one;
the reader obtained that copy while a replacement draft and review remained
pending. A second independent approval made copy two current. Withdrawal removed
current reading, download and search while authorized retained history remained.
The reader's private draft/history/export access was denied throughout. Real
runtime/provenance/integrity probes passed before and after. This recovery passed
without source change; its 1,443 provisioned source hashes remained identical.

The Announcements edition remained `announcements_only@1`; its approved-copy
SHA256 remained
`6f361bbca987c721a5ee4979b9fdee82c6976fec54081311c2fe28bb03416f8f`.
It received no Guides activation or content mutation. The fixture's original
combined `verify-journey` was not invoked or counted. Successful recovery result,
completion, stages, runtime probes and source observations are retained in
`.tools/guidance-development/genuine-runtime-recovery-20261010/execution/`;
provisioning and seed results remain in `browser-fixture/` under the same parent.

The exact `maru-guidance-dev-20261009` container was stopped after this work; its
owned volume and synthetic accounts were retained, not removed. The recorded
web port is free and no running containers remain in the recorded check. See
`.tools/guidance-development/browser-resource-stop-20261010/result.json`.
All observations above are synthetic command-driven evidence. No authenticated
browser/human journey, combined browser expansion, complete accessibility,
production acceptance or full Guides certification is claimed. Credential entry
remains an unresolved browser boundary. Later checkouts inherit no native pins,
runtime approval or successful workflow claim from these local results.


The source-reviewed maintainer walkthrough now starts C without Guides access,
names the actual content-review screen and submission actions, and includes the
required change explanation plus separate replacement review request. Its existing
unrun status remains. Documentation references and scoped whitespace checks pass;
no additional unit, handbook or browser result is inferred from these prose edits.
