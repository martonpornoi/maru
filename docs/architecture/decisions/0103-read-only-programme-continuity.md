# ADR 0103: Read-only signed Programme continuity

- Status: Accepted
- Date: 2026-09-13
- Issue: [#107](https://github.com/martonpornoi/maru/issues/107), under #48

## Context

ADRs 0097/0099 provide independently admitted live outputs and ordinary downloads,
not signed offline packs. ADR 0102 provides reviewed change communication, not
an offline command channel. A Programme department needs useful now/next views
and a bounded, verifiable fallback when the central service is unavailable.
An offline verifier cannot discover a newer publication, revoked permission,
withdrawal or compromised key while disconnected. A signature cannot overcome
that limitation or turn a snapshot into current operating authority.

## Decision

Scheduling owns the dormant `scheduling.programme-continuity@1` adapter. Existing
profiles do not pin it. Online public, exact-person and exact room/Department/
edition operator continuations call the existing complete owner projections,
retaining their separate fields, parent/person locks, final checks and mandatory
audits. No public response is enriched with private fields; no personal query is
called as somebody else. Optional operator layers remain explicitly requested.

Now/next is a pure time-based projection, not attendance. Effective intervals
drive public rows, approved own presence drives hosting, three-phase envelopes
drive operator preparation/delivery/teardown, and retained Shift intervals drive
work. Claims remain tentative and historical/removed work never becomes current
work. The full run sheet stays available; current instructions and owner versions
are not relabelled as immutable released facts. Times retain the edition IANA
zone and explicit offsets across daylight-saving transitions and overnight days.

### Signed bounded snapshot

Use the installed `cryptography` library's Ed25519 implementation, not a custom
signature algorithm or Django's application/session secret. A dedicated deployment
key is provisioned outside repository data. Missing/invalid configuration disables
signed issuance, not ordinary freshly authorized now/next reads. No private key,
credential or directory is returned in a file or URL. No new database tables,
background worker, grant or profile activation is required by this contract.

A closed versioned manifest signs the exact payload digest, issuing key ID,
organization/edition, audience, purpose target, genuine-person binding where
applicable, requested layer ceiling, source observation, release/pointer state,
issue/expiry instants and time zone. Sign domain-separated canonical UTF-8 JSON.
Identical validated inputs and key produce identical bytes. A newly observed
source or changed current instruction creates a different snapshot even if its
release pointer is unchanged. No compression or executable supplied content is
accepted. Parsers reject duplicate/unknown fields, malformed/cross-scope values,
non-finite numbers, oversized/deep input and invalid signatures before rendering.

The initial engineering policy permits at most four hours between source
observation and expiry; the default issuance lifetime is one hour. This is a
synthetic implementation ceiling, not an event-specific safety approval or SLA.
An event owner must approve a shorter suitable window and independent fallback
before a pilot. No expiry extends underlying authority. A disconnected display
always says historical/degraded, shows source age and expiry, and cannot claim
to know a newer release, current qualification, attendance or delivery status.

Public packs contain only existing public fields. Personal and operator packs
retain their own field ceilings and are private exports, not bearer permission
tokens or encrypted containers. Store them only on access-controlled encrypted
event devices; restrict and account for printed copies. Do not automatically
persist them in browser storage, service-worker caches or shared downloads.
Dispose of downloaded/printed copies at expiry, replacement or stop-use under
the operator's documented procedure. Neither signatures nor expiry can remotely
erase an already copied file or sheet of paper.

### Trust, known state and offline verification

The offline verifier is installed and rehearsed before the outage. Trusted public
keys and expected organization/edition/audience/target come from a separately
authenticated provisioning procedure, never from the snapshot's own assertions.
The key ID selects only an already trusted key; bundled keys, key URLs and fallback
to an unknown/retired key are forbidden. Key rotation and known revocation require
reprovisioning trusted verification policy and disposing of affected packs.

Verification checks trusted scope, signature, payload hash and bounded clock
validity before disclosing content. A protected local record of the newest known
signed manifest prevents accepting an older pack as a replacement. A newer
withdrawn/invalidated manifest suppresses ordinary old content and yields a
versioned withdrawn/relocation-pending view. Contradictory equal-version evidence,
untrusted state or clock rollback fails closed. A record containing only signed
manifest metadata need not duplicate the private payload. Missing/lost known-state
history is not evidence that no newer state exists; initialize it deliberately
while connected and preserve it during the outage.

Expiry, invalid signature, known newer state or a failed verification produces
no normal timetable. Online denial or unavailable sources never silently serve a
last-good cache. Personal retained work is not cancelled by a timetable warning;
the warning must explain that revalidation is required, without turning stale
room geometry into a current instruction. After reconnection, obtain a complete
fresh owner projection and replacement pack before resuming ordinary display.

The bounded offline tool may render verified read-only HTML/print locally without
a database or network. Its output remains visibly historical and identifies the
verification/source time; it does not mint acknowledgement, reschedule work or
provide a general relay. Printed output states the same limitations and expiry.
Routine department users use the shared-shell online and print journeys; key
provisioning and offline trust recovery are accountable operator tasks.

## Consequences

- Full owner-authorized projections remain the only source for issuance.
- Signed integrity, current authorization, freshness, handoff and acknowledgement
  are distinct. #104 remains the sole governed change-notice workflow.
- #107 exports the bounded on-site timetable package, not the complete profile
  archive of proposals, reviews, configuration and audit required for stop-use.
  #109 coordinates that broader existing #48 exit/recovery outcome.
- No attendance, actual time, Shift handover, general Communications, incident
  command or excluded module is added. ADR 0004's separate relay remains unbuilt
  by this read-only increment; none of its offline-write authority is adopted.
- Native execution stays deferred under ADR 0100; maintain #102 scenarios.
  #97 recovery, #92 human acceptance and #109 integrated proof remain mandatory.
- This decision is a contract, not a claim that the new components are complete.
  CURRENT and checkpoints record implementation and actual verification.

## Alternatives considered

- Trust a public key supplied inside the same file: rejected; self-signature is
  not independent trust and permits a forged package to certify itself.
- Cache last-good HTML automatically: rejected; it hides known invalidation and
  silently persists private content without a bounded custody/expiry policy.
- Add a full offline app or relay with writes: rejected as outside #48 version one.
- Use an ordinary download hash as authenticity: rejected; an attacker can
  replace both the data and its unsigned hash.
- Claim expiry securely deletes exports or that local time proves freshness:
  rejected; copied paper/data and compromised clocks require explicit limits.

## Requirements affected

OPS-009, SCH-002/006/008/009/010/012, INT-007, QRY-005, PRI-001/008,
AUD-001 and NFR-001/005/008/009/013. ADRs 0004, 0081, 0096, 0097, 0099,
0100 and 0102 remain accepted. Cryptographic API reference:
[Ed25519 signing and verification](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/).
