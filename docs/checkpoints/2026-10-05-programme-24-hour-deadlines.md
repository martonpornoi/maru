# Programme maintainer feedback and 24-hour deadlines

**Date:** 2026-10-05\
**Status:** Local implementation and verification above protected `dec2ca5`; not a protected delivery\
**Scope:** Applications deadline controls used by Programme call creation and window editing

## Maintainer report

The maintainer reported: “The core journey went well. No issues.” They also
reported that the small date-time picker used AM/PM, making noon and midnight
confusing, and requested hours from 0 through 23.

This records their successful short call-draft journey from the maintained
walkthrough. The report did not supply an exact startup commit, browser version
or session transcript; no additional observations are invented. The documented
protected baseline was PR #207's `dec2ca5f52613eb7706f37388ba0283a9596481c`.
Optional sessions, independent participants, specialist accessibility, operational
ownership and production activation remain separate. #48 is not closed by this
report or by the fix.

## Resulting behavior and boundaries

The native calendar remains available under **Date**. A separate **Time (24-hour)**
control accepts `HH:MM` from `00:00` through `23:59`, with visible midnight/noon
guidance. Browser AM/PM settings cannot change that clock. This is the shared
Applications deadline widget; unrelated modules' date controls were not changed.

NFR-006 and the Programme call workspace contract now require this behavior.
The widget joins the date and clock for the existing edition-zone validator.
Whole-minute precision, DST gap/fold refusal, deadline chronology, metadata's
exact-instant preservation, edition-version fencing and owner command boundaries
remain intact. Explicit request allowlists include only the new declared date/time
parts. Duplicate parts, mixed scalar/split representations and unknown fields
remain invalid. Canonical scalar submissions are retained for compatibility.
The HTML works without JavaScript and preserves values and field-error references.

No schema migration, authority change, additional collection or ADR is needed.
Recovery is reverting this presentation change; stored instants are unchanged.
Existing protected-delivery documentation edits and unrelated worktrees were
preserved. The retired PR #207 automation was not restarted.

## Verification

- 332 focused form/view cases passed, including the actual creation and window
  HTTP adapters, midnight/noon/end-of-day clocks, winter/summer offsets,
  nonexistent/ambiguous times, invalid/partial input, duplicate/unknown/mixed
  transport, initial localization, retained error values and accessible labels.
- All 13,559 database-free unit cases passed in 90.37 seconds. Three existing
  Django 6 URL-field deprecation warnings remain; no new failures occurred.
- Changed-source Ruff, strict typing and NumPy docstring checks passed.
- Documentation validation passed for 716 Markdown files, four repository skills
  and 215 unique requirement identifiers. A fresh Sphinx HTML build passed with
  warnings treated as failures; its log is `.tools/date24-docs.log`.
- An isolated loopback component rendered the real shared form widget and
  Programme call stylesheet. The in-app browser confirmed `00:00`, `12:00` and
  `23:59` submit with the correct Budapest offset, `24:00` is refused by the
  browser, and a DST-gap submission is refused while retaining both inputs.
  Tab moved from the clock to the next date; the calendar opened and Escape
  returned focus to its button. Labels were visible in the accessibility tree.
- The component was visually checked at wide and 320px **content widths**, where
  controls stacked without clipping. This was not the full seven-viewport/zoom,
  screen-reader or genuine-role acceptance matrix. No live maintainer session
  or normal database was used. The temporary component server and tab were closed.

Local evidence is retained under `.tools/date24-focused.xml`,
`.tools/date24-units.xml`, `.tools/date24-units.log` and
`.tools/date24-controls.png`. These checks do not transfer PR #207's certification
to a changed source tree. No full PostgreSQL certification or hosted acceptance
was run for this local follow-up.

## Next step

The walkthrough now uses **Date** and **Time (24-hour)** explicitly. To inspect
the change, save observations and dispose an older rehearsal normally, then start
a fresh `--stage team` session from this checkout. The finite WSGI process does
not reload Python form changes. Disposal removes the old synthetic session data;
opening the new draft form is enough to check the clock without repeating the
whole successful core journey. Protected delivery remains separate work.
