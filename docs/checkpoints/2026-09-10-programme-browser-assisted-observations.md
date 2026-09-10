# Programme browser acceptance: assisted observations

Date: 2026-09-10. Issue #87 under #48; UX-029, SCH-011 and ADR 0092.

## Source and scope

The fresh opt-in synthetic planner fixture ran at
`http://127.0.0.1:53829/rehearsal/` from
`263f460e8b39bfacde2c87b0c91abe2e9b33b203`, a documentation-only successor
of protected application source `dca412e97dfa40371e01db3222105f87cf9d4562`.
It used its own loopback PostgreSQL test database and one-hour lease. The older
port 50412 fixture was already stopped and was not used for these observations.
No application code, production profile, route or runtime grant changed.

The maintainer performed the following actions in Chrome and reported the
visible results in this task. They supplied the version from About Chrome:
**152.0.7977.83 (Official Build), 64-bit**. Browser-control reads repeatedly timed out, even
though Chrome remained responsive to the maintainer. These are user-observed
synthetic checks, not agent-inspected DOM, screenshot or preference measurements.

## Native Cancel and deliberate discard

In the current fixture, the maintainer entered `Cancel test` in both the
private-draft name and reason, without creating the draft. Clear filters followed
by native Cancel retained both entries. An earlier report of missing entries
was clarified: the maintainer had been inspecting Choose draft and filter the
board, not the private-draft form. No Cancel defect was established.

Clear filters followed by native OK removed the Create a private draft section,
including the name and reason inputs. This verifies the visible discard/reset
outcome. No create command was requested. The assisted attempt did not independently
compare hidden retry identities or inspect database state. The earlier
[partial attempt](2026-09-10-programme-browser-acceptance-attempt.md) separately
records exact field/retry retention after Cancel; its failed discard inspection
is not rewritten as successful.

## Genuine browser zoom

The maintainer used Chrome's menu to set actual zoom to 200%, then selected
First draft. The populated view contained two Opening ceremony working title
inventory entries: one placed Friday at Convention Hotel / Main Stage and one
unplaced. The Day and room board displayed preparation and delivery datetimes.
The maintainer confirmed no page-level horizontal scrolling and readable,
reachable board text, dates and controls without clipping. This was not a CSS
zoom or responsive-viewport substitute. No automated DPR/viewport measurement
was obtained, and this narrow observation does not certify every editor state.

## Enabled reduced motion

The maintainer turned Windows Accessibility / Visual effects / Animation effects
off while leaving the current Maru tab open. Following the requested board-scroll
and item-selection check, they confirmed the view remained usable without
distracting movement or controls depending on animation. The browser's
`prefers-reduced-motion` value and computed styles could not be read because
browser-control communication remained unavailable.

The maintainer explicitly chose to keep Animation effects off. Do not restore
that preference without a new request. Chrome zoom restoration has not been
confirmed.

## Remaining handoff

The fixture emitted `REHEARSAL_CLOSED: fixture cleanup only, not automatic browser
acceptance` and exited successfully: one fixture test passed in 2,005.56 seconds
(33m25s). That duration measures setup and the interactive lease, not test-suite
performance or automatic UX acceptance. The exact task/purpose labels, tmpfs
database storage, auto-remove setting and container identity were checked before
stopping `maru-issue87-browser-retry1`. A subsequent exact-ID inventory was empty.
Only disposable synthetic data was removed; it is not recoverable. No unrelated
container, persistent development data or production data was removed.

After fixture closure, the maintainer set Chrome to 200% again and used Tab on
the retained editor page. They confirmed that fields were visibly highlighted
and kept in view. This establishes the previously missing zoom-specific focus
observation without a server request; it is not an additional mutation test.

Documentation validation passed for 441 Markdown files and all four repository
skills; the whitespace check passed. No application repair was made.

The three deferred checks now have bounded observed evidence, with the manual
and automated limitations above retained. Keep #87 open until its evidence is
delivered through the appropriate protected checks. The earlier staffing
certification remains separate exact-revision evidence. Screen-reader, representative
end-to-end departmental use, provisioned runtime and integrated Programme-only
acceptance remain separate. #48 and all activation gates remain open.
