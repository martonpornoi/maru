# Rehearse the Workforce-only journey

**Audience:** A technical facilitator, two accountable operators and a volunteer
**Outcome:** Create one responsibility, independently assign a volunteer, share
availability, and complete one short planned Shift without attendee records
**Status:** Current-source procedure and regression checks under validation;
the preserved earlier human trial stopped at recipient-owned password entry.
No complete new browser journey or final absence report is claimed.
**Last updated:** 2026-11-01

This is the canonical synthetic walkthrough for
[issue #42](https://github.com/martonpornoi/maru/issues/42), following evaluation
[#29](https://github.com/martonpornoi/maru/issues/29). Positions, Assignments,
Availability and Shifts are implemented. This exercise does not accept production
use, the continuity package in #22, the accessibility matrix in #23, or attendance
and actual-time recording in #24.

## Before opening the first form

From a source checkout with Docker and the locked Python dependencies installed
(`uv sync --locked --all-groups`), use this dedicated launcher. Run these commands
from the repository root. The directory must be new and underneath `.tools/`.

```powershell
uv run --locked python -m scripts.rehearse_workforce_browser start --directory .tools/workforce-rehearsal-01 --port 8766 --check
uv run --locked python -m scripts.rehearse_workforce_browser start --directory .tools/workforce-rehearsal-01 --port 8766 --minutes 120
```

The first command checks prerequisites and creates nothing. The second creates
one owned PostgreSQL 17.11 container at its recorded digest, applies real current
migrations with a migration owner, provisions the checked-in restricted runtime
role, bootstraps only the platform administrator, and activates exact authority
provenance and the synthetic invitation-retention policy. It runs the real
invitation delivery, expiry and retention commands in a separate child process;
only that worker receives the delivery private key. Local letters go to
`mail.private/` inside this run directory; no real mail is sent. Ordinary people
are invited through the interface below; no organization or Workforce activity
is seeded.

Wait for **Ready**. Open the printed `http://127.0.0.1:8766/admin/` address. Read
your local `bootstrap.private.json` privately for the generated platform login.
Do not paste the password or invitation letters into evidence, a PR or a shared
chat. All `.private` material and web logs are sensitive local working files.
Keep the directory accessible only to the facilitator, and remove its private
material when no longer needed. The launcher retains reports and logs after
normal database cleanup so failures can be investigated.

The launcher refuses a reused directory or an already running container workload.
It creates `source-before.json`, `resource.json`, a passed read-only `before.json`
and `ready.json` before offering the site. These record the actual source inventory,
commit and database image identity. Keep the source unchanged during the exercise.
A populated demonstration or old rehearsal volume is never reused. The automatic
lease is at most 240 minutes; `Ctrl+C` or an empty `stop` file in the run directory
ends it earlier. Normal cleanup stops its web process and deletes only its labelled
database/container volume; it never prunes unrelated resources.

This is HTTP-loopback source development, not OCI, TLS or production acceptance.
It uses the strict base application settings (including password reauthentication,
exact authority and closure guards), with local file delivery and Django's
`--insecure` static-file serving only. No security checks are silenced. For an
OCI evaluation, use the separate
[exact-image runtime](synthetic-oci-runtime-rehearsal.md) and
[static/browser delivery](synthetic-oci-static-delivery-rehearsal.md) procedures
with the actual candidate image, rather than treating their historical defaults
as proof of this revision. Record which environment you actually used.

Use a dedicated database, not a populated convention demo or any
preserved rehearsal volume. Do not run a populated browser fixture alongside the
full PostgreSQL acceptance pool. Keep the site's declared lifetime long enough
for the exercise and its final checks. Do not extend it by disabling cleanup.

Use only fictional names and reserved addresses. Generate private temporary
passwords; this guide deliberately supplies none. Invite ordinary accounts
through **User accounts → Invite a user account**, then have each recipient
use the private invitation code and **Activate account** to choose their own
password. The facilitator supplies only their own synthetic local invitation
delivery; no real mail provider or copied roster is needed. Arrange for the
recipients to complete password entry and the role handoffs within the fixture's
lease. If an automation tool requires human credential entry or an authority
confirmation, record that boundary and hand off the exact form; account seeding
is not a substitute for this journey. Stop if delivery or
verification is unavailable. Do not set verified flags or authority in a database
shell. Do not retain codes, passwords, cookies or request bodies as evidence.

| Actor | Synthetic account | Session and responsibility |
| --- | --- | --- |
| Platform administrator | Environment's privately supplied bootstrap login | Separate browser profile; creates the workspace, invites and activates its operators; does not become a convention member. |
| Operator A | `workforce-alex@example.invalid` | Separate ordinary person account; proposes the responsibility and plans work. |
| Operator B | `workforce-blake@example.invalid` | Another ordinary person and browser profile; independently reviews and approves A's proposal. |
| Volunteer | `workforce-casey@example.invalid` | Separate ordinary person account; applies, owns Availability and claims their own Shift. |

For a human rehearsal, A and B are different people, not one person using two
logins. Assistant-operated or automated account switching is synthetic software
evidence only. It does not establish two-human or representative-owner acceptance.
If using one browser for software checks, sign out fully before each handoff and
confirm the newly signed-in account; multiple tabs share a session. Never reuse
another role's CSRF token or impersonate it through a database connection.

Keep a small private run sheet with the origin, source/image identity, date,
`Europe/Budapest` time zone, actor labels, actual generated organization/series/
edition slugs, and relevant object links. Copy links from the interface; do not
guess UUIDs. This information is fixture evidence, not authority.

## Core journey

Each row gives the starting state, actor, action, expected visible outcome and
minimal evidence. Record an actual result for every row; do not pre-check it.
Reasons below are fictional operational explanations, not personal information.

| Step | Start and actor | Action and copy-ready input | Expected result and evidence |
| --- | --- | --- | --- |
| 1. Workspace | Platform administrator; no exercise organization | Open **Settings → Set up a volunteer team** (the same link is on the platform home). Choose **Create organization, series, and edition**. Organization: `Synthetic Cedar Volunteer Team`; convention: `MaruCon Cedar`; edition: `MaruCon Cedar rehearsal`. Set dates to today through tomorrow in `Europe/Budapest`. Submit **Set up a volunteer team** once. | One Workforce-only edition and a provisioning operator representation. Save the exact edition link and profile label. No attendee or payment setup is implied. |
| 2. Invitations | Platform administrator; both ordinary operator accounts active and verified | In **Representation & access**, invite A and B by their exact addresses. Reason: `Accountable operators for this synthetic Workforce rehearsal.` | Each invitation is Invited; neither person has operator authority yet. Record status only, without private delivery material. |
| 3. Self-acceptance | A, then B, in their own sessions | Open **My governance invitations** at `/admin/invitations/`; open this organization and **Accept invitation**. | Each sees only their own invitation and becomes Accepted. Record the two actor handoffs. Acceptance alone does not activate authority. |
| 4. Activation | Platform administrator; both invitations Accepted, none outstanding | Return to **Representation & access**. Confirm the exact organization name and activate its operator representation with reason `Activate the accepted independent rehearsal operators.` | Organization and operator representation Active. Both exact people have the reserved operator role; the platform administrator is only an activation actor. Retain the displayed result. |
| 5. Structure | A; exact Workforce-only edition selected | Follow **Organization structure**. Create Department `Welcome desk`, description `Help fictional volunteers find their first task.`, no parent, reason `Create one bounded rehearsal team.` | One active Department. Record the Department link. Do not copy a whole convention chart for this one-Position exercise. |
| 6. Safe starter | A; active Department and no compatible published template | In **Positions**, ask B to review the proposed basic visibility meaning. Use **Create the safe Volunteer starter**, B's exact **Independent approver email**, and reason `Use the reviewed basic volunteer meaning for this rehearsal.` | Published Workforce volunteer template, with basic event and structure visibility only. No person has received this role yet. Record the template name/version, not a claimed separate approval screen. |
| 7. Position | A; published starter available | **Create Position**: template `Workforce volunteer`, Department `Welcome desk`, title `Welcome desk helper`, purpose `Welcome fictional volunteers and explain where to report.`, headcount `1`, no reporting Position; reason `Plan one helper responsibility.` | Position and its private draft opportunity. Record the Position link and Draft opportunity state. Creation is not an assignment. |
| 8. Opportunity | A; Position draft | On Position details set **Publication status** to Published, headline `Help at the fictional welcome desk`, description `Practice one short welcome task with the rehearsal operators.` Leave optional opening/closing times empty for this bounded exercise; save with reason `Open the synthetic volunteer opportunity.` | Position Open and opportunity Published. Copy its public Volunteer link. No application or authority is created merely by publishing. |
| 9. Application | Volunteer; no assignment | Open the copied Volunteer link, choose **Apply**, enter `I would like to practice welcoming fictional volunteers.`, and **Submit application**. | Application submitted. Record its visible status. This Workforce-owned application is neither attendee Registration nor broad Participation and grants no assignment or access by itself. |
| 10. Proposal | A; submitted application provides the candidate relationship | On **Assignments**, choose this Position's **Propose a person** and Casey from the relationship-bounded list. Keep an effective start at or before the later Shift and a bounded end tomorrow; reason `Propose the applicant for the short rehearsal responsibility.` Submit **Record proposal**. | Proposed assignment, reserved headcount, and **Waiting for another controller**. No activated role yet. Copy the assignment link for B. If Casey is missing, inspect the application and exact edition; do not add arbitrary membership or a raw account ID. |
| 11. Independent decision | B; exact proposal still current | Open that assignment. Check the Position, person, interval and onboarding requirements. Complete ordinary password reauthentication if requested, then return to the form, reload current state, enter `Independently checked the rehearsal responsibility.`, and **Approve and activate**. | Active assignment and retained independent decision. The actor must be B, not A. Do not bypass incomplete onboarding; this starter should not require invented documents. Volunteer can see their own assignment in **My Workforce**, without the private approval reason. |
| 12. Private Availability | Volunteer; active assignment | In **My Workforce**, open **Availability**. Add one Available period covering the remaining rehearsal today; choose **Save private draft**. | Volunteer sees their draft. A's **Workforce availability** says **Not shared** and must not disclose its times. Record both observations separately. |
| 13. Share deliberately | Volunteer; private draft retained | Reload the same period and choose **Share with organizers**. | Shared plan and version. A now sees the submitted period in the edition's time zone. Sharing is planning input, not a scheduled commitment. |
| 14. Plan short work | A; shared Availability covers the planned slot | Follow **Shifts**, then **Create a Shift**. Use the timing recipe below. Name `Rehearsal welcome`; location `Fictional welcome desk`; People needed `1`; Break minutes `0`; Required rest `0`; work `Practice greeting one fictional volunteer.`; reason `Plan one short synthetic exercise.` Choose **Create draft**. | Private Draft demand with exact Position, local times and one place. Record the Shift link and end instant. No claim exists. |
| 15. Open | A; future-ending Draft | Review the exact interval and **Open claims**, reason `The short rehearsal is ready for claims.` | Open demand; no confirmation yet. |
| 16. Claim | Volunteer; exact active Position, shared covering Availability | In **My Workforce → My shifts**, find **Suitable open work** and **Claim this Shift**. | Claimed, awaiting organizer confirmation; own instructions visible, other people's records and organizer reasons absent. |
| 17. Confirm | B; current claim by Casey | On the organizer Shift detail open **Review claim**, reason `Confirm current assignment and shared Availability.`, then **Confirm commitment**. | Confirmed commitment, with current suitability. An organizer cannot confirm their own claim. If Availability changed, review and reconfirm instead of editing evidence. |
| 18. Lock | A; all required coverage Confirmed and current | Enter `Lock the complete rehearsal coverage.` and **Lock confirmed coverage**. Leave the underfilled-coverage exception unchecked. | Locked demand with one confirmed place. Record the state and complete coverage. |
| 19. Complete | A; Locked and its actual end time has passed | Reload. Under **Complete ended work**, enter `The scheduled synthetic exercise has ended.` and **Complete Shift**. | Demand and confirmed commitment Completed. Volunteer sees retained completion. This is planned-work completion, not attendance or actual hours. |
| 20. End responsibility | B; completed Shift and active Position assignment | On assignment details open **End assignment and authority**, complete normal reauthentication if requested, reason `The bounded rehearsal responsibility ended.`, then **End assignment and revoke authority**. | Ended assignment and revoked role retained in history. Volunteer still has their own minimized record. Do not delete the person or alter past evidence. |

Use the actual generated names when a collision changes a slug. A field error,
permission denial, stale version, unavailable policy or missing dependency is a
stop at that step. Retain the safe message and request reference, reload, and
resolve the stated prerequisite. Do not edit hidden retry keys/versions or repeat
an uncertain mutation blindly. An interrupted run remains incomplete.

## Timing recipe: reach completion without time travel

Create the edition for today's local date through tomorrow. Do not use a fixed
future year and then backdate completion. Set the assignment start no later than
the planned work and its end after it. Before step 14, read the current minute in
the edition's time zone and write it as **T** on the run sheet. Choose start
**T + 10 minutes**, end **T + 12 minutes**, and a shared Availability period that
covers both. Allow more lead time if two people need it. Keep the slot within
the edition dates and assignment interval; avoid an ambiguous DST transition.

Finish opening, claiming, confirming and locking before the chosen start. If that
cannot be achieved, cancel the uncompleted demand with an honest reason and make
a new future draft; never rewrite a published interval. Wait until the recorded
end instant, reload and complete. Before the end, the page should explain that
completion is not yet available. Waiting uses the ordinary clock: no system
clock change, SQL timestamp edit, patched browser time or production backfill.
Unit tests may use controlled clocks; that is a different evidence category.

## Expected denial and safe recovery

In the Volunteer session, open the organizer Shift link copied in step 14.
The expected result is a non-disclosing denial, with no organizer roster,
private reasons or planning controls. Return to **My Workforce → My shifts**
and confirm the volunteer's own view still works. Record the actual response;
do not claim a friendly recovery page if the current route gives a plain 403.
Do not change the account's permissions to make the denial disappear.

Both operator and platform oversight must also respect the immutable
Workforce-only boundary. Registration, payments and unrelated module links must
remain absent. Empty menus alone are not database absence evidence.

## Technical absence check

The facilitator checks the exact dedicated exercise database before step 1 and
after step 20. Record only model names/counts and the scoped assignment facts,
never row contents or credentials. Use the already authorized local inspection
connection; do not grant the runtime login broader privileges to run a check.
Stop if the database contains unrelated fixtures; global-zero checks are valid
only for this empty, dedicated run.

Inspect all models owned by unadopted modules from the current
`workforce_only@1` profile, including Registration/payment/attendance,
Participation and its capacities, Applications (the separate module),
Accreditation, Programme/Scheduling, Catalog, Charity, Communications,
Announcements, Guides, Venues and Logistics. Account, organization, edition,
authorization, audit/effects and Workforce records are expected foundation data.
The safe record is a before/after model-count inventory, not a database dump.
If any unadopted model has a new row, record a failure and inspect its owner;
do not delete the row to produce a pass.

For Casey's exact organization, edition and Position, also verify:

- the retained PositionAssignment is Ended;
- its linked RoleAssignment is revoked;
- `participation_capacity_id` is null;
- exact-person/exact-edition Participation and ParticipationCapacity remain zero;
- one Workforce VolunteerApplication exists for the opportunity;
- the planned ShiftDemand and Casey's ShiftCommitment are Completed; and
- the platform administrator acquired no convention membership, Position
  assignment, Participation or volunteer role as a side effect.

Use the repository's read-only inspector from the same checkout and authorized
inspection environment. It enforces a PostgreSQL read-only, repeatable-read
transaction and a per-statement time limit. It derives every unadopted model,
including implicit relationship tables, from the exact current adoption catalog.
It reads no account password field and emits no email, name, private reason or
database connection string. It never changes privileges or repairs data.

For another already authorized environment, before creating the organization,
replace the platform address with its actual reserved synthetic address, then run
the direct command below. The dedicated launcher already saves this baseline;
use its final wrapper at the end of this guide instead of configuring credentials
again.

~~~powershell
uv run python scripts/inspect_workforce_rehearsal.py baseline --confirm-dedicated-synthetic --platform-email platform@example.invalid --output .tools/workforce-before.json
~~~

After step 20, use that same address and the exact edition UUID copied from the
Volunteering link:

~~~powershell
uv run python scripts/inspect_workforce_rehearsal.py final --confirm-dedicated-synthetic --platform-email platform@example.invalid --edition <actual-edition-uuid> --volunteer-email workforce-casey@example.invalid --baseline .tools/workforce-before.json --output .tools/workforce-after.json
~~~

Create the output directory beforehand if necessary. Existing report files are
never overwritten. A successful report has **status: passed**; final inspection
also requires a passed baseline with the same random bootstrap account binding,
checker/catalog identity and complete zero inventory. It requires one exercise
organization, edition, Position and assignment, one completed demand and its
completed commitment; cancelled timing attempts are allowed. The script checks
retained timestamps against PostgreSQL's actual clock. It cannot itself prove
that browser actions or independent human decisions occurred.

An unavailable query is **blocked**, not zero. A changed checker/catalog,
non-empty baseline, mismatched fixture, missing row, unexpected unadopted row or
unfinished lifecycle prevents acceptance. Preserve the report and diagnose the
cause; never delete records or alter evidence to obtain a pass. Current-source
regressions cover the read-only boundary, complete inventory and incompatible
profile rejection. Record their actual run result separately from this procedure.
The earlier preserved human trial reached local invitation delivery and stopped
at recipient-owned password entry; its intermediate zero inventory is not a final
lifecycle report. A new fixture must complete every row and the final inspection
before issue #42 can be accepted. See the
[preparation checkpoint](../checkpoints/2026-11-01-workforce-rehearsal-preparation.md)
and the separate [current-source native/startup feedback](../checkpoints/2026-11-02-workforce-rehearsal-native-startup-feedback.md).
The [migration-isolation checkpoint](../checkpoints/2026-11-02-workforce-rehearsal-migration-isolation.md)
records the later failed final certification and focused verification of its
bounded test-only repair; it supplies no browser-journey evidence.

## Evidence and completion boundary

| Step or check | Actor | Starting state | Observed result | Evidence reference | Status |
| --- | --- | --- | --- | --- | --- |
| Fill one row per step above | Role label only | Actual state | Safe visible outcome or error | Minimized screenshot, request reference or count report | Passed / Failed / Blocked / Deferred |

Retain exact source/image identity, the role-handoff record, local/UTC timing,
permission denial and return path, and before/after absence results. Redact
private reasons outside the authorized operator view. Separate browser evidence,
automated adapter/native tests and actual independent-human decisions. A route
response or CI pass does not prove an end-to-end human journey.

Dispose only the exact resources owned by this run through the environment's
documented cleanup. Preserve failed evidence first. A restart uses a new empty
fixture and fresh credentials; it does not reset a stopped unrelated rehearsal.
The ongoing and future Workforce practice editions provide prepared examples;
see [Practice the Workforce operating home](workforce-operating-home-practice.md).
They do not replace this empty-database setup and invitation rehearsal or its
final absence check. Other convention demos remain independent.

The owning contracts are [Workforce-only setup](../product/page-contracts/workforce-only-adoption-setup.md),
[Positions](../product/page-contracts/position-management.md),
[Assignments](../product/page-contracts/assignment-management.md),
[Availability](../product/page-contracts/availability-management.md),
[Shifts](../product/page-contracts/shift-planning-and-my-shifts.md), and the
[adoption/recovery runbook](workforce-only-adoption-and-recovery.md).
Requirements: OPS-008, UX-030, NFR-002, NFR-003, NFR-012 and NFR-013;
ADRs 0075–0078 and [0080](../architecture/decisions/0080-progressive-workforce-only-adoption.md).

## Route reference for facilitators

Use ordinary links in the core journey. This reference lets regression tests
detect route drift; placeholders mean the actual selected fixture's values.
Knowing a route never grants access.

| Route name | Path |
| --- | --- |
| `workforce-adoption-setup` | `/admin/platform/setup/workforce/` |
| `my-representation-invitations` | `/admin/invitations/` |
| `organization-structure` | `/admin/platform/organizations/<organization_slug>/series/<series_slug>/editions/<edition_slug>/structure/` |
| `organization-structure-positions` | `/admin/platform/organizations/<organization_slug>/series/<series_slug>/editions/<edition_slug>/structure/positions/` |
| `organization-workforce-assignments` | `/admin/platform/organizations/<organization_slug>/series/<series_slug>/editions/<edition_slug>/structure/assignments/` |
| `organization-workforce-availability` | `/admin/platform/organizations/<organization_slug>/series/<series_slug>/editions/<edition_slug>/structure/availability/` |
| `organization-workforce-shifts` | `/admin/platform/organizations/<organization_slug>/series/<series_slug>/editions/<edition_slug>/structure/shifts/` |
| `workforce-opportunities` | `/volunteer/<edition_id>/` |
| `my-workforce-assignments` | `/my/workforce/` |
| `my-workforce-availability` | `/my/workforce/<organization_slug>/<series_slug>/<edition_slug>/availability/` |
| `my-workforce-shifts` | `/my/workforce/<organization_slug>/<series_slug>/<edition_slug>/shifts/` |

## Finish the dedicated source rehearsal

When using the dedicated launcher above, its `before.json` is already the baseline.
Before stopping that site, copy the actual edition UUID from its visible link and
run the following in another terminal (replace the placeholder):

```powershell
uv run --locked python -m scripts.rehearse_workforce_browser inspect-final --directory .tools/workforce-rehearsal-01 --edition <actual-edition-uuid>
```

This wrapper verifies the unchanged source and exact owned image/container/runtime
endpoint, then invokes the same read-only inspector. It writes `after.json` once;
it never overwrites a previous failed or passed report. A rejection is evidence to
investigate, not permission to edit records or run a different profile. Neither
report establishes that a person completed the browser steps.

