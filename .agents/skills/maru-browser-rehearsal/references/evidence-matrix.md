# Browser evidence matrix

Select the applicable cells before opening the browser. Record **not
applicable** with a reason rather than silently omitting a contract state.

## Roles and scope

- anonymous or signed-out person;
- self-owned participant or volunteer;
- relationship-bounded organizer;
- view-only, manage-only, approve-only, and independently authorized decision
  roles where those capabilities differ;
- platform administrator without convention participation;
- same-organization wrong edition, other organization, expired/revoked, and
  inactive account;
- two distinct people and fresh sessions when independent approval is part of
  the contract.

## States and transitions

- initial discovery and truthful empty state;
- populated ordinary work and the complete happy path;
- invalid or missing input with preserved recoverable form state;
- stale optimistic version, replay, capacity or lifecycle conflict;
- dependency unavailable, bounded overflow, and safe retry guidance;
- read-only, denied, hidden, archived, cancelled, or otherwise closed state;
- success confirmation, retained rationale/history, and the next sensible
  action;
- rollback or reload proving that a failed mutation left no partial state.

## Responsive and visual evidence

Use contract-relevant widths. UX-029's complete matrix is 320, 390, 768, 958,
1,024, 1,280, and 1,920 CSS pixels plus 200 percent zoom. Check:

- no page-level horizontal overflow;
- readable hierarchy, line length, contrast, spacing, and status without color;
- labelled local scrolling only where dense data genuinely requires it;
- useful narrow cards or stacked fields without losing row context;
- touch targets, long synthetic text, empty values, and validation messages;
- reduced-motion behavior when animation or transition is present.

## Semantics and keyboard

- one page H1 and the host's one `main` landmark;
- unique IDs, programmatic labels, fieldsets, names, descriptions, and errors;
- logical tab order, visible focus, Enter/Space activation, and no keyboard
  trap;
- drawer or modal label, focus entry/containment/return, Escape close,
  background inertness, accessibility-tree isolation, and scroll lock;
- current navigation state and expanded/collapsed relationships;
- representative automated accessibility analysis and a screen-reader path
  when claiming broad acceptance.

## Privacy, authorization, and failure

- no protected names, counts, identifiers, reasons, availability, or tenant
  existence before authorization;
- no broader authority from navigation visibility, selected context, preview,
  or staff status;
- safe status codes and human guidance for denied, absent, conflict, and
  unavailable outcomes;
- no secrets, personal payloads, traceback, browser-console warning/error, or
  accidental cross-surface data in the rendered result.

Use [UX-007, UX-008, and UX-029](../../../../docs/product/requirements.md) and
the specific [page contract catalog](../../../../docs/product/page-contracts/index.md)
as the normative source.
