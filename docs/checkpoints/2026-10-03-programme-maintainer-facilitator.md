# Programme maintainer facilitator and browser evidence

Date: 2026-10-03

## Scope and decision

Continue #48/#92/#109 from protected PR #206, commit
`1fa3bb8359fde77e5eebdfd70fde379c4f2d1ae3`. The other development chat was idle;
its delivery checkpoint and CURRENT update were preserved. This follow-up applies
OPS-008, OPS-009 and ADR 0115 without changing production profiles, routes, grants,
schema, finite leases or the independent-person acceptance boundary.

`tests.rehearsals.programme_hands_on` gives a maintainer a private-terminal
facilitator for the existing team/items/published stages. It generates its RSA
recipient in memory, authenticates the encrypted handoff and displays newly
generated fictional accounts only on an interactive terminal. Redirected input
or output is refused. The published stage validates and saves only the independently
supplied public trust policy in a new run-specific directory; it never overwrites
verification history. Public verifier commands retain exact tenant/edition scope.

The maintained walkthrough supplies startup, workspace selection, every call-draft
field, current-date calculation, reason text, expected outcomes, a short core,
optional prepared output/withdrawal/stop checks and Worked/Confusing/Blocked notes.
Generated passwords remain in the local terminal rather than documentation or Git.
Prepared decisions are prerequisites, not observations attributed to the maintainer.
Stopping or expiry disposes progress; another stage is a new fixture, not resume.

## Browser and real-file observations

Ordinary synthetic accounts, current native application and the approved loopback
bridge were used; browser identities were never impersonated.

- Public now/next and the complete print-friendly page displayed all three
  prepared occurrences, source/scope and saved-copy warnings. Native print-preview
  completion was not observable and remains a human check.
- A first download completed after its five-minute validity and was refused by
  the verifier. A fresh actual download verified using independent public trust;
  a subsequent check using the retained known state also succeeded.
- A fresh available pack was verified, the planner withdrew through the ordinary
  reasoned form, and a new withdrawn pack verified into the same known state.
  The earlier pack was then refused and no requested output was created.
  That earlier pack was issued at 17:23:07Z and expired at 17:28:07Z; rejection
  was recorded by 17:23:56Z, so expiry alone does not explain the refusal.
- Public refresh withheld normal timetable geometry after withdrawal. The
  organizer separately submitted the exact stop preview with the supplied reason,
  received a retained terminal receipt, saw read-only **Programme is stopped**,
  and logged out normally. No archive grant was added.
- A fresh team helper supplied a working intake account. Through visible workspace
  navigation it created **Moonlit Makers: panels and workshops**, with the guide's
  initial track, format, questions and policy references, in draft state.
- A fresh published helper supplied eighteen persona cards and wrote only
  `trust.json`. Its ordinary volunteer login reached **My Programme now and next**
  with three retained confirmed work entries. This is assistant-operated evidence.

Local screenshots and public verification material are retained under
`.tools/programme-hands-on-browser-37817e353fe640738fdcf4b8df47de7e/`.
The browser tool refused local `file:` navigation; no workaround was attempted.
The generated HTML's visual inspection, actual disconnected use and private-copy
custody are not passed by CLI verification. Terminal capture wrapping caused two
initial incorrect synthetic login attempts; intact private card parsing succeeded.
Neither those captures nor the expired download is counted as a product defect.

## Startup and disposal repairs

The new helper exposed a Windows provisioning hang: noninteractive migration
children inherited a live command pipe already being read by another thread.
Giving provisioning children `DEVNULL` input restored native startup. Two owned
stalled migration processes were identified by exact PID, parent and command,
stopped, and their owners removed the matching containers. No broad cleanup ran.

The supervisor handles an already-broken input pipe without turning confirmed
disposal into a transport exception. Stop forwards EOF so the child's reader can
finish before interpreter shutdown. Ctrl+C is received while waiting on a queue;
it does not interrupt a Windows pipe read. Missing disposal or a nonzero child
exit remains failure. Native ordinary-stop disposal and exit zero passed;
an interrupted terminal showed disposal but returned nonzero and is not recorded
as a clean-exit pass. The final EOF adjustment receives another native smoke check.

## Verification and remaining work at this checkpoint

Focused confidentiality, trust, provisioning and shutdown checks passed
**115 / 0.79s**. Complete unit feedback passed **13,504 / 74.93s** with three
existing Django URLField warnings before the final EOF-reporting adjustment.
Ruff and documentation validation passed. Final feedback and clean exact-head
certification still need to cover the resulting source; PR #206's certification
does not certify this follow-up. There is no hosted acceptance or new merge yet.

The guide remains labelled a local candidate. Finish protected delivery, the
remaining independent archive/continuity checks and acceptance reconciliation
before claiming the requested complete handoff. #92 still needs genuine people,
screen-reader and owner evidence; #109 and #108 retain their own gates. No
production activation, schedule, machine trust change or new permission is implied.

### Final local follow-up

The final native normal-stop smoke reached READY, emitted DISPOSED and COMPLETE,
and exited zero. No helper/session process or Docker container remained afterward.
The raw-terminal-reader refinement avoids holding a Python buffered-input shutdown
lock. A separate harmless protocol-child probe used the final supervisor: written
stop exited zero; Ctrl+C emitted COMPLETE (proving child exit zero and disposal),
while the containing PowerShell command still returned its interrupted status.
This process-control probe is not additional Programme domain acceptance.
Focused final checks passed **115 / 0.77s**, and the intermediate complete unit
repeat passed **13,504 / 76.10s** before that last reader refinement.
All **5,043** existing certification files were SHA-256 matched to their already
preserved PR #206 archive before preparing to replace `.local-ci/`.

Final complete unit feedback on the raw-terminal-reader implementation passed
**13,504 / 73.75s**, with the same three existing Django URLField warnings.
