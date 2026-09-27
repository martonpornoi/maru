# ADR 0115: Local-only assisted Programme rehearsal

Status: Accepted
Date: 2026-09-25

## Context

The maintainer explicitly approved synthetic local HTTP for #203 after the
self-signed rehearsal certificate prevented browser access. They have no external
HTTPS environment or additional participants. Installing trust roots, bypassing
browser certificate warnings or exposing a public tunnel is not authorized.

Identity invitations and the native fixture correctly require HTTPS. Changing
their production settings or making readiness claim a false TLS result would
expand this request. The isolated backend must retain its real owning commands,
restricted PostgreSQL role, actual authentication, CSRF and independent-account
approval checks.

## Decision

Add a test-only browser bridge in `tests/rehearsals`, never production routing.
It requires both the existing isolated native opt-in and
`MARU_PROGRAMME_LOCAL_HTTP=synthetic-loopback-only`. Bind only literal `127.0.0.1`
on an allocated nonprivileged port. Validate the live fixture's run identity,
original lease, owned certificate path and exact certificate fingerprint first.

The browser uses HTTP; the bridge always uses verified TLS 1.2 or later to the
single owned backend. It never accepts a caller-selected upstream, proxy setting
or redirected destination. The backend's public origin, Secure cookies, native
readiness and HTTPS behavior remain unchanged. Neither transport is a public site.

Reject unexpected Host/port, Origin, cross-site fetches, duplicate authority or
framing headers, nonlocal targets, unsupported methods and oversized bodies.
POST requires the exact browser origin; translate that checked origin and local
Referer to the fixed HTTPS origin while retaining Maru's real CSRF verification.
Only allowlisted headers and this run's namespaced session, CSRF and signed
Django feedback-message cookies cross the boundary. Feedback cookies carry normal
one-time success/error notices; preserve their signed values and consumption/deletion
semantics rather than rejecting a completed mutation's redirect. Unknown cookie
names and nonlocal cookie scope remain refused.
No server-side cookie jar or implicit current user is shared between
requests. Browser cookies lose Secure solely on the approved HTTP side; preserve
HttpOnly, SameSite, expiry/deletion and path, and never adopt another local app's
cookies. No cookies or request bodies are logged.

For synthetic browser diagnosis only, retain bounded in-memory totals by the four
handled HTTP methods and numeric response status. A private supervisor
`diagnostics` command returns a copy; no HTTP diagnostic endpoint is added. Do not
retain paths, actors, headers, bodies, timestamps or per-request records. The
purpose is to distinguish a browser action that never reaches the bridge from a
received request; a chosen status does not prove browser delivery or domain
success. Counts expire with this owned fixture and are never production activity
collection, acceptance evidence by themselves or a reason to renew the lease.

Return only local redirects. Map the exact backend origin in HTML continuations
to the browser origin; do not alter JSON, calendar, archive or signed download
bytes. Such artifacts may retain their canonical HTTPS source and are not proof
of externally reachable hosting. Bound requests at 4 MiB and responses at 8 MiB;
oversized or unavailable responses fail closed. Retain the fifteen-second
upstream deadline, original fixture expiry and owned cleanup. No listener renewal,
background schedule, trust-store mutation or production fallback is added.

The 2026-09-27 applicant rehearsal adds one explicit transport exception to those
general budgets: the exact UUID-shaped personal supporting-file intake route may
use raw `application/pdf` PUT up to the owning contract's 10 MiB. No other PUT route
is admitted. Preserve its bounded original `X-Maru-File-Intent` header on that
route's PUT and body-free result GET; reject duplicates, encoded bodies, foreign
or absent unsafe-request origins and malformed intent headers before forwarding.
The native backend still verifies the actual signature, CSRF, actor, versions,
quota and real scanner evidence. Exact PDF responses may likewise reach 10 MiB
without byte rewriting; all other request/response budgets remain 4/8 MiB.
This fixes the local test transport, not production policy or file acceptance.

The interactive launcher uses labelled prepared stages (`team`, `items`,
`published`). Earlier automated steps remain automated evidence, not human passes.
Account handoff is encrypted to the facilitator's ephemeral public key. Sign in
and out through ordinary forms; verify the active account at each switch. Tabs
alone do not isolate sessions. One person may exercise distinct synthetic roles
with assistance, but that is not independent-person acceptance.

## Consequences and acceptance boundaries

This explicitly replaces the HTTPS-only *browser access prerequisite* for this
local synthetic rehearsal. The default native HTTPS fixture, production policies,
separate-account approval, native tests and protected delivery remain unchanged.
Preserve prior certificate failures and valid #87 browser observations.

Record maintainer-operated tasks, assistant-operated tasks, coaching and failures
separately. This decision alone does not mark any #92/#109/#108/#48 criterion
passed or silently waive an activation gate. Any reassignment of representative
independent-user, specialist accessibility and operational-owner evaluation to a
later pilot must be explicit in the owning acceptance scope and tracked work.
Local HTTP is not browser-TLS, public deployment, production or pilot acceptance.

The loopback connection is unencrypted. Use only fresh synthetic credentials and
data; other software or users on the same machine remain a residual risk. Do not
use this mode on a shared/untrusted host, with real personal data, or across a LAN.
No development certificate or system trust cleanup is required. Remove only owned
fixture resources; preserve other apps, browser settings and worktrees.

## Alternatives considered

- Install a development CA or bypass the certificate warning: not chosen; the
  approved local exception requires no machine trust or browser security changes.
- Relax Identity/runtime HTTPS readiness: rejected; the browser bridge preserves
  genuine backend transport and existing owner security contracts.
- Use mocked component pages or automatic impersonation: rejected; neither tests
  the actual native authority and login boundary.
- Provision public HTTPS now: deferred; it needs an approved environment and
  operational ownership before cross-computer or convention pilot evaluation.

## Requirements affected

NFR-001/002/003/005/013, UX-007/029 and SCH-011/012: isolated test delivery,
honest evidence, unchanged domain authority and narrowly documented development
transport. No production requirement or previous accepted domain ADR is reversed.
