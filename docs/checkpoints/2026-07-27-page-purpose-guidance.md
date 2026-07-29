# Page purpose guidance

Date: 2026-07-27  
Requirements: UX-006, UX-008  
Outcome: concise orientation is present below the inner title of every active
Maru page

## Delivered

- Added a reusable Staff Console page-help pattern that states the page's
  purpose and one concrete interaction example.
- Applied it to Today, People, My registration, Commerce, Security, workspace
  absence, permission-denied, loading-failure, and registration-unavailable
  states.
- Added equivalent guidance to the local landing and Staff Console sign-in
  pages.
- Added model-specific help for every registered bootstrap Django admin model,
  plus administration index, application index, sign-in, password-change, add,
  and change surfaces.
- Kept the copy visually secondary, short, responsive, and immediately below
  each page's main heading.

## Decisions

- Guidance is orientation, not a substitute for labels, validation, or
  documentation.
- Examples use user-facing tasks rather than UUIDs or storage terminology.
- Permission-denied and error pages still explain the intended purpose without
  disclosing protected records.
- Active and published registration versions remain immutable; this change
  does not alter configuration lifecycle or authorization.

## Verification

- Focused backend tests cover the landing page, both sign-in surfaces, admin
  index/application/list/change pages, and every registered admin changelist.
- Staff Console tests navigate all five active destinations and assert their
  purpose guidance.
- All 270 backend tests pass with 90.06% branch-aware coverage.
- Ruff format/lint passes 145 files and strict mypy passes 102 source files.
- TypeScript type checking, all 11 frontend tests, and the production build
  pass.
- Documentation validation passes all 66 Markdown files and 164 requirement
  identifiers.
- A real-browser walkthrough checked Staff Console at desktop and 390-pixel
  mobile widths and a populated Participations admin list. Guidance remained
  readable and no runtime console errors were reported.

## Follow-up

The next UX boundary is a first-class visual registration form builder. The
current draft editor supports questions and products in bootstrap admin but
does not yet provide named sections, drag-and-drop ordering, preview, or a
friendly remove/archive interaction.
