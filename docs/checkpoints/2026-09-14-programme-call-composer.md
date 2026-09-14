# Guided Programme call creation and structured form composition

Date: 2026-09-14. Scope: #108 within #48's delivery decomposition.
Base: protected PR #115, `ae97565ff03005a730ef8d492e2a1f72b04318e7`.
Branch: `codex/programme-call-composer`.

## Outcome and contract

The dormant Applications call workspace now supplies explicit draft creation,
section metadata and first-question creation, all seventeen closed question types,
typed earlier-question conditions, bounded labelled choice-option rows, ordering,
confirmed removal and atomic same-call cross-section moves. The existing owner
commands and whole-graph validators remain authoritative. There is no second form
engine, domain writer, schema change, profile promotion or production route.

The [page contract](../product/page-contracts/programme-call-workspace.md) was
extended before implementation. Requirements IDN-014, PRG-001/002/008/009/011,
AUD-001/003, PRI-001, UX-005 through UX-008, UX-019/020/027/029 and NFR-013 map
to ADRs 0051/0082/0084/0085 and the existing owner contract. No ADR is superseded.

Creation discloses and requires confirmation of the initial title/description
questions and lead-name collection policy. Metadata, policy references, deadlines,
track and format are operator inputs; no policies, people or public copies are
invented. The displayed edition version and timezone remain fenced under the
canonical lock through creation. Existing-draft composition retains its original
cursor and retry key and refuses stale source state without silently rebasing.
Reordering, movement and removal must leave a complete valid graph. No dependent
condition is silently rewritten or deleted, and mandatory sections remain nonempty.

All routes retain login, CSRF, exact Department/organization/edition authority,
protected-read audit, reauthorization, private no-store responses and closed
single-valued transport. Draft removal uses the existing audited configuration
command and explicit confirmation; it deletes no active or historical record.
No new migration or recovery operation is needed. Reverting these dormant
adapters leaves the existing owner schema and history unchanged.

## Verification

- Final focused composer feedback: 101 database-free cases passed in 1.78s.
  Coverage includes every question type, canonical signed condition values,
  full-graph preservation, option addition without writes, retained original
  evidence, timezone/version fences, removal/movement refusal, closed transport,
  authentication/CSRF/authority boundaries and unavailable dependencies.
- Fresh complete unit preflight: 6,274 passed in 38.61s, with only the two
  existing Django URLField transition warnings. The preceding cheap full-unit
  attempt passed 6,272 and failed one in 38.87s on the historical assertion that
  every Applications template directly extends the admin shell. Its narrow
  repair checks this exact composer's inheritance through the existing call
  template, which must itself extend the admin shell. Production route-tree and
  generic-surface containment guards remain intact. No failed attempt is a
  successful certification receipt.
- Focused Ruff, formatting, three-source-module typing and NumPy docstring
  checks pass. Exact-head all-gate certification and protected PR delivery are
  still pending at this implementation checkpoint.
- Three maintained native cases in `test_application_programme_services.py`
  parameterize initial creation, conditional editing and cross-section movement
  through the real owner commands, protected reconstruction and exact receipt
  replay. They were not run or collected. ADR 0100 continues to defer PostgreSQL
  suites; #102 owns their eventual execution and coverage/timing acceptance.

Early focused feedback corrected the canonical contributor field code, signed
integer parsing, removal-label initialization before Django caches bound fields,
and runtime-versus-type-checker formset inheritance. Those failures are diagnostic
feedback, not evidence of a successful exact-commit run.

## Synthetic browser evidence

Two successive isolated loopback fixtures used synthetic projections, mocked
authority/queries/commands, fixture-only CSRF exemption and a hard database
connection refusal. Successful commands redirect without persisting changes.
This rehearsal cannot establish native authority, persistence, concurrency or
end-to-end acceptance.

At 1280 by 720 CSS pixels, the browser exercised grouped draft creation and
explicit initial collection confirmation; option-row addition retaining pending
input; partial-option validation; stale refusal retaining intent; cross-section
movement and adding a section with its first question. It also verified Active
read-only output and the generic denied creation response without private labels.
The page retained one H1/main and no page-level horizontal overflow (1265 pixels).
Feedback added exact error-summary links, focus on the new option row and an
explicit draft-option-removal label. A settled validation response focused its
error summary; clicking its Option 5 label error focused that exact input.

Both owned fixture servers were stopped and their rehearsal tabs closed. No
unrelated services, user settings or production data were changed. Other widths,
genuine zoom, keyboard-only/screen-reader/touch journeys, native discard prompts
and representative operator comprehension remain unchecked #92 work.

## Remaining delivery and activation gates

#108 and #48 remain open. After this increment's exact-head protected delivery,
continue labelled authorized Department selection/reassignment, contributor-owned
proposal/collaboration tasks, independent review/decision/conversion and ordinary
task continuations. Accountable setup and integrated proof remain #109; database
restoration #102, recovery #97 and human acceptance #92 precede Programme promotion.

#113 records the previous PR's 29m36s hosted quality job, only 24 seconds below
its 30-minute limit. This increment does not claim guaranteed timing headroom or
change CI policy. Any actual timeout becomes a protected-delivery blocker; no gate
is bypassed. PostgreSQL remains unexecuted, with no combined coverage or native
readiness claim.
