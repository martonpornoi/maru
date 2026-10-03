# Programme synthetic credential delivery repair

Date: Prepared 2026-10-03; applied and verified locally 2026-10-04
Scope: OPS-008 maintainer facilitator; PR #207 supporting #48/#92/#109
Status: Local repair feedback, not protected delivery or human acceptance

## Failure and changed boundary

The first PR #207 head `f69d6a5a6f73ea3d30cc169942008545162be0d9` failed
CodeQL check `111261541482` for clear-text password logging at
`tests/rehearsals/programme_hands_on.py:256`. Requiring an interactive terminal
did not prevent transcripts from retaining the generated passwords. The alert
was not dismissed, suppressed or treated as harmless because the users are
synthetic. Its failed evidence and the original local certification are retained
separately; neither certifies the changed candidate.

The Windows helper now receives authenticated accounts into a local Tk window.
The terminal renders only session metadata, entry links and public verification
instructions. The account window shows role/email and offers **Copy email** and
**Copy password**; password values never reach widgets, logs or credential files.
Desktop/clipboard availability is checked before starting a native fixture.

A deliberate copy uses CF_UNICODETEXT only after all three documented
[Windows privacy formats](https://learn.microsoft.com/en-us/windows/win32/dataxchg/clipboard-formats#cloud-clipboard-and-clipboard-history-formats)
are installed. Failure has no ordinary clipboard or logging fallback. Expiry
after 30 seconds, role changes and shutdown clear only the unchanged owned copy,
with both owner and sequence checked while holding the clipboard lock. Windows
adds synthesized formats when closing the clipboard: capture the sequence after
that finalization, as verified on this machine. A later external copy is retained.
Busy cleanup is retried; unresolved cleanup prevents COMPLETE and asks the user
to replace the clipboard with harmless text. A crash cannot guarantee cleanup;
other applications on the same machine can read a deliberate copy while present.

Closing the window disables account copying and requests the existing child stop.
Window errors also request owned child cleanup, with no credential-bearing
tracebacks. Normal terminal stop, EOF, interrupted reads, finite leases and child
disposal checks retain their existing boundaries. The original encrypted session
entrypoint remains available; there is no new web route, application grant,
production schema/profile, self-approval exception, lease renewal or activation.
ADR 0115 remains unchanged.

## Verification and limits

- Focused staged feedback passed 39 cases covering authenticated delivery without
  stdout/stderr disclosure, failed privacy-format publication, memory ownership,
  expiry, later-copy preservation, clipboard contention, desktop failure and
  child cleanup. The repair was staged outside tracked source while the original
  certification remained in flight, avoiding mixed-source attribution.
- Native Windows account-window smoke verified role/email presentation,
  deliberate copy/paste equality without exposing the inert generated canary,
  the three privacy formats, expiry and normal window disposal. The first expiry
  attempt exposed the clipboard-finalization sequence change; the repair's native
  probe and corrected window run then confirmed no text format remained after
  expiry. No actual account password was written to smoke evidence.
- A real supervisor/desktop/pipe lifecycle check used an inert encrypted protocol
  peer, with no database or real accounts. Closing the observed account window
  produced DISPOSED and COMPLETE and returned exit zero. This verifies the new
  GUI stop path, not another execution of the full native Programme fixture.
- The walkthrough now uses the actual window/control labels and documents
  prerequisites, copying, errors and disposal. Earlier browser/core workflow
  evidence is retained in the previous facilitator checkpoint and is not
  attributed to a new head.
- The original clean `f69d6a5` certification completed successfully at
  2026-10-03 22:23:35 UTC in 15,283.578 seconds (4h14m44s): 18,585 Python cases
  across 72 reports, with no failures, errors or skips; all 71 PostgreSQL shards
  and 91.73% combined coverage passed. Shards took 405.859–2,891.562 seconds and
  every measured headroom/owned-cleanup check passed. All 5,045 `.local-ci` files
  were copied and SHA-256 compared before the source changed; original wrapper
  logs and the observed CodeQL failure are retained with that archive. The local
  receipt does not override the failed hosted security gate.
- After applying the staged repair in the repository, 104 focused cases passed
  in 0.95 seconds and all 13,529 database-free units passed in 79.65 seconds,
  retaining three existing Django URLField warnings. Repository-wide Ruff/format
  passed for 1,670 files; documentation validation passed for 714 Markdown files,
  four repository skills and 215 unique requirements. Whitespace checks passed.
- Fresh clean exact-commit certification, then exact-head hosted acceptance,
  PR gate and CodeQL remain required before readiness and protected squash merge.
  No inherited receipt is reused.
- Native printing/local HTML visual inspection, restricted archive/custody,
  independent-person and specialist accessibility acceptance, #108 promotion
  and #48 closure remain separate. This account window is not an accessibility
  acceptance result or a production password-management feature.
