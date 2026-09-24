# Programme local-only redirect hardening

Date: 2026-09-24
Status: focused implementation verified; exact-head and hosted acceptance pending

## Scope and evidence map

The maintainer requested addressing all seven open medium `py/url-redirection`
alerts before returning for #48's human acceptance. GitHub's current instances
were verified against main `eff8286b2c7dcff00e51159d76d70d61e7cd4745`:

| Alert | Owning adapter | Continuation |
| --- | --- | --- |
| [13](https://github.com/martonpornoi/maru/security/code-scanning/13) | Scheduling change notices | Exact sender/personal notice |
| [14](https://github.com/martonpornoi/maru/security/code-scanning/14) | Programme workbench | Exact item and selected task |
| [15](https://github.com/martonpornoi/maru/security/code-scanning/15) | Personal hosting | Own item invitation |
| [16](https://github.com/martonpornoi/maru/security/code-scanning/16) | Organizer hosting | Exact item roster |
| [17](https://github.com/martonpornoi/maru/security/code-scanning/17) | Applications decisions | Own exact decision receipt |
| [18](https://github.com/martonpornoi/maru/security/code-scanning/18) | Authorization role review | Original scoped access request |
| [19](https://github.com/martonpornoi/maru/security/code-scanning/19) | Workforce starter review | Original scoped starter request |

The four fixed-prefix destinations already use code-owned local roots and UUID
identifiers. This review does not assert an external-origin exploit through those
routes. Three other sinks reflected `request.path`; they now reconstruct the
canonical destination under the existing owning URLconf and original scope.
All seven use `core.redirects.local_redirect`, a domain-neutral HTTP primitive
with explicit empty-host-allowlist Django validation, absolute-local-path
requirement and backslash/control-character refusal. Invalid targets raise a
code-owned `SuspiciousOperation` (Django's 400 boundary), without echoing the target.

This implements the existing threat-model redirect control under NFR-001/002/003
and preserves the owning PRG-005/006/008, OPS-009, HR-012, IDN-012/014 and AUD-001
contracts and ADRs 0087, 0102, 0106 and 0107. No new architecture decision or
product authority is introduced. No schema, migration, runtime ACL, stored data,
profile, route mounting, receipt, audit or command changes. Recovery is ordinary
code rollback; retained workflow history is unchanged. Existing no-store/CSP,
CSRF, current authority, two-person control and idempotent retry remain intact.

## Focused verification and iterations

- **445 focused helper/HTTP tests pass in 3.49s.** New cases reject external,
  scheme-relative, malformed authority, backslash, control and non-absolute
  targets, preserve local path/query/fragment, and prove role/starter/both notice
  purposes ignore a hostile or aliased request path without repeating commands.
  Existing positive checks now assert exact local destinations for item, host and
  Applications continuations. Existing denied, foreign-scope, CSRF, conflict,
  field and retry cases remain selected.
- Earlier development runs exposed an incorrectly written expected Applications
  route and errors in a new redundant host test. The route expectation was
  corrected to the actual owning route; host assertions were integrated into the
  existing complete command tests without dropping their original assertions.
- Ruff format/lint pass after naming the HTTP control-character constants.
- The first complete unit invocation encountered the pre-existing inaccessible
  shared Windows pytest temporary directory. A bounded reproduction confirmed
  `PermissionError` before fixture setup. Only the verified task-owned failed
  run was stopped; a new full unit run uses its own repository-local temporary
  directory. No application/test assertion or machine permission was relaxed.
- The unchanged complete unit rerun passed **13,351 / 71.17s**, with the three
  existing Django URLField future-default warnings and no failures/errors/skips.
  Its report is `.tools/programme-redirect-units-2.xml`.

Focused reports are under ignored `.tools/programme-redirect-*`; they are not
exact-commit certification or CodeQL success. Because Authorization is touched,
the unchanged classifier requires exhaustive history. Before delivery, complete
exact-head local certification, independent hosted PR gate/CodeQL, protected
match-head merge, default-branch alert readback and clean-main synchronization.
Record that evidence on the delivery PR; do not silently reuse PR #201's receipt.

## Remaining boundaries

No alert dismissal, suppression, query exclusion, severity change, policy bypass,
production activation, real personal data or new schedule. The earlier individual
false-positive dispositions for alerts #20/#21 are unchanged and do not resolve
these seven instances. Human acceptance #92, joined #109 evidence, final #108
promotion and umbrella #48 remain open for their existing criteria.
