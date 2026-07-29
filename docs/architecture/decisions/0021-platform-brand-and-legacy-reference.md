# ADR 0021: Platform brand and behavior-only legacy reference

- Status: Accepted
- Date: 2026-07-29
- Requirements: UX-007, UX-008, UX-010, REG-014, FUR-010, NFR-002

## Context

Maru has an earlier clean-room prototype in the private
`martonpornoi/maru` repository and a newer uncommitted local checkout. That
prototype established a recognizable cat-in-a-box mark, navy/amber/ivory
palette, and useful workflow experiments for programme, shifts, venues,
publishing, exports, and archives.

The current repository has stronger tenancy, authorization, audit, privacy,
registration, finance, media, workforce, and closure boundaries. Copying the
legacy Django models or views would reintroduce global project assumptions,
email-allowlist identity, mutable cross-domain writes, and archives or exports
that do not meet the current data boundary.

Maru also distinguishes its stable operational surfaces from convention-owned
annual public websites. The platform needs a coherent identity without turning
its reference registration client into the only acceptable frontend.

## Decision

Adopt the owned static Maru identity package as the platform brand:

- preserve `#071B3A`, `#B9822E`, and `#FAF3E3` as the navy, gold, and ivory
  anchors;
- maintain documented tonal scales and semantic aliases in the neutral
  `maru.core` static namespace;
- use the favicon, application icons, square marks, and rectangular wordmark
  across bootstrap administration, Staff Console, local entry/login, and the
  bundled public reference client;
- keep semantic success, warning, danger, and attendee-status colors separate
  where they communicate operational meaning; and
- require WCAG 2.2 AA contrast and text or icon meaning in addition to color.

The legacy application is a behavior reference, not an implementation
dependency. Useful behavior is mapped to stable current requirements and
implemented later through the owning current module, application services,
scoped authorization, audit, APIs, and tests. No legacy model, migration, view,
or personal/runtime media is imported.

Convention-owned annual clients remain replaceable under ADR 0010. They may
replace page structure and theme while using the same versioned API and cannot
override availability, authorization, price, capacity, payment, or lifecycle
truth.

## Consequences

Maru gains a consistent visual identity and a documented source for future
assets. The gold anchor is not suitable as ordinary text on ivory, so darker
gold is used for small text and the anchor remains an accent or receives navy
text.

The Staff Console source repeats the palette anchors needed by its standalone
Vite development build; tests detect drift from the canonical core stylesheet.
Brand assets increase repository size by roughly two megabytes but remain well
below GitHub's large-file threshold.

Future programme, schedule, shift, venue, announcement, and export work can
reuse validated workflow lessons without inheriting the prototype's security
or data-model limitations.

## Alternatives considered

- Keep the newer green provisional theme: visually coherent, but discards the
  owned identity the organizer explicitly selected.
- Copy the legacy application wholesale: faster superficially, but incompatible
  with current tenant, privacy, audit, and modularity decisions.
- Defer all legacy review until each future module: avoids present work, but
  risks losing the uncommitted prototype's useful behavior and acceptance
  details.
