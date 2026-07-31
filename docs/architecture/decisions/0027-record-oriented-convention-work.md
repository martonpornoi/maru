# ADR 0027: Record-oriented Convention work and contextual setup guidance

- Status: Accepted
- Date: 2026-07-31
- Supersedes: ADR 0022 global Quick Start placement
- Extends: ADR 0026 original administration shell
- Requirements: UX-001, UX-003, UX-006 through UX-012, NFR-001 through
  NFR-003

## Context

ADR 0026 correctly restored Django administration as Maru's single global
shell, but its embedded API-backed workflows retained the typography, large
hero cards, rounded panels, spacing, and internal toolbar of the former
standalone Staff Console. Moving Convention work to the top of the same menu
therefore did not make it feel like the same site.

The ADR 0022 Quick Start also appeared in the global administration header on
every page. Its eight-step panel consumed substantial vertical space after the
operator already understood the setup sequence, while Convention work's Setup
guide already owned the guarded first-authority and lifecycle workflows.

## Decision

Keep the safe API-backed workflow implementation, but make its embedded inner
pages follow the record-oriented visual language of specialist Django pages:

- one Django header, user menu, edition selector, breadcrumbs, and sidebar;
- compact page title and purpose help;
- Django-like modules, field rows, forms, tables, buttons, status labels, and
  spacing;
- responsive behavior aligned with specialist record pages; and
- no embedded application hero, second top bar, or competing display
  typography for administrators.

The Django administration edition selector remains visible on embedded
workflow pages. It supplies preferred working context to the embedded client;
the API still re-authorizes every request. Active non-staff accounts retain a
compact in-content edition selector because they do not have Django record
administration access.

Remove the global Quick Start strip and the duplicate administration-home
setup panel. The ordered setup narrative remains inside Convention work's
Setup guide, beside the guarded one-time leadership ceremony, lifecycle
transitions, registration preparation, workforce structure, and closeout
readiness. The complete administration directory remains available for direct
record lookup.

## Consequences

Convention work and specialist records now read as two kinds of inner page in
one administration product. Returning administrators regain vertical space on
every page. New administrators still have one discoverable setup path, but it
does not become permanent global chrome.

Removing navigation guidance from the header does not remove any capability or
record path. Setup guide links remain permission-aware and its guarded
ceremonies continue to call the same commands and APIs.

## Alternatives considered

- Restyle only the sidebar: rejected because the inner workflow typography,
  panels, and toolbar were the main remaining visual split.
- Collapse Quick Start by default: rejected because it still occupied global
  chrome and duplicated Setup guide.
- Reimplement workflows as ordinary model forms: rejected because lifecycle,
  authorization, audit, and transactional command services remain the
  authoritative behavior boundary.

