# Admin-only GUI manual-test preparation — 23 October 2026

## Request and scope

Prepare a local from-empty test for Saturday, 24 October: one platform admin,
no ordinary accounts, organizations, series, editions or other project data;
all subsequent accounts and convention setup are the maintainer's GUI work.
No application behavior, migration, dependency, permission or profile was changed.
No commit, push, PR or production deployment is part of this request.

The [checklist](../operations/blank-start-manual-test.md) contains thirteen main
steps for accounts, governance, organization/series/edition creation, registration
draft construction, Departments/Positions, assignment, Availability, Shifts and
the bounded rota copy. Seven optional branches cover validation/stale forms,
conflicts, further editions, Announcements, Guides/help desk, accessibility and
privacy/resume. Inputs and decision reasons are fictional and copy-ready.

## Local ownership and starting state

The attached `blank-start-manual-test` worktree, branch
`codex/manual-test-from-empty`, starts from protected commit
`7bd59c0bf1130a7ebc8b202d0f47b2bc26c9182b` (PR #221). The private host bundle is
`C:\Users\TheMw\Documents\Maru\.tools\manual-test-20261024`.
It holds Start/Stop launchers, the initial login file, public web/private worker
invitation keys, logs, local mail, rendered interactive guide and verification.
Credentials and keys are intentionally absent from tracked documentation.

The dedicated labelled container is `maru-manual-20261024-pg`, persistent volume
`maru-manual-20261024-data`; PostgreSQL uses the existing pinned 17.11 image on
loopback port 55424. Maru uses 8044 and the guide/local inbox 8045. Normal locked
dependencies and migrations were installed. The first superuser was created by
the supported management command. No demo seed or ordinary-account ceremony was
run. All business model inventories were zero; the one admin and framework /
explicit invitation-retention-policy controls are technical bootstrap records.

The identity worker alone receives the private decryption key. The local web
uses normal local settings, a file-based mail backend and distinct session/CSRF
cookie names. No external mail is sent. Start resumes rather than recreating
the database. Stop validates recorded process command ownership and the exact
container ID/label, waits for the invitation worker to finish, and preserves
the volume/mail/notes. There is no destructive reset action or automatic expiry.

## Verification performed

- Normal migrations, Django system checks and migration-current checks passed.
- The actual browser admitted the initial administrator and displayed one
  platform account, zero organizations and no selected event. Invitation and
  organization-creation forms loaded without creating business records.
- The organization inventory's Add action is absent in the current shell.
  The guide links the actual mounted creation form and labels the navigation
  gap; generic model administration remains inspection-only.
- The rendered guide displayed labelled controls, one H1/main and no normal
  desktop-width overflow. A tick and private note survived reload; all ticks
  were then cleared and the note blanked. The guide has 113 checkboxes, anchored
  sections, a local inbox link and a notes download action.
- Stop/Start preserved the exact admin password and the one-account/zero-project
  inventory. Nine unrelated stopped containers retained their exact IDs/states.
- Documentation policy and `git diff --check` passed for this local handoff.

The browser checks are a preparation smoke check, not completed manual mainline
acceptance. No additional account or convention was made by the agent. The
maintainer will enter each invited person's password and accept invitations.

## Limits and next action

Registration currently supports the canonical draft builder; activation/public
checkout and the successor writer cutover are not claimed complete. Programme
activation/timetable remains gated. Volunteer Shifts supply the available
schedule journey. Future Shifts cannot be truthfully completed before their end.
No account, profile, native guard, capability, clock or production acceptance
boundary was bypassed to manufacture a result.

Use the Start shortcut, private login and checklist tomorrow. Save observations,
then Stop to retain work for diagnosis. This environment is separate from the
old #42 recipient-owned acceptance boundary, which remains untouched; no
independent-human, specialist accessibility, operational, recovery or production
gate is closed. Any product repairs or repository delivery are subsequent work.
