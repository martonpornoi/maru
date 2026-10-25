# Build a convention from an empty Maru

Prepared for Saturday, 24 October 2026. Local synthetic test, based on protected
commit `7bd59c0bf1130a7ebc8b202d0f47b2bc26c9182b` (PR #221).

Start with **one platform administrator, no ordinary accounts, no organizations,
no convention series and no event editions**. No demo dataset or prefilled
convention is used. You create the business records through the GUI.

Allow **3–4 hours for the main path**, with breaks; optional branches can fill
the rest of the day. These are estimates, not measured completion times.
You can stop at any numbered checkpoint. A blocked step is a useful test result:
record it and continue with an independent branch instead of fixing data in SQL.

## Continue after the 24 October test reports

Your existing records are kept. You have two editions because this checklist
tests two different adoption profiles. The Crew edition was accidentally created
under a *second* organization named Synthetic Moonfox Organizers, whose stable
URL name ends in `-2`. Its Maru-operator representation is still provisioning;
Alex's Board access in the first organization cannot authorize the second.

To continue the Crew workspace you already made, use this sequence:

1. As the platform admin, open
   [the Crew organizer's accountable access](http://127.0.0.1:8044/admin/platform/organizations/synthetic-moonfox-organizers-2/representation/).
   Check that the stable organization URL contains `synthetic-moonfox-organizers-2`.
2. In **Invite a controller**, invite the existing verified accounts
   `alex.board@example.invalid` and `blake.board@example.invalid`. Reason:
   `Establish accountable access for the existing synthetic Crew workspace.`
   These are governance invitations, not new account invitations.
3. Sign in as Alex, open **My governance invitations**, and accept Alex's own
   Crew invitation. Repeat as Blake for Blake's invitation.
4. Return as platform admin to the same `-2` representation page. Activate its
   **Maru operators** after both accept, entering the exact displayed organization
   name and reason `Activate the accepted synthetic Crew controllers.`
5. Sign in as Alex again. Select **Moonfox Crew 2031**; open **Organization
   structure → Manage Positions** and continue at step 10. Keep Departments you
   already created. If none exist there, create them through step 10 first.

Do not repeat the foundation wizard, delete an edition, reparent records or copy
governance in the database. The two organizations' access remains separate. A
future fresh run should use the explicit series-reuse choice in step 9.

The question examples now use hyphens: `badge-name`, `first-visit`, `welcome-note`
and `temporary-note`. Keep valid keys you already saved; do not recreate them
merely to match the examples. Existing checklist ticks and private notes remain
in your browser profile.

## Before you begin

- [ ] Open the prepared local test folder and double-click **START.cmd**.
  Docker Desktop must be running. If START reports an already recorded session,
  run **STOP.cmd** once, then START again; neither command erases your work. If START reports an already recorded session,
  run **STOP.cmd** once, then START again; neither command erases your work. The guide opens at
  <http://127.0.0.1:8045/>; Maru is at <http://127.0.0.1:8044/admin/>.
- [ ] Open **ADMIN-LOGIN.txt** in that folder. It contains the only pre-created
  account and its fresh local password. Do not use an older demo login.
- [ ] Keep the [local test inbox](http://127.0.0.1:8045/inbox) open. New-account
  invitations go here, never to an outside mailbox. Refresh after up to
  30 seconds. Follow the actual invitation link and choose the password in
  Maru; no API request or database edit is needed.
- [ ] Use a separate browser profile/private window for each test identity,
  or log out before switching. Ordinary tabs share their login cookies.
- [ ] Keep all names, contact details, uploads and reasons fictional. You may
  use the examples below verbatim. Choose passwords you can remember for
  these disposable accounts; do not reuse real passwords.
- [ ] Start a notes file using the results table at the end. Record observations
  as **Pass**, **Blocked**, **Bug**, **Not tried**, or **Needs another person**.

The initial admin is platform oversight, not an attendee or volunteer. Do not
try to register it for the convention. You can exercise several synthetic
roles alone, but that is not independent-human approval or production acceptance.

**Current limits to expect:** you can build a registration draft in the GUI.
The complete canonical registration activation/successor writer is not claimed
as delivered. The Programme event timetable is still gated in ordinary profiles.
The working scheduling journey below is **volunteer Shift planning**. Keep these
limits distinct from defects you discover in a delivered screen.

## Main path A — accounts and the convention foundations (45–70 minutes)

### 1. Confirm that the starting state is empty

- [ ] Sign in as the initial administrator.
- [ ] Open **Platform administration → User accounts**. Expect exactly your
  initial platform account and no invited people.
- [ ] Open **Organizations**. Expect an empty list.
- [ ] Confirm that no working edition is selected and there are no convention
  series, event editions or demo workspaces. Do not run a demo seeder.

**Checkpoint:** you can explain what the platform admin is allowed to do without
having accidentally become a convention participant.

### 2. Create three ordinary people yourself

From **User accounts → Invite a user account**, invite one person at a time:

| Email | Display name | Intended test role |
| --- | --- | --- |
| `alex.board@example.invalid` | Synthetic Alex | First accountable controller |
| `blake.board@example.invalid` | Synthetic Blake | Second accountable controller |
| `casey.attendee@example.invalid` | Synthetic Casey | Ordinary person with no governance authority |

- [ ] Give each invitation the reason `Create a synthetic person for the local manual test.`
- [ ] Open each message in the local inbox, follow its one-use link, set that
  person's password, and finish acceptance through the GUI.
- [ ] Sign in as each person at least once. Confirm the accepted account is an
  ordinary person, not another platform administrator.
- [ ] Return to the original admin's **User accounts** inventory. Expect four
  accounts total, with accepted/verified state for the three new people.
- [ ] As Casey, check that platform-wide organizations/accounts are not available.

If delivery fails, record the invitation status, visible error and time. Do not
create the person through specialist Accounts records or mark them verified by hand.

### 3. Create your organization

As the initial admin, open **Organizations → Create organization**.
The [direct creation form](http://127.0.0.1:8044/admin/platform/organizations/new/)
is also available. Do not use the inspection-only Organizations page under
Advanced records.

Enter:

| Field | Value |
| --- | --- |
| Organization name | `Synthetic Moonfox Organizers` |
| Description | `Fictional organization for the October manual test.` |
| Website | `https://example.invalid` |
| Contact email | `office@example.invalid` |
| Primary operating country | Hungary |
| Default languages | English |
| Default time zone | `Europe/Budapest` |

- [ ] Select **Create organization**. Expect a Draft organization, with no
  automatically created people, series or editions.
- [ ] Open the organization, change its description and **Save changes**.
- [ ] Reload it and confirm the change persisted.

### 4. Establish accountable representation

- [ ] On the organization record, open **Representation & access**.
- [ ] Under **Choose accountable access**, select **Executive Board**, enter the
  reason below, and choose **Create accountable representation**. Reason:
  `Establish accountable governance for this fictional convention.`
- [ ] Invite Alex and Blake using their exact accepted email addresses.
- [ ] Sign in separately as Alex, open **My governance invitations**, and accept
  Alex's own invitation. Repeat as Blake for Blake's invitation.
- [ ] Return as the platform admin. Confirm both appointments are Accepted.
- [ ] Enter the exact organization name and reason
  `Activate the two accepted synthetic controllers for this local test.`
  Choose **Activate accountable access**.
- [ ] Expect an Active organization and representation. Casey must remain
  outside the Board. The platform admin must remain an operator, not a member.

If you are testing alone, label the result a synthetic multi-account rehearsal.
A real independent-person gate remains untested even when the forms succeed.

### 5. Create a recurring series and a dated edition

- [ ] From the organization's **Convention series**, choose **+ Add series**.
  Use name `Moonfox Convention`, description `A fictional recurring convention`,
  contact `convention@example.invalid`, and **Availability: Active**.
- [ ] Save and verify that **Convention editions** is still empty.
- [ ] Choose **+ Add edition** beside Convention editions. Select **Full convention**,
  name `Moonfox 2031`, start `2031-06-05`, end `2031-06-08`, time zone
  `Europe/Budapest`, language `en`, currency `EUR`.
- [ ] Choose **Create event edition**. Expect Draft, the correct parent chain,
  and no automatic registration, Programme, Department or Shift records.
- [ ] Choose **Use as working edition** explicitly. Check the edition context.
- [ ] Edit the end date to `2031-06-09`, save and reload, then restore
  `2031-06-08`. Confirm the earlier value returns without creating another edition.

**Checkpoint:** one organization → one series → one full-convention edition,
all created by your own GUI actions. The interface should keep these concepts distinct.

## Main path B — build the registration form yourself (35–55 minutes)

### 6. Start a blank form

As the platform admin, with **Moonfox 2031** selected, open the edition's
**Registration** setup page, rather than **Registration desk** or specialist records.

- [ ] Expect **Not configured**. Choose **Choose a starting point**.
- [ ] Set **Starting point: Blank registration** and leave the source record at
  **No source record — start blank**.
- [ ] Enter these values and **Create registration draft**:

| Field | Value |
| --- | --- |
| Configuration name | `Moonfox public registration v1` |
| Registration opens | `2030-12-01 10:00` |
| Registration closes | `2031-06-01 20:00` |
| Overall capacity / Overall hard ceiling | `20` / `30` |
| Currency / Minimum age | `EUR` / `18` |
| Default payment window in minutes | `1440` |
| Wait-list policy | Allow a wait-list |
| Automatic wait-list promotion | Require a later controlled offer action |
| Administrative reason | `Prepare a fictional registration form from blank.` |

Times are local to Europe/Budapest. Type dates as `YYYY-MM-DD` and local
date/times as `YYYY-MM-DD HH:mm:ss` using 24-hour time. A minute-precision field
accepts seconds `00`; it refuses nonzero seconds instead of rounding them.
For example, type `2030-12-01 10:00:00`. These future dates intentionally avoid opening a
public admission window during preparation.

### 7. Add and edit sections and questions

- [ ] Choose **Open registration builder → Add section**.
  Section key `visit`, attendee-facing title `Your visit`, description
  `Tell us what you want to do at Moonfox.`, placement First section.
- [ ] **Add question**: stable key `badge-name`, label `Name on your badge`,
  answer type Short text, Required, section Your visit, visibility Attendee and
  staff, classification C2 personal, purpose `Print the requested fictional badge label.`
- [ ] Add `first-visit`, label `Is this your first Moonfox?`, answer type Yes/no,
  Optional, C1 internal, purpose `Plan a fictional newcomer welcome.`
- [ ] Add `welcome-note`, label `What would help you feel welcome?`, Long text,
  Optional, C2 personal, same section, purpose `Prepare the fictional welcome desk.`
- [ ] If conditional controls are offered, show `welcome-note` after
  `first-visit` is Yes. Use the actual value/choice the UI presents.
- [ ] Edit one label, change the order, save and reload. Expect the chosen
  sequence and preserved definitions.
- [ ] Add one disposable optional text question `temporary-note`, then remove
  it through the draft builder. Confirm other questions remain intact.

Use `Build the synthetic registration definition for manual testing.` whenever
a retained administrative reason is requested. No real sensitive answers are needed.

### 8. Add admission products and inspect the boundary

- [ ] **Add product** with code `weekend`, name `Weekend admission`, price
  `2500` in minor EUR units (€25.00), entitlement code `admission`, entitlement
  name `Convention admission`, capacity `20`, hard ceiling `30`, sale window
  `2030-12-01 10:00` to `2031-06-01 20:00`, no required capacity codes,
  product wait-list Allow waiting, payment window `1440` minutes.
- [ ] Add a second product `day-pass`, name `Day admission`, price `1500`,
  entitlement code/name `day-admission` / `Day admission`, capacity `5`,
  ceiling `5`, the same window, and no volunteer eligibility requirement.
- [ ] Inspect the builder summary and reload. Expect one section, three
  retained questions and two products, all still draft.
- [ ] Return to **Registration** and verify the draft is linked without creating
  a registration, payment or attendee record.
- [ ] Record **registration activation/public checkout as Not tried — current
  canonical lifecycle cutover remains incomplete**. Do not use an old model-admin
  activation action, recovery command, SQL change or seeded active form to hide
  that limit. Public attendee registration is not a required success in this build.

**Checkpoint:** you have tested substantial form construction, validation,
ordering, removal, prices and configuration persistence. This is a form-building
result, not a complete public registration launch.

## Main path C — a separate volunteer scheduling journey (60–100 minutes)

This uses a second edition because **Workforce only** has a deliberate boundary:
no attendee registration or payment is needed for volunteer work. This means
two deliberately separate editions: **Moonfox 2031** for registration drafts and
**Moonfox Crew 2031** for volunteer work, normally under the same organizer/series.
Keep your full-convention form unchanged. This is a profile-isolation test, not
an instruction to create a second organizer.

### 9. Create the Workforce-only edition

- [ ] As the platform admin, open **Set up a volunteer team**.
- [ ] Under **What already exists in Maru?**, explicitly choose
  **Add an edition to a series**. Select **Moonfox Convention — Synthetic Moonfox
  Organizers (synthetic-moonfox-organizers)**. Do not choose **Create organization,
  series, and edition**, and do not type the existing organizer's name as a new
  foundation. Name the new edition `Moonfox Crew 2031`,
  dates `2031-06-05` through `2031-06-08`, time zone `Europe/Budapest`.
- [ ] Review **Only Workforce is adopted** and submit once.
- [ ] Select this edition. Expect Workforce setup and no Registration/payment
  destinations. Do not try to expand its immutable profile.

### 10. Create a small structure and Position

- [ ] Open **Organization structure → Create Department**. Make a root
  `Operations`, purpose/description `Run the fictional convention floor.`
- [ ] Create child `Welcome Desk` beneath Operations, description
  `Help fictional visitors find their way.` Do not copy the 22-Department starter
  on the main path; this is your own manually built structure.
- [ ] Sign in as Alex, select **Moonfox Crew 2031**, then open **Organization
  structure → Manage Positions**. Check the edition name before continuing.
  If the edition is absent, its own accountable-access setup is incomplete;
  follow the recovery instructions near the beginning instead of changing roles
  or creating the same workspace again.
- [ ] If no compatible template exists, use **Create the safe Volunteer starter**,
  enter Blake's exact email, and explain `Create the minimal volunteer template for this manual test.`
- [ ] Choose **Create Position**. Title `Welcome volunteer`, Department Welcome
  Desk, approved headcount `2`, template the safe Volunteer starter, no reporting
  Position, purpose `Welcome people and explain where to go.`, reason
  `Plan two fictional welcome volunteers.`
- [ ] Publish/open its volunteer opportunity using the offered controls. Expect
  the position and opportunity states to be clearly distinguished.

### 11. Appoint one person through the governed assignment forms

Use **Blake** as the main-path volunteer: Blake already has the required
organization relationship from the Board ceremony. An invitation alone does not
make Casey a candidate for every Position. Testing that boundary is intentional.

- [ ] As Alex, open the Position and **Propose a person**. Choose Blake.
- [ ] Use effective start `2031-06-05 08:00` and ending `2031-06-09 20:00`, or
  a narrower valid interval that still includes every Shift you plan. Keep its
  start after the Board activation you just performed. Reason
  `Propose synthetic welcome work for the manual scheduling test.`
- [ ] Expect Proposed and a clear need for a different controller's decision.
- [ ] Sign in as Blake and approve the exact proposal if the UI admits this
  independent account and its authority. Use reason
  `Review the fictional role, dates and headcount for this local test.`
- [ ] If self-subject approval is refused or another controller is required,
  record the boundary. Use the platform admin's independently attributed oversight
  only if the ordinary approval screen explicitly offers it; do not choose a
  controller identity on someone else's behalf or edit an assignment record.
- [ ] Confirm the assignment is Active and appears in Blake's **My Workforce**.

This remains a single-person rehearsal if you control all test accounts. Do not
record actual two-human governance or safeguarding approval as passed.

### 12. Add Availability and a Shift

- [ ] As Blake, open **My Workforce → Availability** for Moonfox Crew 2031.
- [ ] Add an Available window on `2031-06-06`, `09:00`–`18:00`, then submit
  the plan through its normal form. Availability must not create a Shift claim.
- [ ] As Alex or the admitted platform admin, open **Shifts → Plan shifts**.
- [ ] Create `Welcome desk — morning`: Position Welcome volunteer; where to
  report `Welcome Desk, main entrance`; starts `2031-06-06 10:00`; ends
  `2031-06-06 12:00`; people needed `1`; break `10` minutes; required rest after
  this Shift `30` minutes; briefing `Welcome visitors and direct questions to the desk lead.`;
  handover `Tell the next volunteer about unresolved questions.`;
  planning reason `Cover the fictional Friday welcome desk.`
- [ ] Open/publish the draft through the offered Shift action.
- [ ] As Blake, open **My shifts → Suitable open work**, inspect all instructions,
  and claim it. Expect **Claimed**, not Confirmed.
- [ ] As the organizer, confirm the claim with reason
  `Confirm the volunteer, Availability and absence of overlapping work.`
- [ ] As Blake, verify the retained row says Confirmed. Do not expect to see
  another person's private Availability or the organizer's rationale.
- [ ] As the organizer, lock the fully covered Shift. Expect Locked and a clear
  explanation if further changes require reopening.

Completion is time-dependent. A Shift dated in 2031 cannot truthfully be completed
now; the expected result today is refusal before it ends. Do not change the clock.

### 13. Download and print what you created

- [ ] As the authorized organizer, open the Workforce-only Shift list and use
  the download and print actions for the rota operating copy.
- [ ] Save the ZIP locally. Inspect `rota.json`, `schema.json`, `rota.html`,
  `README.txt`, and `manifest.json`.
- [ ] Open the standalone print HTML and browser print preview. Check labels,
  Shift times, instructions, source versions, observation/stale-copy notice,
  page breaks and long text. Printing to PDF is optional.
- [ ] Confirm the copy does not show platform account IDs, private Availability,
  contacts, documents, decision reasons or unrelated registration data.
- [ ] Keep the copy as historical output; changing the live plan must not silently
  change the saved file.

**Checkpoint:** manual foundations, draft form, responsibility, Availability,
claim, organizer confirmation, locked coverage and a portable/printable copy.
Mark the last successful step honestly if a boundary stops the path earlier.

## Optional branches — choose what interests you

### O1. Error handling and stale forms (15–25 minutes)

- [ ] Try an edition end date before its start date; expect a useful error and
  preserved input, with no extra edition created.
- [ ] Try a registration capacity above its hard ceiling; correct the field
  after the error. Do not record invalid data as successfully saved.
- [ ] Open the same edition profile or draft builder in two tabs, save a change in
  one, then save the old form in the other. Expect stale/reload guidance rather
  than a silent overwrite.
- [ ] Repeat a save or refresh after submission. Confirm no duplicated record.

### O2. Claim, rest, capacity and withdrawal rules (20–35 minutes)

- [ ] Create a second open Shift overlapping the confirmed one. As Blake,
  confirm it is unavailable or refused, including required rest.
- [ ] Create a Shift outside Blake's submitted Availability. It must not become
  suitable merely because Blake holds the Position.
- [ ] Try to lock an underfilled Shift without explicit underfill acknowledgement.
  Expect refusal; do not accept underfill casually as a main-path success.
- [ ] Reopen the first Shift as organizer, then withdraw as Blake using the
  acknowledgement checkbox. Expect retained Removed/withdrawn history.
- [ ] Reclaim and have the organizer confirm again. Distinguish retained history
  from the current commitment.
- [ ] Try to complete a future Shift. Expect refusal before its end time.

### O3. Reuse without accidental shared state (15–25 minutes)

- [ ] Create `Moonfox 2032` manually beneath the same series and confirm that
  it begins without the other edition's people, Departments, form or Shifts.
- [ ] If an eligible published registration template/prior-edition source is
  offered, inspect it; do not assume a draft is an eligible source.
- [ ] For a second Workforce-only edition, optionally apply the fictional
  Department starter, edit a copied leaf, and check the earlier edition is unchanged.

### O4. Separate Announcements workflow (30–60 minutes)

- [ ] Use **Set up Announcements** to create a separate fictional edition;
  reuse existing foundations only when explicitly offered.
- [ ] Complete its visible named-person purpose-authority setup, using accounts
  you created yourself. Record any additional independent-review requirement.
- [ ] Create one draft announcement: title `Welcome desk opening`, body
  `The fictional welcome desk opens at 10:00. Ask the team for directions.`
- [ ] Submit for the offered independent review. A drafter approving their own
  work should not count as independent review.
- [ ] Prepare channel copy for manual handoff. Record publication only as a
  synthetic manual exercise; do not post to a real social account.
- [ ] Make a correction and inspect retained review/publication history and export
  if the admitted interface offers it.

### O5. Guides, required reading and help desk (30–60 minutes)

- [ ] Create a separate Guides workspace, or use the explicit supported expansion
  of an Announcements edition. Do not change profile codes through ordinary editing.
- [ ] Complete the visible purpose/access setup for named editor, reviewer and
  handler accounts that you created yourself.
- [ ] Draft `Welcome desk handbook` with two short fictional instructions;
  request review and publish only through the available governed actions.
- [ ] As an admitted reader, find the guide and exercise required-reading
  acknowledgement if offered; verify acknowledgement is not permission expansion.
- [ ] Open a help request `Where is the quiet room?`, reply through the handler
  interface, and inspect status/history. Try an optional handover/escalation.
- [ ] Compare reader and handler views for private notes and wrong-edition access.

### O6. Keyboard, narrow screens and ordinary-language usability (15–30 minutes)

- [ ] Complete one whole form using Tab/Shift+Tab/Enter. Follow visible focus.
- [ ] Test genuine browser 200% zoom, then a narrow browser window. Check the
  menu, long labels, errors, tables and drawers without losing controls.
- [ ] Where a detail drawer exists, check Escape, focus return and keyboard trapping.
- [ ] Note terms you could not understand without this guide. Treat confusing
  navigation and silent failure as findings, even if the server accepts the data.

### O7. Privacy, isolation and resume (15–25 minutes)

- [ ] Compare Casey's ordinary-person view with the admin and controller views.
  An account invitation must not itself grant convention management.
- [ ] Save an authorized edition URL, switch to a person without that scope, and
  open it. Expect a safe denial without private names or another person's records.
- [ ] Use **STOP.cmd**, then **START.cmd**. Verify your records, account passwords
  and form content are still present; the launcher must not reseed or clear them.
- [ ] Review the relevant history/audit screen only where your role is admitted.
  Check that decisions retain reasons without making them public attendee data.

### Known unavailable or separate acceptance

- Programme submissions/reviews and the released **event timetable** are dormant
  in ordinary profiles. Do not use a Programme rehearsal seed or activation override
  to manufacture this test's success. Volunteer Shifts are a different schedule.
- Complete registration activation, public checkout, paid-provider reconciliation,
  live credentials and registration closure are not promised by this from-blank
  canonical builder. Do not treat a visible backend record as a finished GUI journey.
- Dealer/auction journeys, external channel delivery, real safeguarding/minor
  policy, production scanners/storage, restore/PITR and production deployment
  need their own current scope and acceptance. Treat absent navigation honestly.
- One tester with several accounts cannot satisfy independent-person,
  screen-reader-specialist, operational-owner or production approval gates.

## Finish and report

- [ ] Record your last successful main-path step and the optional branches tried.
- [ ] Save relevant screenshots, output ZIP/PDF and exact visible errors locally.
  Keep passwords, one-use links and private mail out of shared screenshots.
- [ ] Copy your checked guide/notes if you want a durable report; browser checklist
  ticks are local to this browser profile and are not server acceptance evidence.
- [ ] Double-click **STOP.cmd**. This stops only this test's processes/container.
  It retains the database volume, manual records, mail, outputs and notes. There
  is no automatic expiry, data reset or destructive cleanup button.

| Step | Result | Expected / observed | Account and edition | Screenshot / error / follow-up |
| --- | --- | --- | --- | --- |
| Example: 7 | Not tried | Add and reorder questions | Admin / Moonfox 2031 | — |
|  |  |  |  |  |
|  |  |  |  |  |

For a bug, include the step, action, exact visible message, whether input was
retained, and whether reloading shows a partial or duplicated record. Avoid
repeatedly submitting an action once its outcome is uncertain.
