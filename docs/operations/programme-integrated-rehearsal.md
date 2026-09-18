# Programme setup-to-on-site rehearsal

**Audience:** Maintainers preparing #108, independent Programme evaluators and recovery operators\
**Outcome:** Prepare one reproducible journey and collect evidence for #109/#92 without confusing component delivery with acceptance\
**Status:** Preparation protocol; the complete fixture and setup are not yet implemented or accepted

## Entry conditions and authority

This protocol implements the acceptance plan for [#48](https://github.com/martonpornoi/maru/issues/48),
not a new product scope. Use the [setup contract](../product/page-contracts/programme-operations-adoption-setup.md),
ADR 0081, NFR-013, IDN-011/012, PRG-001 through PRG-011, SCH-001 through SCH-012,
OPS-009, INT-007 and UX-029 as the owning boundaries. Current status belongs in
[CURRENT](../project/CURRENT.md), not in a copied readiness percentage.

While ADR 0100 defers PostgreSQL, prepare fixture code, role scripts, assertions
and documentation, but do not collect or execute database tests. Mocked browser
observations remain component evidence. A fixture lease ending successfully is
cleanup evidence, not a successful journey. Do not enable the production profile,
add runtime grants, provision production keys or use personal data to make a demo.

Before executing final acceptance:

- pin the candidate commit, dependency locks, supported PostgreSQL image and
  exact isolated candidate profile/role definitions;
- restore required PostgreSQL verification under #102 and establish #97's
  supported logical-recovery procedure;
- provide an explicit opt-in launcher with a dedicated database, loopback URL,
  bounded lease and verified task-owned cleanup; **no complete integrated launcher
  exists yet**, so there is no launch command in this protocol;
- use real owning commands and permissions for acceptance, not an always-allow
  authorizer, direct status edits, disabled guards or fabricated approval;
- record synthetic scanner/signing/delivery adapters and their limits separately
  from any evidence obtained with real supported adapters; and
- preserve existing profiles and the unadopted product boundaries throughout.

Existing `tests/rehearsals/programme_*.py` files exercise individual components.
Some require PostgreSQL and synthetic authority substitutions. They must not be
launched during deferral or relabelled as the complete fixture.

## Prepare the fixture and distinct sessions

Fixture preparation starts with a closed test-only candidate definition: literal
capabilities, shell destinations, registered effect routes, versioned catalogs,
adapters, conflict sources and unchanged root-role codes. Do not derive its
authority by accepting every current or future capability in a module, or inherit
unrelated full-convention destinations/effects. Importing the candidate must not
register a runtime/selectable/persisted profile, mount routes, change model choices,
alter guards, open a database or create records. Validate it independently against
the owners' declared catalogs and the current manifest containment guards.

Prepared components live in `tests/rehearsals/programme_candidate.py`,
`programme_effects.py` and `programme_urls.py`. The candidate preserves the
Workforce/foundation pins and admits the explicit Programme owner adapters and
role recipes, without assigning those roles to anyone. Its independent Effects
registry uses the real internal-fact acknowledgement handler, not a notification
or invitation-delivery substitute. The joined URLconf includes all ten dormant
owner route modules plus the unchanged shared application routes. It changes
neither `ROOT_URLCONF` nor either current profile. Existing unrelated routes stay
available for denial probes; routing alone proves neither admission nor isolation.

Database-free tests check every included owner route for exact name, handler and
scope round trips, collisions and continued absence from current URLconfs. They
also validate catalog completeness, explicit exclusions and import purity. These
are preparation checks, not requests against a running server, native authority,
schema installation, genuine-person acceptance or P01–P12 results.

The eventual opt-in fixture must separately establish its disposable database and
actual approved runtime boundary. A test-only candidate object is neither a launcher
nor a migration, and does not satisfy P01–P12 by itself. Never launch it under the
deferred policy; retain explicit not-run status until restored acceptance.

Use repository-owned fictional convention names, synthetic people and reserved
example domains. Do not copy an actual convention roster. Provide one primary
organization with two editions and a second organization to exercise isolation.
The setup scenarios must cover a blank foundation, existing organization and
existing convention series. Reset scenarios in isolated databases rather than
rewriting immutable history to reuse one world.

| Session | Purpose and separation |
| --- | --- |
| Platform administrator | Provision foundations; never become a controller, member, host or volunteer. |
| Two accountable people | Accept their own invitations in separate sessions; reuse truthful existing representation where present. |
| Programme organizer | Configure a call or core item, readiness and deliberate host invitations. |
| Proposal lead and collaborator | Independently own profiles/consent and acknowledge the exact sealed proposal. Neither is automatically a host. |
| Reviewer, moderator and decision maker | Exercise exact assignments, field ceilings, recusal and independent decisions. |
| Planner, Venue owner and release approver/publisher | Use separately admitted owner tasks; preserve every required independent approval. |
| Volunteer and Workforce organizer | Own claim versus independent confirmation; neither becomes an attendee. |
| Room/Department operator, outsider and anonymous reader | Prove each output ceiling and denial, not just organizer success. |

Give each participant a role card with a goal, entry link and fictional inputs,
but no hidden identifiers or explanation of how to pass. Distinct sessions are
not themselves evidence of representative humans: #92 requires actual people.
Where one synthetic account holds several purposes, test each purpose separately
and prove one relationship does not silently grant another.

## Journey checkpoints

All rows below start **not run**. Record results against the exact candidate;
do not inherit a pass from a component PR. Repair failures through the owning
module and replay affected checkpoints, including downstream consequences.

| ID | Task | Required observable evidence |
| --- | --- | --- |
| P01 | Establish accountable setup | Blank/reused foundations, first Programme Department, two genuine-person acceptances, safe incomplete setup, no platform-administrator subject or excluded product state. Exact retries do not duplicate foundations. |
| P02 | Open a call and collaborate | Labelled call discovery, typed answers and private supporting file, independent collaborator profile/consent, seal/acknowledgement, submission and revision history without an attendee relationship. |
| P03 | Review and decide | Assigned field-limited reviewer access, conflict/recusal, moderation and accountable decision; no anonymous identifying lookup or private review leakage to hosts. |
| P04 | Prepare accepted and core items | Exact acceptance converts once; organizer-created core items need no fabricated submission. Readiness, working/delivery/discussion/public layers and host confirmation remain distinct. |
| P05 | Plan a timetable | Service days, occurrences and alternative drafts; explain room/combination, availability, capacity, setup/teardown, host, accessibility, staffing, overlap and rest conflicts. Pointer, keyboard and explicit forms preserve the same versions and commands. |
| P06 | Staff the work | Explicit demand becomes a Workforce-owned Shift; volunteer claims, another organizer confirms, and coverage locks. No other volunteer's private data or Participation is created. |
| P07 | Approve and publish | Current owner evidence, independent approval and atomic publication. Preparation failure leaves the prior release intact. Public, personal, room, Department, API, calendar and print outputs identify the same release. |
| P08 | Change published work | A reasoned successor retains history and previews retained work impact. Existing claims/confirmations are not silently rewritten. Notice preparation, independent review, manual handoff, failure and exact-recipient acknowledgement remain separate. |
| P09 | Operate on site | Now/next and run sheets expose only authorized current instructions and immutable release facts. Print includes scope, version, time zone and freshness/expiry warnings. No check-in or actual-time claim is inferred. |
| P10 | Lose connectivity or a dependency | Fail closed on partial/unavailable sources; use only the bounded read-only fallback. Independently trusted packs, expiry, newer withdrawal, lost history, reconnection and disposal behave as documented. |
| P11 | Export, recover and stop | Retain authorized history and archive evidence; restore a mutually consistent database/artifacts through #97's supported procedure and reauthorize reads. Stop-use prevents new work/access as contracted without erasing required evidence. |
| P12 | Verify isolation and excluded effects | Cross-organization/edition/role/object/field attempts disclose nothing outside scope. Compare owner-controlled baseline and final state/effect inventories: no Registration, Participation, payment, attendance, accreditation, catalog, charity, Logistics or general Communications side effects. |

P12 is an assertion at every relevant checkpoint, not just a final count. Absence
of a navigation link does not prove absence of writes, authority, jobs or effects.
Include wrong-tenant direct requests, revoked authority, stale versions, exact
retries, unavailable dependencies, rollback and empty/overflow responses. Retain
both positive and denial/audit evidence without logging private answer contents.

## Human and accessibility session (#92)

Prepare a short participant script from P01 through P11. A representative organizer
and distinct host/volunteer must complete their own tasks without developer
narration. Record misunderstanding as a defect, not a pass after explanation.
Ask participants to explain private versus public content, incomplete readiness,
approval versus publication, retained Shift commitments, and fallback freshness.

Rehearse the newly connected paths with a representative screen reader, keyboard
and visible focus, semantic labels/errors/status, native discard/leave dialogs,
and genuine browser 200% zoom. Include empty, validation, denied, stale,
dependency-failure, review, release, read-only and degraded states. Check relevant
surfaces at 320, 390, 768, 958, 1024, 1280 and 1920 CSS pixels, long content,
print pagination and scope warnings. CSS widths are not native zoom evidence.
Automated accessibility scans complement, but never replace, these observations.

Reuse valid unchanged #87 observations. Recheck only materially changed paths and
record why. Preserve the maintainer's disabled Windows Animation effects; do not
change personal browser/OS settings without permission. Include #92's notice,
private-file and continuity follow-ups and obtain independent operational-owner
acceptance. Assistant-operated synthetic roles cannot supply this acceptance.

## Evidence record and completion

For each checkpoint retain: candidate commit, fixture/environment identity,
role/session purpose, initial state, exact action, expected result, observed
result, pass/fail/not-run, evidence location and linked defect. Record adapter
substitutions, source versions, release identifiers and fixture limits. Do not
put passwords, invitation tokens, signing keys, private files or raw personal
answers in public issues, logs or screenshots.

Use separate evidence labels:

- **Preparation:** protocol, fixture implementation or assertions exist; no execution implied.
- **Component:** isolated or mocked checks; no native or integrated acceptance implied.
- **Native automated:** exact-head PostgreSQL reports and unchanged coverage/timing gates under #102.
- **Recovery:** supported logical restore plus weakened-guard negative tests under #97.
- **Human:** observed representative-person/screen-reader work under #92.
- **Integrated:** complete joined evidence and failure/recovery/stop-use proof under #109.

Protect failed-attempt records and relate repairs to their tested revisions. A
later commit needs fresh appropriate evidence; do not copy an earlier receipt.
After the session stop only verified fixture-owned processes/resources, dispose
of private synthetic downloads according to the fixture recipe, and verify
unrelated worktrees, containers and browser preferences are untouched.

Close #109 only when its native, recovery and human prerequisites and this joined
journey pass. Then deliver #108's separately verified profile promotion through
the protected PR flow. Close #48 only after its complete delivery decomposition
and integrated checklist are supported by evidence. This protocol, a green
documentation PR, or successful component tests complete none of those gates.
Production infrastructure, provider provisioning, privacy/safeguarding, training
and operational go/no-go remain separate from repository Programme completion.
