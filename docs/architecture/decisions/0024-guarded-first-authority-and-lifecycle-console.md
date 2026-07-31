# ADR 0024: Guarded first-authority ceremony and edition lifecycle console

- Status: Accepted
- Date: 2026-07-30
- Partially supersedes: ADR 0022 first-authority command-only experience
- Extends: ADR 0023 unified Management Console
- Placement amended by: ADR 0027 contextual Setup guide
- Requirements: IDN-004, IDN-005, EVT-004, AUD-001, UX-001, UX-003,
  UX-005 through UX-008, UX-011, UX-012, NFR-001 through NFR-003

## Context

The clean-database rehearsal confirmed why an empty organization needs an
exceptional trust-on-first-use transaction, but it also showed that requiring a
carefully quoted operator command after ordinary browser setup is an avoidable
failure point. The command left a workspace-less administrator with no safe
browser action to establish the first Chair. After bootstrap, the edition
lifecycle API existed but the Management Console did not expose it, so an
authorized leader still could not move Draft to Preparing without a technical
client.

ADR 0022 correctly removed the persistent **First convention setup** Django
form. That form looked routine, stayed visible after completion, and mixed a
privileged authority ceremony with editable advanced records. The safety
problem was its placement and presentation, not the reuse of the audited
bootstrap service from a browser.

## Decision

Expose a purpose-built **Establish convention leadership** ceremony in the
Management Console Setup guide, while retaining `bootstrap_convention` as an
operator and recovery fallback.

The ceremony is available only to an active Django superuser and only for an
active organization with no role bundles, role assignments, or direct
capability grants. It requires:

- a matching non-closed event edition;
- an exact, distinct, active Chair account selected by recognizable email;
- a permanent reason;
- exact re-entry of the organization slug; and
- confirmation of the signed-in controller's current password.

The browser never accepts a controller email or raw authority records. It calls
the same atomic `bootstrap_organization_workforce` service as the command. The
service creates both initial authority controllers, edition Chair authority,
membership and participation context, the leadership department and Chair
position, and the starter role/position-template catalog. A second execution
fails closed. Candidate-account reads, denied attempts, and the successful
mutation are audited with the request correlation identifier. The password is
checked for the action and is never persisted.

The ceremony appears as:

- the primary Setup guide action for an eligible workspace-less superuser;
- a guarded contextual setup panel for an eligible organizer; and
- a read-only **Convention leadership established** explanation after the
  one-shot boundary has closed.

It is not restored as an ordinary Django admin model form or persistent header
link. Subsequent authority changes use scoped access management and
independently approved workforce appointments.

After successful bootstrap, Maru refreshes the controller's newly created
edition context and opens the Setup guide. The Setup guide owns an
edition-lifecycle panel that:

- displays the current human-readable state;
- derives the valid next states from the accepted lifecycle graph;
- explains the consequence of the selected transition;
- requires a reason for every transition;
- requires an additional explicit acknowledgement for terminal cancellation
  and archival; and
- calls the existing capability-checked, locked, audited transition API.

The API remains authoritative. The client exposes no transition when the
context projection says the actor lacks `events.transition`, and server
authorization, readiness gates, state validation, audit, and database triggers
remain the security boundary. Registration activation and ticket-sale windows
remain separate from edition lifecycle.

## Consequences

An organizer can complete the ordinary first-convention journey after initial
environment and superuser creation without PowerShell. The exceptional action
remains conspicuous, one-time, password-confirmed, exact-scope-confirmed, and
audited rather than becoming an editable authority shortcut.

Moving Draft to Preparing becomes an understandable browser action immediately
after leadership exists. The same panel supports later Ready, Live, Closing,
Archived, rollback-to-preparation, and cancellation edges without exposing
direct lifecycle editing. Terminal actions carry stronger confirmation, and
archive still fails unless all closeout gates pass.

The candidate projection is a privileged account directory read and is
therefore superuser-only, bounded, and audited. Deployments still need a
production identity/step-up decision; local password confirmation is not a
claim that the local identity path is production-approved.

## Alternatives considered

- Keep the command as the only path: rejected because clean-environment testing
  repeatedly demonstrated quoting, environment, and discoverability failures
  after otherwise browser-based setup.
- Restore the former Django admin page unchanged: rejected because it would
  again present initial authority as a routine editable record.
- Automatically bootstrap when a Chair or edition is created: rejected because
  it would hide a privileged cross-module transaction and eliminate exact
  confirmation and explicit audit intent.
- Let Django superuser status directly edit lifecycle: rejected because
  platform administration is not convention authority and would bypass the
  lifecycle service.
- Show only a Draft-to-Preparing button: rejected because later valid lifecycle
  decisions would remain undiscoverable and require another technical client.
