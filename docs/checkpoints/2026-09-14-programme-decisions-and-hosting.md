# Dormant Programme decisions and hosting workspace

Date: 2026-09-14
Scope: Second bounded #108 increment under #48; not activation or final acceptance.
Base: protected PR #112, `f64c96ed7e1912121de476d6ad4332b4c330b448`.

## Contracts and behavior

The [item page](../product/page-contracts/programme-item-workspace.md) and
[hosting page](../product/page-contracts/programme-host-workspace.md) contracts
map PRG-005/006/008, IDN-014, UX-029 and NFR-013 to the existing Programme owner
commands and ADRs 0081/0087. No new writer, migration, privilege, profile pin,
production route or automatic message delivery is introduced.

Department discussion, typed readiness source selection and exact public-copy
withdrawal have independent fields and write authority. Source queries read only
exact IDs/versions/labels under locks and required audit, not private source
bodies. Latest withdrawn public copy cannot become evidence through an older-copy
fallback. Historical privacy-withdrawal choices are complete and bounded, not
publication claims; the owner retains current-person and privacy-exit rules.

Organizers see labelled rosters with separate history/shared-availability grants.
New invitations require one known verified address and deliberately composed
host-visible copy. Reinvitation/removal select exact existing relationships.
The personal inventory, responses and purpose-owned availability never query
organizer layers or accept another subject. Native minute inputs reject ambiguous
or missing DST times. Explicit complete-set draft/share and separate withdrawal
retain original source/retry identity, without private reasons, automatic copying
or reopening closed planning. Changed edition source versions refuse stale forms.

Bounded compositions compare item/relationship versions before combining labels
and history or shared availability. Pending input is reauthorized before echo;
unknown/duplicate fields, forged subjects, oversized rows and absent CSRF are
rejected. Failure discloses no partial private content. Removal is pending until
submission, not immediate erasure. Rollback removes dormant adapters only;
existing immutable owner history and recovery procedures remain unchanged.

## Verification and corrected feedback

- Final focused database-free forms, HTTP, typed source queries and closed
  read-purpose attribution passed 218 cases in 2.13s, including timezone and
  explicit evidence-selection regressions. Strict typing passed all six selected
  modules; NumPy docstrings passed the seven selected modules.
- Seven tests of the actual availability-row JavaScript passed in 1.18s total,
  including labelled unique rows, focus, pending guard, unchanged command tokens,
  no submission/autosave, fixed 128 bound and malformed/missing controls.
- HTTP tests caught availability formset transport reaching a strict top-level
  decision form. The adapter now splits form and formset data only after the
  request-wide closed-field and duplicate checks. Initial test whitespace and
  aggregate-version attribute assumptions were corrected without weakened checks.
- Four maintained native cases (three typed-source/withdrawal, one real
  form-to-host-command lifecycle and stale-version path) are **not executed**
  under ADR 0100. They remain #102 debt; no PostgreSQL timing, combined coverage,
  real workflow or database certification is claimed.

Exact-head retained local certification and independent protected hosted checks
are still required. Focused results are not a successful certification receipt.
The first exact run at `4dd0e7e18da3b71625799d3b9eeec2c22f9bc199` failed full
mypy because five existing Scheduling calls unpacked UUID-only dictionaries into
the extended read signature. These callers now explicitly specify the unchanged
`timetable` purpose. No successful receipt is claimed for that run; the corrected
commit must pass fresh full typing and retained certification.
Full-source mypy subsequently passed all 596 modules, and 84 existing personal
release-impact/change-notice regressions passed in 0.70s with the explicit purpose.

## Synthetic browser evidence and explicit gaps

The disposable loopback fixture forbids database connections and substitutes
owner queries, authority and commands. CSRF is disabled only in that fixture;
real-view CSRF refusal is covered separately by HTTP tests. At 1280 by 720,
the browser showed explicit blank invitation copy, separate My Maru invitation
navigation, native local-minute fields, added-row focus, visible pending state,
and stale refusal retaining the original periods and command source tokens.
The availability page did not overflow horizontally at that viewport.

Browser feedback found Django's template localization converting the explicitly
zoned edition envelope back to the default zone. Local conversion is now disabled
for those already-zoned display values, with an exact Europe/Budapest offset
regression. The browser recheck shows the intended `+02:00` envelope and explicit
pending period-removal language.

Labelled item navigation also exposed separate Department discussion, typed
evidence choices and exact historical withdrawal with explicit confirmation.
Review of those pages made readiness concern/outcome selection explicit blanks,
so a fresh form does not imply satisfied evidence by default; a regression checks
all three decision selectors. The fixture does not validate real source authority.

These observations do not prove real authorization, persisted commands, full
viewport/keyboard coverage, genuine zoom, native discard controls, screen-reader
behavior or integrated end-to-end usability. Those remain unchecked #92 work;
#109 owns the complete isolated journey. No user's system setting was changed.
The disposable fixture servers and their tabs were stopped/closed after the
rehearsal. #102 comment 5657375804 records native debt; #92 comment 5657375935
records the explicit unchecked human tasks.

## Next increment

After protected delivery, continue #108's Applications call/proposal/collaborator/
review/conversion tasks, followed by authorized continuations and setup. Keep
#48/#108 open. #102 restoration, #97 recovery and #92/#109 acceptance still gate
final profile promotion. Documentation/quality latency is recorded separately
under #113 and does not displace #48 unless it blocks delivery.
