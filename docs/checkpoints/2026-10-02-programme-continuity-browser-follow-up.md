# Programme continuity: bounded browser follow-up

Date: 2026-10-02. Issues: #92/#109 within #48. Requirements: SCH-012,
OPS-009, NFR-013 and UX-029. ADRs: 0103 and 0115.

## Observed browser evidence

Assistant-operated synthetic run `9c5edaa336ab4e4ba15e900671e436bf` started from
protected `911002068dd5acb89ac4e4a8c46b60c1081c6097` with a 3,600-second lease.
The published fixture used automated setup/intake/review/planning/work/release
prerequisites; those decisions are not browser or human acceptance. The loopback
bridge ran on port 49204 over the fixture's pinned HTTPS backend.

- The anonymous public now/next view displayed three released events, pointer 1,
  current room/venue labels and reviewed public copy. Scope, release, Budapest
  time zone, source time, historical-copy and replace/dispose warnings were visible.
- Public and authenticated volunteer views each passed DOM geometry checks at
  **320, 390, 768, 958, 1024, 1280 and 1920 CSS pixels**: one H1, one main,
  no page-level horizontal overflow and no overflowing main descendants.
  Screenshots at public 320 and personal 390 showed readable stacked content.
  These observations are not native browser zoom or specialist screen-reader proof.
- Actual Tab focused the public skip link with a visible three-pixel outline
  inside the viewport; Enter navigated to its timetable anchor. The public
  print-copy link displayed the complete content and printing instructions,
  without the download/navigation controls. Native print pagination was not run.
- Ordinary volunteer sign-in reached its own now/next view: three retained
  confirmed work intervals and current work instructions. It explicitly reported
  hosting/release **unobserved**, without acquiring general release discovery.
  The browser error log was empty at this observation.
- The signed-snapshot link produced a 5,283-byte JSON file for that exact
  volunteer/personal scope, no optional layers, unobserved release, key
  `fixture-9c5edaa336ab4e4ba15e900671e436bf`. Its SHA-256 was
  `6236470a76b0d98d93ea33be8e265a837f4cd46bd8124c28db576162fc404c38`.
  The declared issue/expiry were 08:20:04/08:25:04 UTC. This is observed metadata
  and download evidence, **not independent signature verification**.

## Interruption and limits

A several-hour wall-clock gap occurred while the download operation was pending:
the file creation time was 16:07:03 UTC, after the original lease and pack expiry.
The cause of that gap was not established. The later print request reached a
connection-refused page; logout could not proceed. Neither is an application
failure or a pass for the intended interaction. No expiry or clock was extended.

The terminal returned `disposed` and exit zero. Read-only inspection confirmed
both exact owned containers, the parent processes and port 49204 listener absent.
The temporary viewport override was reset. The browser's internal error URL was
blocked by its inspection policy and was not bypassed. Operator/host views,
native print/zoom, disconnected verification and archive/stop remained unperformed
in this run. No role grants, domain mutations or production activation occurred.

## Narrow preparation repair

Inspection found that the interactive published launcher generated independent
public verifier trust but did not hand it to the facilitator. It now includes the
existing public policy only inside the encrypted recipient handoff. The normal
closed trust decoder rejects unknown/private-key fields; additional checks bind
one key to the exact fixture run, Organization and edition. Other stages expose
no policy. The issuer's signing secret, five-minute pack lifetime, original fixture
lease, authorization and production behavior are unchanged.

Ten new focused assertions initially failed because the handoff did not exist;
the first implementation exposed a noncanonical test JSON fixture, corrected to
the same canonical encoding as real preparation. Expanded stage, scope, secrecy,
refresh/EOF/diagnostics and disposal checks now pass **36 / 0.35s**, with Ruff and
formatting passing. Documentation validation passes: 707 Markdown files,
four skills and 215 requirement IDs before this checkpoint was added.

The first complete unit attempt was interrupted after temporary-fixture setup
errors. A bounded reproduction confirmed `WinError 5` on the pre-existing system
`pytest-of-TheMw` directory, before the test body. The old directory was untouched;
the new attempt uses a fresh explicitly owned base. Interrupted results are not
certification. Complete feedback, native handoff use and exact bundle certification
must be recorded separately when finished.

Next: provision public trust before a fresh browser download, verify expected
purpose and known-state behavior without resetting history, then exercise the
remaining authorized operator and exit paths. Genuine-human, operational-owner,
specialist accessibility and final profile-promotion gates remain open.

## Subsequent focused completion

The fresh-temp complete database-free run passed **13,477 / 75.69s**, with the
three existing Django URL-field warnings, zero failures/errors/skips and exit zero.
Its XML is retained locally as `programme-exit-units-20261002-r2.xml`.
Documentation validation then passed 708 Markdown files, four skills and 215
requirement IDs; whitespace checks passed. This is inexpensive feedback, not an
exact-commit certification receipt. Native public-trust handoff use remains pending.

The exact hash-verified expired synthetic snapshot was moved out of Downloads into
the run's ignored evidence folder, without overwriting another file. Its hash is
unchanged. It remains available for failure analysis and is not an operative copy;
no encrypted real-device custody or secure-erasure claim is made.
