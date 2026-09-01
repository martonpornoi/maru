# Checkpoint: Django REST Framework 3.17.2 security update

- Date: 2026-09-01
- Issue: [#67](https://github.com/martonpornoi/maru/issues/67)
- Phase: Progressive adoption and pre-production release evaluation
- Related requirements: NFR-002, NFR-003, NFR-008, NFR-009
- Related decisions: ADR 0063

## Outcome

Maru's locked dependency graph resolves Django REST Framework 3.17.2 instead
of vulnerable 3.17.1. The existing declared `>=3.17.1,<3.18` compatibility
range is unchanged.

Upstream 3.17.2 fixes CVE-2026-73228, which allowed DRF JSON and URL-encoded
request parsing to bypass Django's configured in-memory request-size limit,
and CVE-2026-73229, which allowed `AdminRenderer` to expose GET-protected data
while rendering an invalid write. Maru configures only `JSONRenderer` by
default, but it does not retain known-vulnerable code merely because one path
is not currently selected.

## Decisions

- Keep the repair lockfile-only: the existing compatible patch range already
  admits 3.17.2 and no application workaround or audit suppression is needed.
- Treat the live dependency audit as a fail-closed mainline blocker discovered
  during issue #66 certification, not as Programme feature scope.
- Rebase and recertify the preserved issue #66 candidate only after this
  protected repair reaches `main`.

## Changed areas

- `uv.lock` package version, artifact URLs, sizes, and SHA-256 hashes for
  Django REST Framework.
- The Unreleased changelog and current handoff.

## Verification

The locked graph resolves exactly `djangorestframework==3.17.2`. `uv lock
--check`, locked environment synchronization, `pip-audit`, and the complete
non-database repository gate pass; both Python and frontend audits report no
known vulnerabilities. That gate also covers package-artifact verification,
Ruff, strict mypy across 411 source files, documentation policy, PyDocLint,
semantic docstrings across 425 source files, warning-fatal Sphinx/AutoAPI,
Django/system/migration checks, production settings, OpenAPI/generated
TypeScript stability, and all 33 Staff Console tests and its production build.
The complete 2,581-test unit suite passes separately.

Exact-commit local certification and the protected pull-request gate remain
the final delivery evidence and are recorded against the committed head.

## Data, migration, and deployment notes

There is no schema, data, configuration, authority, or API migration. A normal
locked dependency installation replaces the package artifact. Rollback to
3.17.1 is prohibited because it knowingly restores both vulnerabilities.

## Known risks and incomplete work

- Reverse proxies and deployment request limits remain defense in depth; they
  do not replace the corrected framework behavior.
- The Programme import candidate remains unmerged until it is rebased onto the
  patched dependency graph and independently certified.

## Recommended next actions

1. Merge this exact candidate only after the protected gate is green.
2. Rebase issue #66 onto the resulting `main`, repeat exact-commit
   certification, and resume its protected delivery.
