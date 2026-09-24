# Programme stop authority boundary

Date: 2026-09-21

Continues #190 inside the approved #48/#108 exit bundle and ADR 0111. Native
Events terminal admission and the complete stop preview/command remain unfinished;
this does not close P11 or activate a profile.

Authorization 0040 fences fresh grants, assignments, resource bindings and guided
request/decision writes in stopped Programme context, including a guided request
for a broader shared Venue grant. Actual shared Organization authority and other
editions keep their existing meaning. Exact retained revocation remains possible
only through the existing current-authority boundary, with unchanged issuance
fields and matching same-transaction native Audit evidence. No new helper EXECUTE
grant, blanket revocation, new privilege, deletion or artificial decision occurs.

The existing commands use Audit's public mutation-evidence boundary only for a
successful stopped-edition revocation. They consume its minimized audit identity,
not another owner's private model query. Other audit paths remain unchanged.
The new native guard requires matching principal, object, scope, operation,
changed fields and witness transaction; a matching operation elsewhere in the
transaction does not authorize arbitrary changes. Normal used reversal checks
the retained stop receipt before removing any guard.

## Verification

- Initial actual stopped-scope native tests: nine passed in 7.47s.
- Expanded native tests plus existing authority commands and guided Programme
  role workflows: 144 passed in 160.54s (2m40s), report
  `.tools/programme-stop-authorization-native-2.xml`.
- Audit routing, guided-role metadata, isolated helper permissions and CI
  inventory: 121 fast tests passed in 1.07s.
- Full source typing: no issues in 776 source files.
- Final focused native file after SQL-string formatting: 16 passed in 12.91s,
  `.tools/programme-stop-authorization-native-3.xml`.
- Complete fast run25: 12,943 passed in 69.74s with three existing URL-field
  warnings, `.tools/programme-exit-bundle-units-25.xml`. Ruff, formatting,
  docstrings and documentation validation pass (674 Markdown files).

The native negatives include issuance, scope escape, recipient/reason/duration
changes during revocation, missing native audit, unrelated same-transaction audit,
unknown request scope and disabled-trigger readiness refusal. Real public
revocation creates the matching witness; shared Organization and other-edition
grants still execute. Terminal states are isolated native test arrangements,
not evidence that a complete Stop Programme command has executed.

The isolated guided-role fingerprint includes the additive guards while preserving
the exact existing helper list. The new native file has a conservative uncalibrated
300-second CI inventory weight, pending final exact-commit timing/coverage evidence.
Applications, Programme, Venues and Events terminal closure, complete preview/UI,
genuine integrated races/recovery and final protected delivery remain outstanding.
