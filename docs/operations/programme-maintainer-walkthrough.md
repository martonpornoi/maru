# Programme maintainer walkthrough

**Audience:** The maintainer testing alone on the local Windows computer\
**Outcome:** Try a small fictional Programme workflow and record where it becomes confusing\
**Status:** Core journey, print preview and offline HTML reported passed by the maintainer on 2026-10-05

This guide is for coached-by-document maintainer testing. It does not replace the
independent-person, specialist accessibility or operational-owner session in
[the human acceptance cards](programme-human-acceptance.md). Stop at the first
complication if you prefer; that is useful feedback, not an incomplete assignment.

## Short session: two output checks

The maintainer confirmed that both outputs displayed correctly and that these
instructions were followable. The [recorded observation](../checkpoints/2026-10-05-programme-step1-native-and-maintainer-outputs.md)
completes this short follow-up; it does not require repeating the successful core
journey. The steps below remain available to reproduce the two checks. Start
Docker Desktop and open a new PowerShell terminal in the prepared checkout:

```powershell
Set-Location 'C:\Users\TheMw\Documents\Maru'
git rev-parse HEAD
git status --short
.\.venv\Scripts\python.exe -m tests.rehearsals.programme_hands_on --stage published
```

Wait for **READY - fictional local test environment**. Keep the terminal and
account window open. This stage creates the fictional published timetable for
you; you do not need to repeat call creation. Use its newly printed **Public
programme** URL. Both checks use public output and need no account sign-in:

1. Follow the **Print-friendly complete copy** and Ctrl+P steps in
   [read the prepared timetable](#optional-second-session-read-the-prepared-timetable).
   Inspect every preview page for clipped or missing activities, room names,
   dates and saved-copy warnings. Cancel printing when finished.
2. Follow [public offline copy](#optional-public-offline-copy): download the new
   snapshot, use this session's exact **PUBLIC OFFLINE CHECK** commands and open
   the generated `initial.html`. Check that the timetable, scope, source time
   and historical-copy warning are readable and understandable. Complete the
   download/verification within its five-minute validity; if it expires, take
   a fresh download rather than changing the clock or bypassing verification.

Record the printed commit, browser/version, and **worked**, **confusing** or
**blocked** for each check, with the exact error or a short description if needed.
Do not include passwords or signing material. Withdrawal, stop-use and personal
account checks are optional later work, not extra tasks in this follow-up.
Save your notes and follow [stop and disposal](#stop-restart-and-preserve-your-notes).
The session's disposable data is removed at stop or expiry.

Do not run a rehearsal alongside the full eight-database local certification
pool. If technical certification is still in progress, wait for its completion
before starting this session.

## Version and prerequisites

The application and desktop launcher are available at protected commit
`dec2ca5f52613eb7706f37388ba0283a9596481c` ([PR #207](https://github.com/martonpornoi/maru/pull/207)).
Its source tree equals the locally certified `73692da7` candidate; independent
hosted acceptance, PR gate and CodeQL passed before merge. See the
[delivery record](../checkpoints/2026-10-04-programme-maintainer-protected-delivery.md).
Record the exact commit printed at startup with your observations. The commands
below use this computer's prepared checkout and locked environment. The
[October 5 follow-up](../checkpoints/2026-10-05-programme-24-hour-deadlines.md)
changes the deadline controls described below and is awaiting exact-head
certification and protected delivery in [PR #208](https://github.com/martonpornoi/maru/pull/208).
Record `git status --short` alongside the startup commit when evaluating a local
candidate. A commit alone does not identify a modified working tree.
This remains synthetic evaluation, not a production release or independent human acceptance.

The maintainer reported: “The core journey went well. No issues.” The accompanying
feedback requested 24-hour entry because AM/PM made noon and midnight confusing.
The later report confirms the two output checks above. These are single-maintainer
observations; other optional sessions and the independent acceptance cards remain
separate. You do not need to repeat the whole journey to comment on the new clock.

Use this computer's existing Maru checkout, locked `.venv`, Python's Tk desktop
runtime and Docker Desktop. The account window requires Windows; unavailable
desktop support fails before any test database is created.
Use only fictional data. The test server listens on this computer, not the LAN.
The commands create a fresh disposable database and real test accounts through
the maintained native setup; they do not activate Programme in your normal database.
There is no shared permanent test password. Credentials remain in memory;
only a deliberate copy places one value on the local clipboard. The window
uses [Windows history and cloud exclusions](https://learn.microsoft.com/en-us/windows/win32/dataxchg/clipboard-formats#cloud-clipboard-and-clipboard-history-formats).
Other local applications may read the clipboard while it is present. Paste
only into this test site's login; do not save these passwords in your browser.
If the process crashes or clipboard cleanup fails, copy harmless text yourself.

## Start the server and create the test accounts

1. Start Docker Desktop and wait until its engine is running.
2. Open a **new PowerShell terminal**, outside a transcript or screen recording.
3. Run these commands:

   ```powershell
   Set-Location 'C:\Users\TheMw\Documents\Maru'
   git rev-parse HEAD
   git status --short
   docker info --format '{{.ServerVersion}}'
   .\.venv\Scripts\python.exe -m tests.rehearsals.programme_hands_on --stage team
   ```

4. Wait for **READY - fictional local test environment**. Preparation can take
   several minutes. A preparing message is not readiness. If startup fails,
   record the stage and message; do not change your production settings or
   disable security checks to continue.
5. The terminal supplies the exact **Administration** address. A separate
   **Programme test accounts** window opens. Select the required **Role**,
   choose **Copy email**, and paste into **Email address or username** on
   this local site's login page. Return to the account window, choose
   **Copy password**, and paste into **Password**. The window shows the
   email; it never displays the password or writes it to the terminal.
6. Paste each copy within 30 seconds. Expiry, changing roles or stopping
   clears the window's unchanged clipboard copy. If you copied something
   else meanwhile, that newer copy is preserved. On **Copy failed**, close
   other clipboard tools and try the button again.
7. Leave the terminal and account window open. Remaining time includes preparation.
   The original lease is one hour; worker refresh does not extend it.

The `team` stage has already created the fictional organization, series, edition,
Programme Department, two controllers and an intake organizer. That setup is an
automated prerequisite. It is not evidence that you created an organization or
users through the interface. The accounts named **organizer** and
**independent-approver** are different identities, although you operate both.
Neither their labels nor being a controller grants every Programme permission.

## Switching accounts

Use the ordinary **Log out** control before switching **Role** in the account
window. Copy and paste the newly selected email and password separately,
then choose **Open Administration**. Check the displayed signed-in identity
after each switch.
Ordinary tabs share login state; opening a second tab is not a second account.

If a task is missing, record which account you used and what you could see.
Do not improvise grants or switch to an administrator to make it work.

## Core journey: create one call draft

Allow roughly 15–25 minutes after READY. This is a small form-and-navigation test;
you can stop after it. You will not need to invent users, policy codes or reasons.

1. Open **Administration** from the terminal and sign in with **intake-organizer**.
2. Beside **Workspace**, choose **Change**. In **Choose a workspace**, select
   **Synthetic Programme rehearsal · Synthetic Programme organizer**, then
   press **Switch**. Selection alone does not switch the workspace.
3. In **Find a task or record**, enter `Programme` and press Enter.
4. Open **Programme calls, review and conversion**, then **Manage calls** under
   **Programme (programme)**, then **Create a call draft**.
5. Read **Starting configuration to review**. The draft starts with two questions
   and one contributor-name policy; creating it does not open a public call.
6. Fill every field below. Policy references are the fixture's synthetic policy
   codes, not approval to reuse those policies at a real event.

| Visible field | Copy or choose this value |
| --- | --- |
| Stable call code | `moonlit-makers` |
| Call name | Moonlit Makers: panels and workshops |
| Call guidance | A fictional convention call for friendly creative sessions. |
| Why these proposals are collected | Practise reviewing and scheduling a fictional Programme proposal. |
| Classification | C2 - Personal |
| Maximum submissions per person | `4` |
| Maximum collaborators | `4` |
| Audience policy | `applications.programme.audience.v1` |
| Proposal retention policy | `applications.programme.retention.v1` |
| Proposal content policy | `applications.programme.content.v1` |
| Contributor consent policy | `applications.programme.contributor-consent.v1` |
| Collaboration evidence retention policy | `applications.programme.collaboration-retention.v1` |
| Initial track code | `creative` |
| Initial track name | Creative workshops |
| Initial format code | `workshop` |
| Initial format name | Workshop |
| Minimum duration minutes | `30` |
| Default duration minutes | `60` |
| Maximum duration minutes | `90` |
| Reason | Create a fictional call to evaluate the Programme workflow. |

7. For the three deadline fields, open a **second** PowerShell terminal and run:

   ```powershell
   $programmeToday = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Central Europe Standard Time').Date
   'Opens (inclusive): ' + $programmeToday.AddDays(-1).AddHours(12).ToString('yyyy-MM-dd HH:mm')
   'Applicant edit deadline (inclusive): ' + $programmeToday.AddDays(1).AddHours(12).ToString('yyyy-MM-dd HH:mm')
   'Closes (exclusive): ' + $programmeToday.AddDays(2).AddHours(12).ToString('yyyy-MM-dd HH:mm')
   ```

   Under each matching deadline, choose the printed date in **Date** and type
   `12:00` in **Time (24-hour)**. The clock uses `00:00`–`23:59`: midnight is
   `00:00`, noon is `12:00`. The browser may display the calendar date in your
   computer's format; these are **Europe/Budapest** local times. Noon avoids
   the ambiguous overnight clock-change hour.
8. Check **Create this draft with the displayed title/description questions and
   contributor-name policy.**, then press **Create this call draft**.
9. Expect the heading **Moonlit Makers: panels and workshops**, the state
   **draft**, your Creative workshops track, Workshop format with 30/60/90 minutes,
   and **Proposed title** and **Proposal description** under **Complete configured
   questions**. Deadlines are displayed with explicit offsets; they can appear as
   UTC instants representing the same local time you entered.
10. Save your observations. Leave **Activate domain call** alone for this short
    journey. Follow the disposal steps below.

If a validation error appears, copy its exact text and stop or correct a typing
mistake. Do not submit repeatedly after an uncertain result; first inspect whether
the named draft already exists under **Department calls**.

## Optional second session: read the prepared timetable

After the first session is disposed, start a new one from the Maru folder:

```powershell
.\.venv\Scripts\python.exe -m tests.rehearsals.programme_hands_on --stage published
```

This stage prepares a separate call, submitted proposal, completed review,
accepted items, rooms, staffing and an approved published timetable. It supplies
planner, volunteer and reviewer accounts. These are automated prerequisites,
not things you personally submitted, reviewed or published. It requires the real
fixture malware scanner; the launcher opts into its existing isolated signature
refresh. Wait for READY and use this session's new accounts and URLs.

1. Open **Public programme** from the terminal. Expect **Programme now and next**,
   **Approved Programme release available at the source check**, Europe/Budapest,
   a source-check time and a replace/dispose deadline.
2. Read **Complete run sheet**. Expect **Fictional opening ceremony** and two
   **Fictional convention workshop** occurrences, with Main stage and Workshop
   room wayfinding. Dates move with fixture creation; use the displayed dates.
   Empty **Now** is normal when the fictional convention is still in the future.
3. Follow **Complete public Programme timetable**, inspect it, then use the
   browser Back button. Note any confusing differences between these outputs.
4. Choose **Print-friendly complete copy**. Check that all three occurrences,
   scope, source time and saved-copy warnings remain readable.
5. Press Ctrl+P. Inspect the browser's print preview, including later pages;
   cancel it when finished. Record clipping, missing text and the browser used.
   This native print-dialog check is maintainer-operated. The October 5 report
   confirmed correct display; the assistant did not operate that native dialog.
6. Optional: sign in through **Administration** with **volunteer**, then open
   **My programme** from the terminal. Expect **My Programme now and next** and
   three **Fictional room preparation and session support** entries marked
   **Your retained confirmed work**. Inspect your own work and its state; do not
   interpret a claim as confirmed work or an interval as proof of attendance.
   Use **Log out** before the next account. Ordinary tabs share login state.

You can stop here. The remaining checks deliberately change or end this synthetic
Programme, so do them only after reading/printing what interests you.

## Optional public offline copy

Use only the **public** download for this short exercise. The launcher supplies a
separate trusted public-key file and an exact verifier command. No signing secret
or password is written to that folder. Verification files remain after disposal.

1. Return to **Public programme**, choose **Refresh now and next**, then
   **Download signed snapshot**. Note the **actual new filename** in Downloads;
   browsers may add `(1)` or another suffix. Do not accidentally use an older file.
2. Copy this new file to the exact `incoming.maru.json` destination printed by
   the launcher. Do not copy the download over `trust.json` or `known.json`.
3. In a second PowerShell terminal, change to `C:\Users\TheMw\Documents\Maru`.
   Copy the two command lines under **PUBLIC OFFLINE CHECK** from the launcher.
   Run them promptly: this fixture's signed snapshot lasts **five minutes**.
4. Expect successful verification and an `initial.html` file. Open that local
   file in your browser. Check its historical-copy warning, scope, source time
   and timetable. The October 5 maintainer report confirmed correct display of
   this local HTML; it remains a human observation rather than an automated check.
5. If the verifier refuses the file, stop using it. Record the message. An expired
   download is recoverable by taking a fresh snapshot and trying again before
   expiry. Do not change your clock, reset history or disable verification.

For later downloads in the **same session**, retain `known.json`, omit
`--initialize`, and choose a fresh output filename such as `withdrawn.html`.
Initialization is only for the first successful verification. Previously generated
HTML is not recalled or kept fresh automatically; stop using it after a known
withdrawal or expiry. This exercise does not establish private-copy custody,
complete disconnected operation or archive acceptance.

## Optional withdrawal and Programme stop

1. Sign in through **Administration** as **planner**, select the same synthetic
   workspace using **Change** → **Choose a workspace** → **Switch**, and search
   **Find a task or record** for `Programme`.
2. Open **Release timetable**, then **Withdraw the active timetable**.
3. In **Reason for this change**, paste:

   > Withdraw the fictional timetable before testing Programme stop.

4. Check **I have reviewed this exact action and its consequences:** and press
   **Withdraw this active timetable**. Expect **Confirmed withdraw receipt**.
5. Refresh **Public programme**. Expect **Programme withdrawn - obtain replacement
   instructions**, with normal timetable rows withheld. A previously opened tab
   is not current evidence until refreshed.
6. Optional offline follow-up: download the new withdrawn snapshot and verify it
   using the retained `known.json`, without `--initialize`, into `withdrawn.html`.
   It must not restore the earlier timetable. The assistant also verified that
   an earlier, still-unexpired available snapshot is refused after this history
   learns about withdrawal.
7. Use **Log out**, then sign in as **organizer**. Open the exact **Stop Programme**
   URL printed by the launcher. This dormant test page currently requires that
   explicit link; it is not a normal navigation entry.
8. Read **What stopping means** and **Complete impact preview**. Stopping this
   adoption retains history and work commitments; it does not cancel the convention
   or silently complete shifts. In **Reason for stopping Programme**, paste:

   > End this disposable rehearsal while retaining its history and commitments.

9. Check **I understand that Programme will stop, its timetable will be withdrawn,
   and retained history and commitments will not be erased or completed.**
   Press **Stop Programme and retain history**.
10. Expect **Programme is stopped**, your recorded reason and a receipt, with
    read-only context and no ordinary reopen action. Save your observations and
    use **Log out**. Then dispose the terminal session below.

Withdrawal and stopping are different actions requiring different accounts. If
the preview says the active release still needs withdrawal, return to the planner
step rather than trying to grant the organizer extra authority. This walkthrough
does not supply archive authority or ask you to retrieve a restricted archive.

## What this short guide leaves for later

The core covers call creation; the prepared session covers output, withdrawal and
stop. Proposal collaboration, review decisions, planning edits, publication,
restricted archives, independent-person observation and specialist screen-reader
acceptance remain separate checks in the
[acceptance evidence map](programme-acceptance-evidence.md). A further `--stage items`
starting point is supported for focused item work, but is not an additional task
you need to complete for this guide. A maintainer operating several fictional
accounts does not count as several independent participants.

## Stop, restart and preserve your notes

1. Save your observations outside the test site. Avoid copying passwords,
   invitation links or raw private downloads into your report.
2. Log out in the browser.
3. In the original PowerShell terminal, type `stop` and press Enter.
   Closing **Programme test accounts** requests the same session cleanup.
   Account copying stops immediately; wait for terminal completion.
4. Wait for **DISPOSED - the test session has ended.**, then
   **COMPLETE - child exited normally and disposal was confirmed.** and the
   terminal prompt. Record an error or missing completion message rather than
   assuming normal completion. Use the written `stop` command for this walkthrough.

You can return to the same browser session while the original process and lease
remain live. **There is no cross-session save/resume:** stopping or expiry removes
its disposable data. Running the command again creates a new URL, database and
passwords. Resume your testing at the appropriate prepared stage, recording the
new session separately. Old downloads and links do not become current again.
Do not delete unrelated Docker containers to reset this test.

The rehearsal server does not reload Python form changes automatically. To see
the 24-hour controls, save your notes, finish and dispose any older session using
the steps above, then start a fresh `--stage team` session from this checkout.
Refreshing an old page alone is insufficient. You can inspect **Create a call
draft** without submitting another draft if you only want to check the clock.

## Your notes

Copy this table into whatever note-taking tool you prefer. One sentence is enough.
Leave later steps untested when you stop.

| Step / account | Worked, Confusing or Blocked | What I expected | What happened / screenshot |
| --- | --- | --- | --- |
| Startup | | | |
| Login and workspace | | | |
| Create call draft | | | |
| Optional prepared public view | | | |
| Volunteer view / print | | | |
| Optional continuity / exit | | | |
| Logout and disposal | | | |

Include the commit printed at startup, chosen stage, approximate time and the last
successful step. If a message appears, copy its wording. You do not need to
diagnose the cause or complete the rest before reporting it.
