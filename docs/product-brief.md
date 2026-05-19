# Product Brief

## Goal

maru should make furry convention operations easier to understand than a
generic conference tool. The platform should use the terms staff already use:
projects, subprojects, applications, panels, shifts, hotels, rooms, profiles,
and signage.

## Core Concepts

| Term | Meaning |
| --- | --- |
| Project | One convention edition. |
| Subproject | One operational area inside a project, such as event submissions or dance competition volunteering. |
| Application | A submitted form response. |
| Panel | An approved event application that can be scheduled. |
| Shift | A volunteer duty block on a timetable layer. |
| Profile | A public/internal profile visible after approval. |
| My Events | A read-only archive of a user's past panels and applications. |

## Authentication

- Google-only login.
- Every account must use a Gmail or Googlemail address.
- Access is controlled by an allowlist of email addresses and assigned roles.
- Seed test account: `marton.pornoi@gmail.com`.
- Login should not imply full profile access. A user can submit forms first;
  profile setup unlocks after any application is approved.

## Roles

Predefined roles:

- Admin
- Board
- Event Manager
- Security
- Fursuit Support
- Themeing
- Host
- Volunteer
- Registered User

`Admin` and `Board` have full control, including starting new projects.

## Projects And Subprojects

A project is a specific convention. A project can contain many subprojects:

- Event submissions
- Dance competition volunteering
- DJ applications
- Fursuit support applications
- Security volunteering
- Generic internal forms

Each subproject owns forms, review workflow, approval state, timetable layer
rules, exports, and profile visibility rules.

## Forms And Applications

Forms should preserve Google Forms labels exactly, because imported spreadsheets
and staff conversations usually use those names.

Applications should be reopenable. Reopening should preserve the previous
submitted version and create a new editable version, so admins can compare what
changed.

## Timetable Rounds

The timetable has staged visibility:

1. Private placement: approved hosts place only their own panels.
2. Host negotiation: approved hosts can see enough information about other
   panels to coordinate time conflicts themselves.
3. Public: all registered users can see the full timetable.

The timetable also needs layers:

- Panels
- Volunteer shifts
- Signage/reminders
- Staff-only operational blocks

## Profiles

Approved users can maintain a profile with:

- Display name
- Profile picture
- Fursuit picture
- Fursuit name
- Telegram handle
- Discord handle
- Short bio
- Participation history
- Ongoing panels/shifts/applications

## External Surfaces

maru should expose secure read APIs for:

- Official website timetable
- Approved volunteer lists, for example dance competition volunteers
- Profile pictures where consent and visibility allow it
- Digital signage reminders
- Printable timetable output

Exports should be token-scoped and audited.

## Non-Goals For First Build

- Email notification system. Notifications are internal only.
- Public anonymous account creation beyond Google login.
- Copying pretalx code or UI terms.

