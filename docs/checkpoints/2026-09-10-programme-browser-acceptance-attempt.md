# Programme browser acceptance: partial attempt

Date: 2026-09-10. Issue #87 under #48; UX-029, SCH-011 and ADR 0092.

## Exact source and fixture

Application source was the protected staffing squash
`dca412e97dfa40371e01db3222105f87cf9d4562`; only post-delivery documentation
was edited during the attempt. The opt-in `tests/rehearsals/programme_timetable.py`
fixture used a dedicated loopback PostgreSQL 17.11 container, test database and
finite lease. Its printed menu URL was `http://127.0.0.1:50412/rehearsal/`.
This was synthetic owner/test-policy evidence, not a production route, profile,
runtime-role, real-login or human acceptance claim. No real personal data was used.

## Observed evidence

The user-approved Chrome connection opened the synthetic planner's native
Create a private draft form. A unique synthetic draft name and rationale were
entered without submitting the create command. All input/select/textarea
name, value and checked-state tuples except CSRF were captured, including the
exact retry identity. Clear filters triggered a native `confirm` dialog.

The supported dismiss action timed out during browser focus emulation. After
read-only connection recovery, the native dialog was absent, the original
form and unsaved notice were visible, both entered texts remained intact, and
the complete captured field tuples matched exactly. This establishes Cancel
retention for that attempt despite the control-transport timeout.

Clear filters was requested again and a second native `confirm` was observed.
The supported accept action timed out. Subsequent page and screenshot inspection
also timed out; the screenshot attempt ultimately reset the browser-control
session. Although a later dialog query reported none, intended navigation and
discarded state were not verified. Deliberate discard therefore remains open.

Genuine 200% zoom and enabled reduced motion were not exercised. Windows
Settings failed to expose a targetable window after launch and a fresh window
listing. No zoom, viewport override or accessibility preference was changed.
The browser family was Chrome, but its exact version was not captured; repeat
the remaining checks with explicit browser-version evidence. No automated or
responsive-width result substitutes for these missing observations.

## Verification and cleanup

All 64 existing frontend tests passed in 27.24s. The intended file filter also
ran the other two frontend files; this result is the complete frontend suite,
not a separately measured focused-file run. Documentation validation passed
and `git diff --check` was clean before this checkpoint was added.

Browser cleanup could not reach the visible Finish button after connection
failure. Only the exact fixture Python processes and label-verified disposable
container were stopped. The database was ephemeral and is not recoverable;
no production or unrelated data was removed. This is interrupted fixture
cleanup, not a passing fixture test. No reminder was created and no test
container remains. The synthetic browser tab may remain until browser cleanup
or user closure; its loopback service is stopped.

## Continuation

Keep #87 and all activation gates open. Restore a working Chrome connection,
then repeat controlled Cancel/deliberate discard with exact field and intended
navigation evidence, genuine 200% browser zoom, enabled reduced motion and
browser-version capture. Preserve normal fixture cleanup and restore every
temporary preference. Screen-reader, representative-human, runtime-role and
integrated Programme-only acceptance remain separate mandatory work.
