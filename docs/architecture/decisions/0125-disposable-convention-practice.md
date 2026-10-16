# ADR 0125: Disposable convention practice

- Status: Accepted; implementation verification in progress
- Date: 2026-10-15
- Requirements: OPS-008, UX-031, NFR-013, ANN-001–009, KNO-010–013

## Context

The maintainer wants two useful, current fictional conventions that newcomers can
try without constructing authority or switching many technical settings. The
legacy educational fixture cannot supply exact authority-provenance evidence.
Private acceptance fixtures have a different credential boundary, including the
native clipboard controls described in OPS-008 and ADR 0115. A browser cannot
promise exclusion from operating-system clipboard history or synchronization.

## Decision

The disposable local launcher defaults to one ongoing and one future MaruCon,
with draft, waiting-review and approved examples for Announcements and Guides.
It creates a fresh, owned PostgreSQL database, migrates under its migration owner,
provisions the existing restricted runtime contract unchanged, activates exact
authority provenance during stopped maintenance and seeds through owning commands
under the real runtime login. Content preparation is atomic. No receipt/history
row is fabricated, no guard is disabled and no unselected workflow is seeded.

Separate synthetic Authors and Reviewers work in both areas. Readers see approved
Guides only: Announcements staff view also admits working/history details and is
therefore not granted to Readers. Setup operators and platform oversight do not
imply content authority. Prepared decisions are labeled synthetic preparation,
not independent-human acceptance.

An explicitly enabled development-only loopback page deliberately presents the
six generated content accounts as public local practice credentials. It is not
mounted in production. It rejects non-loopback peers/hosts, is not cacheable, and
exposes no platform/setup password. Passwords remain in the launcher and child
environment, never output logs or persistent files. Copying requires an explicit
action and works while a password is masked when the browser permits clipboard
access. On refusal, the password stays masked and the page focuses its deliberate
reveal control, explaining how to reveal, select and manually copy it. Visible
fields retain selection-based manual copying. A manual clear button is provided.
The page explains that browser copying cannot
exclude OS clipboard history/cloud synchronization. It does not automatically
erase a later copy from another application.

This is restricted to disposable synthetic exploration on an unshared local
machine, not a shared demo service or a tunnel. It does not replace or relax the
private acceptance facilitator, its clipboard contract, prior approval refusals,
or any production credential rules.

Dates use one recorded Europe/Budapest creation anchor. Reloads preserve edits,
dates and history. Existing data causes preparation to refuse. A new launcher
invocation starts a new database; it is not a recovery mechanism. Normal exit or
expiry removes only the exactly owned resource. The original dataset remains
available as an explicit legacy scenario.

## Consequences and verification

Newcomers can practice writing, independent review and approved reading without
granting themselves authority. There is no browser authentication bypass. Native
checks must verify rollback/retry, scope denials and preserved edits; startup
checks must use the genuine runtime login. Browser evidence must cover role
switching, copying masked values, ordinary workflow controls and narrow layouts.
Existing safety, coverage and delivery gates remain unchanged. This first demo
does not establish all-module coverage, independent human or production acceptance.
