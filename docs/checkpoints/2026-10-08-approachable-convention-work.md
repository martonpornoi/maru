# Approachable convention work and contributor entry

Date: 2026-10-08
Status: Development milestone; clean exact-commit certification and protected
review remain the delivery boundary.

## Outcome and authority

The maintainer authorized unattended implementation using recommended product
choices, approved Astra Extra High subagents, deferred Programme #48 completion,
and requested larger coherent batches. This batch addresses the first-run human
experience and public contributor path before adding more operational modules.
It implements UX-031 and ADR 0116, refining UX-027 and ADR 0049's visible flat-menu
rule while preserving a single authorized registry.

## Product changes

Six purpose groups organize the available menu: Overview, People & teams,
Registration & shop, Applications, Places & equipment, and Settings. Account and
Advanced records are secondary. Current groups open; search recognizes older
terms; pins and context remain authorized on every render. Scoped rows keep event
context visible, including two equal labels for different editions. Empty and
unauthorized groups remain absent. Native disclosures and the script-free mobile
fallback preserve usable navigation.

Team workspace replaces the prominent Workforce label. Applications explains
activity ideas, fixed versions and contributor confirmation in ordinary English.
Required rules, consent, approvals, versions needed for retry, and consequential
actions retain their existing semantics. Optional technical detail is collapsed;
invalid optional and form-editor inputs reopen their panels. Required reference
codes without an approved resolver remain visible, blank and explained.

README, contributor instructions and the existing newcomer pages lead with furry
conventions, current capabilities and an optional local tour. Setup has one owning
path and uses the database actually created by Compose. Missing invitation-worker
keys are explained without claiming that basic sign-in delivers invitations.
CURRENT is reduced to a handoff; historical ADRs, checkpoints and failed evidence
remain available. Remote description/topics were inspected but not changed.

## Verification performed during development

- Navigation focused Python tests: 76 passed. Navigation JavaScript behavior:
  five passed, including search, current group, custom pins and Escape behavior.
- Applications focused tests: 563 passed; follow-up form-editor tests: 84 passed.
  Four new cases check visible field/command errors and unchanged retry/version
  data. Changed templates compile; scoped lint and formatting pass.
- Complete inexpensive Python feedback: 13,585 passed in 76.87 seconds, with
  three existing Django URLField warnings. Later focused home cases pass
  separately; final clean certification must include every latest case.
- Full frontend suite: 108 passed; type checking and production build pass.
  Generated browser assets are included. Technical disclosure behavior is also
  checked in the authenticated browser; its focused test is retained.
- Fresh disposable PostgreSQL setup: all migrations applied, a synthetic
  administrator was created, ordinary sign-in and the empty Organizations page
  worked. The normal synthetic demo seed then supplied organizer roles; ordinary
  organizer sign-in, event selection, Team workspace, menu navigation and the
  closed/open technical setup disclosure worked in the actual local application.
  The final authenticated home had one H1/main and no horizontal overflow at
  measured CSS widths 320, 390, 768, 958, 1024, 1280 and 1920. Requested browser
  sizes were calibrated against innerWidth because the existing browser zoom
  changed the resulting CSS width; no native 200-percent zoom claim is made.
- A synthetic already-authorized real-template menu fixture covered full and
  restricted menus at seven requested viewport settings (not independently
  calibrated CSS widths), keyboard focus containment and return,
  search clearing, Advanced records gateway and a script-free fallback simulation.
  The latter exposed and repaired inherited CSS specificity that hid the menu.

The first complete unit invocation encountered Windows shared-temp permission
errors. A fresh worktree-owned temporary directory resolved them. Two old tests
also exposed the changed header's extra noscript element and missing direct OCI
evaluator links. The upload assertion now targets the upload panel's actual
fallback sentence; concise evaluator links were restored without relaxing their
test. A frontend invocation from the repository root failed file resolution;
rerunning from its documented frontend directory passed. Logs remain separate.
A warning-fatal documentation build identified one nonexistent requirement fragment;
the maintained link now targets the requirements document. The final certification
must perform its own fresh warning-fatal build. Database feedback passed 129 of 130
expanded cases; the remaining old Workforce-label expectation was corrected and
rechecked separately. No production behavior or authorization assertion was removed.
Independent review also found hidden event context, closed invalid editor panels,
stale walkthrough labels and duplicated workspace wording; all were repaired.

## Boundaries and recovery

No migration, data conversion, authorization expansion, API rename, production
route or profile activation is included. UI mutations still use the same commands,
CSRF controls, expected versions, retry keys and independent approval boundaries.
Reverting this presentation batch does not require a data rollback.

These are assistant-operated synthetic and automated observations. Actual
JavaScript-disabled browser operation, specialist screen-reader acceptance,
independent-person/non-native-English comprehension and production use are not
claimed. Programme #48/#92/#109/#108 remain open; this batch does not convert old
native, maintainer or browser observations into broader acceptance.

The candidate began at protected PR #208 squash `1fc8a216c96a7a42e7ab1f3bcec206eae50a1426`
in an isolated managed worktree. The original checkout's in-progress Programme
guides and local handoff remain untouched. Fresh exact-head local certification,
independent hosted acceptance, protected review and owned fixture cleanup must be
verified separately before delivery. Do not reuse previous candidate receipts.

The focused remaining database case passed in 2.46 seconds. The synthetic browser
session logged out normally, temporary viewport settings were reset, and both
development servers stopped. The exact owned Compose project and its database
volume were removed and their absence verified before the eight-worker pool.
