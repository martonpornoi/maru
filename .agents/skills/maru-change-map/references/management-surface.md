# Management-surface reference

Read this reference when changing Maru's management shell, personal surface,
navigation, forms, task pages, drawers, or visible workflow state.

## Purpose and placement

- Name the surface after the human task, not an implementation number or model.
- Give it one canonical route and one place in the shared navigation grammar.
- Keep platform, organization, edition, administrative, and personal contexts
  visibly distinct. Context never grants authority.
- Lead with decisions, work, exceptions, and continuations. Specialist records
  remain progressively available without becoming a second product shell.
- A planned capability may have one truthful non-interactive roadmap home; it
  must not appear as a dead or executable-looking link.

See the [management shell contract](../../../../docs/product/page-contracts/00-management-experience-shell.md)
and [experience architecture](../../../../docs/product/experience-and-information-architecture.md).

## Page contract

Define before implementation:

- audience, purpose, route, scope, authoritative data, and field ceiling;
- view, edit, approve, and administer authority with safe denied behavior;
- empty, populated, validation, stale, conflict, dependency-failure,
  read-only, denied, success, overflow, and recovery states;
- preceding and following tasks, with every destination authorizing again;
- desktop, intermediate, narrow, keyboard, assistive-technology, and reduced-
  motion behavior;
- tests, manual evidence, documentation, and honest remaining acceptance gaps.

## Shared interaction grammar

- Preserve one page H1 and the host's one `main` landmark.
- Use ordinary links, buttons, labels, fieldsets, status text, and visible focus.
  Color, icon, position, and hover are never the sole meaning.
- Creation belongs beside its owning resource. Destructive and high-impact
  actions explain consequence, confirmation, recoverability, and rationale.
- Modal drawers expose a labelled dialog, move and contain focus, close on
  Escape, isolate and scroll-lock the background, and return focus to the
  opener.
- Avoid page-level horizontal overflow. Convert dense narrow lists to labelled
  cards when that preserves context better than a local scroll region.
- Show a computed Access explanation without disclosing hidden principals or
  turning it into a manually maintained page ACL.

Use [UX-005 through UX-008, UX-012, UX-019, UX-020, UX-027, and UX-029](../../../../docs/product/requirements.md)
as the maintained acceptance authority.
