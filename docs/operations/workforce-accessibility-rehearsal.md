# Rehearse Workforce access and accessibility

**Audience:** Contributors and evaluators using a separate fictional preview\
**Outcome:** Record exact role, state, layout and keyboard evidence under #23\
**Status:** Signed-out evidence recorded; authenticated roles and real zoom remain blocked

Use the [ordinary Workforce practice](workforce-operating-home-practice.md) for
the task sequence. This guide adds a repeatable evidence matrix; it does not
replace independent human, specialist screen-reader or operational acceptance.
Never use the saved maintainer manual-test environment, accounts, passwords or
113-checkbox guide for this rehearsal.

## Start with a separate preview

From the repository root, with the [local prerequisites](../start-here/run-locally.md):

```sh
uv run --locked python scripts/try_maru.py --scenario workforce --port 8766 --minutes 120
```

Use an unused loopback port. Wait for **Ready** and open the printed link. Keep
the launcher terminal open; **Ctrl+C** or lease expiry removes only its owned
database and volume. A new invocation creates a new timeline; do not rerun a seed
over an existing rehearsal or prune unrelated resources. Start this preview only
after other required native acceptance workers finish, so the rehearsal does not
compete with their fixed resource budget.

Use an isolated browser context as well. Session cookies are scoped by host,
not port: another `127.0.0.1` port in the same ordinary browser profile could
replace the saved manual rehearsal's login cookie. A separate in-app browser
context or temporary guest browser avoids that interference. Do not clear the
user's existing cookies or reuse the original manual tab. Real zoom evidence
still needs a browser that exposes its actual zoom control.

Expand one practice role, copy only its generated credentials and sign in through
the ordinary form. Use **Sign out to switch roles** before another account.
Keep credentials and the role-picker page out of screenshots, public evidence,
issues and PRs. Platform/setup passwords are deliberately hidden; do not extract
them from process state or invent an alternate route to a closed human boundary.

## Record the actual starting point

Record the exact source commit, browser/version, actual viewport in CSS pixels,
browser zoom percentage, theme, motion preference, date, edition and role. A
responsive emulation width is not real browser zoom. A screenshot alone proves
neither focus order nor announcement by a screen reader.

The maintained fixture admits these distinct roles in both ongoing and future
editions:

| Role | Expected purpose | Deliberate boundary |
| --- | --- | --- |
| Manager | Structure, Assignments, shared Availability and Shift planning | Cannot approve their own Assignment proposal or confirm their own claim |
| Reviewer | Assignment review and Shift decisions | Does not gain Structure editing |
| Volunteer | Own Assignment, Availability and suitable/retained Shifts | Does not gain organizer rosters or another edition's work |

Prepared fixture decisions are synthetic setup, never independent-person
acceptance. This fixture does not expose a platform-admin login, a dedicated
read-only/manage-only account or every revoked/expired role. Record those cells
as not exercised rather than treating a Manager as a substitute. Use separately
reviewed role fixtures or genuine owner-led sessions when those cells are added.

## Role and state task cards

Use visible links and forms. Preserve initial state and time before each task;
later tasks deliberately change it. Check the current UI before recording a
label as evidence.

If recording W11's before-end state, open the ongoing Manager's **Short closeout
practice** first. It ends five actual minutes after fixture preparation; a long
future-edition sequence may already have passed that time. Keep the real timeline
and report an unobserved before-end state honestly rather than moving the clock.

| Card | Role/edition | Task and observable result |
| --- | --- | --- |
| W01 | Signed out | Open protected Home, Shift and personal links; ordinary sign-in or safe denial exposes no private work |
| W02 | Future Volunteer | Inspect proposed Assignment/private Availability and My shifts before approval; no inferred active assignment, organizer rationale or other people |
| W03 | Future Reviewer | Review the pending Assignment through the ordinary page and own step-up when requested; decision uses a different person from its author |
| W04 | Future Volunteer | Share the complete Availability plan deliberately; a private/missing plan remains unknown, a shared empty plan means unavailable |
| W05 | Future Manager | Open the draft **Future welcome desk**, review local times/instructions, open claims and return to Home |
| W06 | Future Volunteer then Reviewer | Claim suitable work, observe awaiting-review status, switch sessions and independently confirm; a claim alone is not confirmed coverage |
| W07 | Future Manager | Lock confirmed current coverage without accepting underfill; status and retained reason are visible only to authorized roles |
| W08 | Future Volunteer then Manager | Withdraw or replace Availability, inspect changed evidence, explicitly reopen locked coverage if necessary and attempt a fresh lock; stale coverage is refused without silently refreshing a source version |
| W09 | Future Volunteer then Reviewer | Share a corrected plan; reviewer explicitly uses **Review confirmation again** before a fresh lock |
| W10 | Ongoing Manager/Reviewer | Inspect **Welcome desk - claim awaiting review**, capacity and independent decision; no asserted attendance or actual-time evidence |
| W11 | Ongoing Manager | Observe **Short closeout practice** before/after its displayed real end; complete only after the end, then inspect retained history |
| W12 | Appropriate Manager and Volunteer | Cancel an eligible practice Shift with retained rationale; the person sees truthful removal/cancellation without organizer private reasoning |
| W13 | Other-edition account | Open an observed exact URL from the other edition; safe denial must not disclose hidden people, work or counts |
| W14 | Reviewer | Inspect Structure through authorized navigation; no Structure-editing action or accidental authority from context |
| W15 | Authorized actor in two tabs | Retain an old form, make a normal change in the other tab, submit the old version; conflict is explicit and safe input/retry context remains |

Use ordinary supported recovery when a card changes the state needed by another.
Do not edit a retained version, backdate authority, use direct database writes,
weaken a guard or accept another human's invitation to create a desired screenshot.
The existing native tests cover additional authority/capacity combinations; their
results remain automated evidence rather than a browser observation of missing
fixture roles.

## Layout, zoom and keyboard matrix

For Home, organizer Shift list/detail, personal Assignment/Availability/My shifts
and at least one returned invalid form, select the applicable cells:

- CSS widths: 320, 390, 768, 958, 1,024, 1,280 and 1,920 pixels.
- Light/dark themes; statuses must have text or another non-colour meaning.
- Actual browser zoom at 200%, with its real displayed percentage recorded;
  resizing, CSS scaling and device-pixel-ratio emulation do not substitute.
- Keyboard discovery, skip link, visible focus, logical Tab/Shift+Tab order,
  ordinary Enter/Space activation and no trap.
- Narrow navigation drawer: opener name/state, focus entry and containment,
  background inertness/accessibility isolation, Escape close and focus return.
- One H1 and one host `main`, unique IDs, labels/fieldsets, help/error association,
  status/error semantics, ordinary form correction and reload behavior.
- Page-level overflow, clipped required controls, readable long labels, local
  scroll regions and target sizes. Retained row context must survive stacking.
- Reduced-motion preference where the surface animates. Record the actual
  browser/OS preference; a static stylesheet rule is separate evidence.

Record layout and keyboard observations independently. Automated accessibility
checks can find structural defects but do not establish a representative screen
reader's announcements, comprehension or complete assistive-technology coverage.

## Failure and disclosure

Exercise malformed/missing input and safe stale forms through normal UI. Record
source/audit outage or overflow only if a separately scoped supported fixture
actually creates it; never disable authorization/audit in the running preview to
make the cell appear tested. Distinguish unknown, denied and unavailable from
zero work. Check that personal pages omit organizer rationale, other volunteers,
private Availability values and foreign-edition labels.

If an owned preview dependency is interrupted for a planned recovery test, record
the exact owned resource and preserve its data. Do not stop/restart any manual
database or unrelated fixture. Capture the failed page, normal recovery and reload
separately; a successful restart is not representative restore/PITR evidence.

## Evidence record and stopping point

For each observation record:

| Field | Required content |
| --- | --- |
| Provenance | Exact source commit, preview scenario, browser/version and timestamp |
| Scope | Fictional edition, actual distinct role, initial state and task card |
| Presentation | CSS viewport, real zoom, theme and motion preference |
| Action | Actual links, keystrokes/forms and current visible wording |
| Result | Passed, failed, blocked, not exercised or not applicable with reason |
| Evidence | Sanitized screenshot, visible behavior or automated report; no credentials/private payload |
| Limit | Synthetic/automated evidence versus genuine human, specialist or operational evidence |

Keep failed originals; fix only supported defects, add focused regressions and
repeat affected paths on the new source. Do not call another commit's screenshot
or test receipt exact-head acceptance. Before protected delivery, perform the
normal final certification and required independent hosted checks.

Finish by closing browser sessions, stopping only the owned launcher and verifying
its exact container/volume cleanup. Preserve the ten original stopped fixtures
and manual data. Keep #23 open until every required role/state and genuine human
cell has its evidence. Do not mark screen-reader, representative owner, recovery,
operational or production acceptance complete from this synthetic rehearsal.

## Recorded bounded observation — 1 November 2026

This observation used source `a42205cb7d18fc59575982824a43bf66f9ff8139`, the
ordinary maintained Workforce preview on loopback port 8766 and a separate
in-app browser context. The browser's engine version and real zoom percentage
were not exposed, so neither is inferred. It used fictional ongoing/future
editions with dates prepared on 1 November. No original manual-test tab,
credential, account, record, checklist or stopped database was used.

| Cell | Actual result | Limit |
| --- | --- | --- |
| Signed-out protected routes | Home, organizer Shifts and the publicly linked personal Availability destination redirect to ordinary sign-in without releasing private work | No authenticated or foreign-edition authorization claim |
| Role-picker layouts | Requested all seven listed CSS viewport widths; no page-level horizontal overflow, one H1, one main and no duplicate IDs; all credential disclosures were closed | The scrolling page reserves a 15-pixel scrollbar; at requested 320 the viewport was 320 and content width 305 |
| Sign-in layouts | All seven actual viewport widths matched their requested values, with no horizontal overflow, one H1/main and no duplicate IDs | One supplied light presentation only; no dark/reduced-motion or real-zoom evidence |
| Form labels | Both visible inputs have programmatic labels, required state and appropriate username/current-password autocomplete | No screen-reader announcement or owner comprehension claim |
| Keyboard sequence | Tab moves between the two event links; Space opens/closes a role disclosure; sign-in Tab proceeds email → password → submit | Basic supported browser key input only; no complete drawer/trap/focus-visibility matrix |
| Browser console | No captured warning/error entries during this bounded path | Does not establish absence of server warnings or every failure state |

Native Chrome control timed out requesting application access before a Guest
session or zoom action could run. In the isolated in-app browser, credential
field reads yielded redacted placeholders. One attempted sign-in using those
placeholders returned the normal generic rejection; it is not evidence that
the actual generated credentials failed. No retry with guessed credentials,
password reset, process/database extraction, platform/setup login or invitation
route was used. W02–W15, including the real before/after-end closeout, remain
unexercised in this observation. Time was not changed or backdated.

Both task-created browser tabs were closed, and the temporary viewport override
was reset. The ordinary launcher was interrupted; its shell reported exit 1
and a cleanup message. Independent exact-ID checks then confirmed its one
container and anonymous volume were absent and all ten original stopped
fixtures retained their IDs, names, images and exited state. Cleanup evidence
does not turn the blocked role journey into acceptance. #23 remains open.

### Supported Copy-button probe on updated main

A second separate preview used protected source
`82a351478773ab60ce6f195db4e9996e8832ba9f`. Its ordinary **Copy email** button
reported **Copied. Paste it into the normal sign-in form.** The browser tool's
clipboard API returned an empty string, and ordinary Ctrl+V into the disclosed
sign-in form was explicitly refused because its virtual clipboard had no data.
No authentication submission occurred in this probe. This does not establish
that the generated credentials or Maru's ordinary sign-in are defective.

The page's **Clear copied practice data** action then reported **Clipboard
cleared.** Both task tabs were closed and the viewport reset. The launcher was
interrupted normally (shell exit 1); exact container and volume absence and all
ten unchanged original stopped fixtures were independently verified again.
No password, alternate credential source, hidden account, invitation acceptance,
original manual data, clock change or authentication-policy change was used.
Authenticated cases require an available supported browser input path; native
zoom and genuine human/specialist gates remain open. The failed first method
and this separate normal-UI probe remain distinct evidence, not retries of a
valid-credential failure or a completed authenticated journey.
