# Empty-experience baseline

Date: 2026-07-31
Status: Complete; product-owner acceptance pending

## Outcome

The product owner selected the empty-experience reset defined in UX-013 and
ADR 0030. Maru retains its tested Django modules, schema, services,
authorization, audit, APIs, migrations, fixtures, and preserved frontend
source, but the default browser experience now contains exactly two pages:

- `/accounts/login/`: local Sign in; and
- `/admin/`: an active-staff-only empty administration home.

`/` redirects to `/admin/`, and `/accounts/logout/` is a POST action. The home
shows Maru identity, the signed-in display name, Sign out, and one explicit
`Nothing here yet` message. It has no menu, edition selector, setup sequence,
recent actions, specialist records, embedded frontend, registration,
volunteer, or convention content.

Previous HTML pages are not mounted by `maru.baseline_urls` and return 404.
Health, build, schema, and versioned API routes remain mounted as JSON so the
backend can be carried forward without adding browsable-API HTML pages or
pretending its former page placement is accepted.

## Recovery and branch boundary

The full pre-reset state is preserved in three forms:

- verified temporary recovery folder
  `C:\Users\TheMw\AppData\Local\Temp\Maru-reset-snapshot-20260731-171759`;
- Git commit `548f15a`; and
- branch `codex/pre-reset-20260731`.

The page-by-page rebuild is on `codex/page-by-page-rebuild`. No pre-reset
database was flushed, dropped, or repurposed.

## Empty database

The new `maru_rebuild_empty` PostgreSQL database has all retained migrations
and exactly one account:

```text
Username: admin
Email: admin@maru.local
Display name: Maru Administrator
Password: M4rucon-Rehearsal-2031!
```

This is local test data. The account is the first database account, active
staff, and a superuser. Direct checks confirm zero organizations, convention
series, editions, registration configurations, registrations, departments,
and positions. The ordinary `maru` and populated `marucon_rehearsal` databases
remain unchanged.

## Authorization and behavior

- Anonymous administration requests redirect to Sign in.
- Valid handle/password authentication lands on `/admin/`.
- Authenticated non-staff accounts receive 403 at `/admin/`.
- Sign out accepts POST and does not add a third content page.
- Previous browser URLs return 404 rather than redirecting into a hidden
  alternate experience.
- Existing API authorization remains the data and command boundary.

## Visual evidence

The real running application was inspected at the default 1280-pixel viewport
and an explicit 390-pixel viewport. The empty home retains one heading and one
short message, has no old navigation or runtime console warnings/errors, and
has no horizontal overflow. The sign-in DOM and computed geometry retain
unique labelled controls and no horizontal overflow at the narrow breakpoint.

## Verification

- Dedicated baseline integration tests: 12 passed.
- Ruff format/lint: passed for 250 files.
- Strict mypy: passed for 179 source files.
- Django system check and migration drift: passed.
- Fresh migrations through identity `0009` and registration `0030`: passed on
  `maru_rebuild_empty`.
- Production-shaped deployment check: passed.
- OpenAPI 3.1 generation/validation and generated TypeScript types: passed.
- Preserved frontend: 20 tests and production build passed.
- Full backend suite: 443 passed with 90.11% branch-aware coverage.
- Documentation validation: 120 Markdown files and 186 recognized requirement
  identifiers.

## Next gate

The product owner must inspect and accept this baseline. Do not add navigation,
placeholder destinations, an organization form, or any other page before that
response. If accepted, the next candidate is the first-administrator/platform
state page, but it still requires the complete page contract in
`docs/project/RESET_REBUILD.md` before implementation.
