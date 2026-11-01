# Workforce accessibility rehearsal and bounded evidence

- Date: 2026-11-01
- Issue: #23 remains open
- Requirements: UX-007, UX-008, UX-029, UX-032; existing Workforce authority
- ADRs: 0077, 0078, 0080 and 0128 remain unchanged
- Scope: Contributor guide and recorded synthetic observations only

The maintainer authorized progressing through work that can be completed without
human participation, including partial issues with later manual validation. The
[rehearsal guide](../operations/workforce-accessibility-rehearsal.md) adds fifteen
task cards across distinct existing roles and ongoing/future fictional editions.
It covers supported setup, safe session isolation, original manual-data
preservation, seven CSS widths, actual zoom, themes, keyboard/drawer behavior,
semantics, stale input, denial, disclosure, recovery and exact owned cleanup.
It changes no application source, profile, authority, schema, API or demo fixture.

## Actual observations

Two ordinary separate Workforce previews used protected source
`a42205cb7d18fc59575982824a43bf66f9ff8139` and then
`82a351478773ab60ce6f195db4e9996e8832ba9f`. Their dates were prepared on
1 November 2026. Both used a separate in-app browser context, preserving the
saved manual environment and its host-scoped cookies.

The first signed-out path checked protected-route sign-in redirection, the
role picker and sign-in at seven requested widths, one H1/main and unique IDs,
no horizontal overflow, required labels/autocomplete, basic Tab order and
Space disclosure activation. No captured console warnings/errors occurred in
that bounded path. The role picker reserved a 15-pixel vertical scrollbar;
the sign-in viewport matched every requested width. Only the supplied light
presentation was observed. Screenshots in the task transcript show the closed
role picker and empty sign-in form; no credential card was exported.

Native application control timed out before zoom or a guest session could run.
The first in-app credential read returned redacted placeholders; one placeholder
sign-in was rejected generically. The second preview's ordinary Copy email
control reported success, but the browser transport returned an empty clipboard
and explicitly refused normal Ctrl+V. No authentication was submitted in that
second probe. These results establish tool/input boundaries, not a defect in
generated credentials or Maru's normal sign-in. No alternate credential source,
password reset, platform login, invitation acceptance or security change was used.

The normal Clear copied practice data control reported clearing its clipboard.
Both previews' task tabs were closed and viewport overrides reset. Each launcher
was interrupted normally and reported shell exit 1 plus cleanup. Independent
exact-ID inspection confirmed both owned containers and anonymous volumes absent.
All ten original stopped fixtures retained their IDs, names, images and exited
state, including the saved manual database. Records, credentials and the
113-checkbox manual guide were untouched.

## Remaining acceptance

Authenticated task cards W02–W15, actual before/after-end closeout, real 200% zoom,
dark/reduced-motion presentation, complete visible focus/drawer behavior and
representative screen-reader/owner, recovery, operational and production gates
remain open. No time was changed or backdated. Evidence from the two named source
commits does not certify a later source or establish the complete UX-029 matrix.
#23 stays open after this documentation increment.

The guide must receive normal final exact-head certification and independent
protected hosted delivery after incorporating the preceding comparison outcome.
Current local/source and hosted results must be recorded separately; no earlier
test receipt or signed-out screenshot supplies that acceptance.

Preparation feedback at protected base `82a35147` passed documentation policy
for 793 Markdown files, four repository skills and 223 identifiers covered by
its three-letter scan. Whitespace passed. This is development feedback only;
the subsequent main update and final exact-head acceptance remain required.
