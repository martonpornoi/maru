# Programme now, run sheets and offline continuity

**Audience:** Synthetic Programme evaluators and accountable continuity operators\
**Outcome:** Read current work and prepare, verify, replace or stop using a bounded fallback\
**Reading time:** 8 minutes

## Availability and responsibility

This is dormant #107 development under [ADR 0103](../architecture/decisions/0103-read-only-programme-continuity.md),
not an activated Programme profile or permission to use real personal data.
An isolated fixture must admit `scheduling.programme-continuity@1` and the
independently required source adapters. No current profile pins it, and normal
production routing does not mount these pages. #108 connects normal departmental
task selection; #102/#97/#92/#109 remain database, recovery, human and integrated
acceptance gates. Do not enable a profile or provision a production signing key
merely to follow this guide.

Department users read the shared public, My Maru or Administration pages.
An accountable operator owns key provisioning, exact offline scope, device and
clock custody, fallback instructions and disposal. A signature authenticates
snapshot bytes: it does not prove current permission, current instructions,
attendance, delivery, acknowledgement or absence of a newer withdrawal.

## Read current and next work

1. Open the rehearsal's exact public, personal or operator **now and next** link.
   Personal means the signed-in person only. Operator means one authorized room,
   Department or edition, not a broader planner or a list of people.
2. Read the release state, edition time zone, source-check instant and replacement
   deadline. Now/next is frozen at that source check, not a ticking live monitor.
   Choose **Refresh now and next** for a new complete authorized read.
3. Follow a **Now** or **Next** title to its complete card. Public intervals are
   approved event times; hosting intervals are required own presence; operator
   cards expose preparation, delivery and teardown separately. Confirmed work
   retains its accepted interval. Tentative claims are labelled; removed or
   completed history is not current work. The earliest next start includes ties.
4. Read current room labels and instructions with their own source versions.
   They are not silently treated as immutable approval facts. An operator can
   explicitly select technical, accessibility, media or linked staffing layers
   and choose **Load selected complete view**. Every owner must authorize; a
   denied or unavailable selected layer prevents the complete response.
5. Use **Print-friendly complete copy**, then the browser's Print command. Keep
   all scope, source, time-zone, expiry and historical-copy warnings. The page
   does not automatically print, and browser-native pagination requires rehearsal.
6. Continue through **Reviewed Programme change notices** for the existing #104
   workflow. Reading, printing or downloading does not hand off a notice or
   acknowledge it. No attendance, rescheduling or offline write channel is added.

Authorized empty scope does not mean an empty edition. Unrequested, unadopted,
unpublished, withdrawn and invalidated states have different meanings. Known
withdrawal/invalidation hides ordinary Programme geometry and instructs the
reader to obtain replacement instructions. Retained volunteer work is not
silently cancelled or moved. Denied or incomplete sources produce no old or
partial timetable; do not substitute a previously saved copy for a failed check.

## Signed export configuration (accountable operator)

Live and print reads do not require signing secrets. **Download signed snapshot**
performs a fresh owner read and loads dedicated process configuration. Missing,
ambiguous, malformed or out-of-window keys produce a safe unavailable response,
not an unsigned substitute. The HTTP download is an unencrypted JSON container,
not an offline web application, bearer credential or trusted-key distribution.

The managed request process reads `MARU_PROGRAMME_CONTINUITY_SIGNING_KEYS_JSON`.
Never use Django's `SECRET_KEY`, a session secret, a checked-in key or a key from
the request. Provision a dedicated Ed25519 key through the operator's approved
secret-management procedure; never paste raw configuration into logs, tickets,
screenshots, shell history or exception-local capture.

The closed signing-policy document has exactly:

- `contract`: `scheduling.programme-continuity-signing-policy@1`;
- `lifetime_seconds`: an integer from 1 through 14400; default policy is 3600;
- `keys`: 1 through 8 records, each containing exactly `organization_id`,
  `edition_id`, `key_id`, `private_key_b64`, `not_before`, `not_after`.

UUIDs use canonical lowercase form. The private key field is standard Base64 of
the 32 raw Ed25519 private bytes, not PEM. Times use canonical UTC ISO 8601 with
`+00:00`. Serialize the entire document as UTF-8 JSON with sorted keys, compact
separators, no ASCII escaping and no trailing newline; for a prepared in-memory
document this is `json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
Limits are 32768 bytes and eight keys across all scopes in that process.
The issuer derives the public key, requires one active key for the exact tenant
and edition, and verifies its own output against the configured trust ceiling.
The key window must cover the complete manifest lifetime. Issue time must be
within five minutes of source observation; expiry is measured from observation,
not download completion. Live/print copies use a one-hour source-based deadline;
signed packs use their configured manifest deadline, at most four hours.

These are engineering ceilings, not an approved event safety policy. Before a
pilot, the event owner must choose an appropriate shorter expiry and independent
fallback. Rotation must leave exactly one active issuing key per scope, with
independently distributed verification trust covering needed signed history.
An expired key may still authenticate retained historical metadata; it cannot
extend a pack's validity. A known compromised key requires stop-use and controlled
trust/history recovery, not pretending old signatures are still sufficient.

## Prepare trust and protected history before an outage

Install and pin the exact Maru package and its locked dependencies on the
controlled offline device. The verifier imports no Django runtime, opens no
database and makes no network requests. Rehearse the installed tool, local time
zone data, filesystem hard-link support and clock before depending on it.

Distribute a separate protected trust file through an authenticated channel.
It contains canonical JSON with exactly `contract` equal to
`scheduling.programme-continuity-trust@1` and `keys`. Each of the 1 through 8 key
records contains `organization_id`, `edition_id`, `key_id`, `public_key_b64`,
`not_before`, `not_after`; encoding and 32768-byte bounds match the signing policy.
The public field contains 32 raw public bytes in standard Base64. No private key
belongs on the verifier. Verify the key identity and scope independently of the
download. A key or URL bundled with an untrusted package is not a trust source.

Independently record the expected organization, edition, audience, real actor
when private, purpose and target. Do not copy these assertions blindly from the
package under examination. Maintain one protected known-state path per exact
audience/person/purpose; changing optional operator layers must not lose the
latest-known withdrawal or release high-water mark.

While connected, obtain a freshly authorized pack and deliberately initialize
new protected history. A synthetic public example, using independently provisioned
fixture IDs and existing controlled directories, is:

```console
python -m maru.scheduling.continuity_offline --package incoming.maru.json --trust trusted-keys.json --known-state public-known.json --output initial-copy.html --organization 00000000-0000-0000-0000-000000000001 --edition 00000000-0000-0000-0000-000000000002 --audience public --kind public --initialize
```

For own material use `--audience exact_person --kind personal --actor UUID`.
For operator material use `--audience private_operator --actor UUID`, the exact
`--kind room`, `department` or `edition`, and `--target UUID`; an edition target
equals the edition ID. Add only the independently approved `--layers technical
accessibility media staffing` subset. Public and personal scopes accept no
operator layers or arbitrary other-person target.

## Verify a replacement or render during a bounded outage

Repeat the command **without `--initialize`**, preserving the same protected
history and using a new output filename. There is no clock-override flag. A
successful exit status 0 publishes one complete historical HTML file after
signature, exact scope, hash, expiry and known-state checks. Open that locally
and use native Print if needed. Now/next is frozen at verification time; rerun
the verifier with a new filename to recompute it while the pack is still valid.
Opening an old HTML file does not reverify it or update its time, and the HTML
does not contain a network script or mutation relay.

The verifier retains signed latest/high-water metadata and the last local
verification instant before decoding the payload or rendering. A malformed
newer signed payload therefore cannot authorize an older fallback. A newer known
withdrawal/invalidation prevents re-rendering older ordinary material. The
history is metadata, not a duplicate of private instructions or activity telemetry.
Local clock rollback is refused; rollback of the entire device storage and clock
cannot be reliably detected without independent custody.

Exit status 2 or argument errors mean stop, preserve history, and obtain fresh
authorized instructions or accountable recovery. Never reuse an older copy to
bypass the refusal. Package, trust, history, lock and output paths must be
distinct; output must not exist. A purpose-specific exclusive `.lock` prevents
cooperating verifier races. Writes publish complete files without overwriting an
existing output. Unsupported storage or full-disk errors fail; cleanup can fail
after a complete file was published, so **a failed command does not authorize
using any resulting file**.

## Recovery, custody and stop-use

- Missing/corrupt history or a remaining lock is not permission to initialize
  again. Confirm no verifier is running, preserve the exact evidence, and have
  the accountable operator recover trusted state. If history cannot be recovered,
  stop offline use until connected reauthorization, independent clock/trust
  verification and deliberate new provisioning are complete.
- Do not remove a historical key just to make an error disappear. Rotation,
  revocation, storage loss and suspected tampering require reviewed trust and
  history recovery. No automatic key fetch or history reset is implemented.
- On reconnection obtain a complete current authorized source and replacement
  pack, advance known state, and dispose of superseded copies. A known withdrawal,
  invalidation, permission loss or compromised key can require stopping sooner
  than the printed expiry. Disconnected devices cannot discover unseen changes.
- Store private packs, HTML and history on access-controlled encrypted event
  storage, not shared browser downloads or automatic cloud synchronization.
  POSIX-style file modes alone do not establish Windows ACLs or encryption.
  Record accountable paper recipients without turning this tool into a people
  directory. Collect and securely dispose of copies at replacement, expiry or
  stop-use under the event's approved procedure. Expiry cannot erase copied files,
  browser downloads, backups, caches or paper; control each retained copy.
- Diagnose with exit/status category, exact software version, scope/key identifier
  and the existing owner audit correlation where available. Do not log payloads,
  private instructions or key configuration. This tool adds no telemetry.

There is no schema migration or new runtime privilege in #107. Reverting code
does not erase exports: stop issuance, retire the exact fixture/runtime adapter
through its owning process and account for existing copies and trust history.
This timetable pack is not the complete proposal/review/configuration/audit exit
archive. #109 coordinates that broader #48 stop-use and recovery outcome.

## Isolated preparation evidence

The [integrated rehearsal](programme-integrated-rehearsal.md#signed-continuity-preparation)
maintains dedicated ephemeral test-key issuance, independent trust, six scoped
downloads, actual offline CLI/history handling, controlled-clock refusals and
owner-command withdrawal/republication. PostgreSQL execution remains deferred;
database-free component results do not certify native issuance or operational use.
Its owned temporary synthetic files and network-denied verifier prove neither
encrypted device custody nor secure erasure of external copies. The accountable
event trust, history, clock, replacement and disposal procedures above still apply.
