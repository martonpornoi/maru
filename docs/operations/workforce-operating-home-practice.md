# Practice the Workforce operating home

**Audience:** Contributors and evaluators using fictional local data\
**Outcome:** Follow Assignments, shared Availability and Shift closeout from Home\
**Contracts:** UX-032, HR-012–014 and ADR 0128

This is a separate disposable Workforce-only preview. It creates no attendee,
Registration, payment, attendance, Announcements or Guides workflow. Existing
manual-test accounts, saved records, checklists and services are not used.
Prepared synthetic decisions are not independent human acceptance.

## Start and choose a role

From a checked-out repository with the [local prerequisites](../start-here/run-locally.md):

```sh
uv run --locked python scripts/try_maru.py --scenario workforce --minutes 60
```

Keep the terminal open until the printed Ready link appears. Open that link,
normally <http://127.0.0.1:8765/demo/workforce/>. Expand a practice role, copy its
generated email/password and sign in through the normal form. Platform and setup
operator passwords are not displayed. Do not reuse the generated passwords or
expose this loopback-only page through a tunnel.

Each edition has its own accounts:

| Role | Work available | Deliberate limit |
| --- | --- | --- |
| Manager | Structure, Assignments, shared Availability and Shifts | Cannot approve their own Assignment proposal or confirm their own claim. |
| Reviewer | Assignment decisions and Shift review/management | Cannot edit team structure; ordinary owner-page checks still apply. |
| Volunteer | Own application/Assignment, private Availability and suitable Shifts | Cannot see organizer-only rosters or the other edition's work. |

Return to `/demo/workforce/` and use **Sign out to switch roles** before changing
accounts. No link signs you in, grants a role or approves a decision.

An independent decision may open **Confirm it is you**. Paste the same current
role's password into **Current password**, choose **Confirm session**, then
review the returned record and submit the decision. This normal security step
does not approve the record for you.

## Future event: make one coherent plan

1. Sign in as the future **Reviewer**. Open Assignments and review **Welcome
   helper**. Check the requirements and retained proposal, then approve or reject
   using the existing page. The Manager made this proposal and cannot approve it.
2. Switch to the future **Volunteer**. The sign-in link opens **My Availability**.
   Review the private draft and choose whether to share it. Only deliberate
   sharing makes periods available to organizers. A deliberately shared empty
   plan means unavailable; private/missing input does not.
3. Switch to the future **Manager**. Open Shifts and review **Future welcome
   desk**. Review Position, local times and work instructions before opening claims.
4. As the Volunteer, open **My shifts**, review suitable work and claim it. A
   claim is not confirmation. Return as the Reviewer for the independent decision.
5. As the Manager, review coverage and choose whether to lock it. A changed or
   withdrawn Availability version requires review; Home never bypasses that check.
   To rehearse recovery, withdraw the Volunteer plan, observe the changed-evidence
   guidance and refused lock, then share a new plan as that Volunteer. The
   Reviewer can use **Review confirmation again** to check the new evidence
   before locking complete coverage. Keep the understaffing exception unchecked.

## Ongoing event: follow Home through closeout

1. Sign in as an ongoing **Manager** or **Reviewer** and open **Home**. Use
   **Change event** if this edition is not selected. The primary suggestion and
   **Other team work** cover only independently admitted areas, at most four total.
2. Follow a waiting-claim or changed-evidence suggestion to its ordinary Shift
   page. Make the permitted decision and return to Home. Refresh to see current
   guidance; there is no activity polling or task tracking.
3. The locked **Short closeout practice** Shift ends five actual minutes after
   creation. Check its displayed edition-local end time. After that time, refresh
   Home: **Review an ended, locked Shift** takes priority over pending decisions.
4. Follow that link, review the retained work and choose **Complete** when
   appropriate. Refresh Home again. The completed record remains in authorized
   history and the next existing work becomes the continuation. Completion records
   planned work; it does not establish attendance or a human handover.

## Failure, privacy and stopping

Missing access omits an area. A source, freshness, limit or mandatory-audit failure
shows generic unavailable guidance for that area while other admitted areas and
direct tools stay available. No private person label, rationale, document or exact
personal Availability period belongs in a Home card. A quiet checked area does
not establish whole-event readiness. Destinations authorize again.

Reloading preserves decisions, dates and history for this preview. A seed rerun
refuses existing data. A new invocation creates a separate timeline and database.
Press **Ctrl+C** or let the lifetime expire to stop the server and remove only its
owned database/volume. Never prune other containers or reseed another rehearsal.
Clear copied practice data with the page's clipboard button when finished.

Automated native and synthetic browser evidence is distinct from representative
owner, two-human, screen-reader, recovery, operational and production acceptance.
