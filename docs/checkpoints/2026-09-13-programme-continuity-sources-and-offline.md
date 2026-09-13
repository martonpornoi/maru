# Programme continuity: owner projections and offline verification

Date: 2026-09-13. Supporting local work within #107, following PR #110 and
the protocol checkpoint. This is not a completed #107, PR, activation or pilot.

The new dormant adapter is registered but pinned by no existing profile.
Its read wrapper calls exactly one existing audience composition, retains the
owner transaction/lock/audit boundaries, and rechecks profile admission before
returning. Public output contains reviewed effective-time cards; exact-person
output preserves required host presence separately from retained work; operator
output retains full envelopes and only explicitly requested instruction layers.
Linked staffing is represented once per demand, with current/predecessor meaning
and anonymous retained-interval counts rather than an invented personnel list.

The closed canonical on-site payload retains complete source hashes, observation,
release/pointer, zone, layer state, and independent instruction/work versions.
Now/next uses end-exclusive aware intervals and preserves concurrent next-start
ties. Removed/completed work never becomes current work. Nonavailable Programme
state cannot carry ordinary Programme geometry; retained own work is independent.

Dedicated environment signing configuration has exact tenant/edition key scope,
no Django-secret fallback, a one-hour default and a four-hour hard ceiling from
source observation. Only one active key may issue for a scope. The resulting pack
is verified against that independently configured key policy before being returned.
Keys are ephemeral synthetic test data only; no deployment key was provisioned.

The standalone `python -m maru.scheduling.continuity_offline` tool accepts a
separate trusted public-key file, independent expected scope, protected known-state
file and new HTML destination. It requires explicit pre-outage initialization,
serializes cooperating verifiers with an exclusive purpose lock, and persists
verified metadata before payload decoding or rendering. Complete output is
published without overwriting an existing destination. Broken storage, unknown
trust, expiry, scope mismatch or older known state cannot create a normal copy.
A newly verified signed header remains known even if its payload cannot render.

The protected record now also retains local last-verification time, detecting
clock rollback within a pack lifetime. Its local timestamp is not issuer-signed;
whole-filesystem/clock rollback remains outside the disconnected guarantee.
Historical HTML uses escaped cards, the edition zone, exact source information,
copy deadline and explicit degraded warnings; it has no scripts, network assets
or mutation actions. HTML and paper are dated copies, **not live verifiers**.
They cannot erase themselves or discover a new release. Accountable encrypted
device custody, paper disposal and reconnect/reprovision procedures remain required.

## Verification so far

- Full database-free suite: **5,729 passed in 45.30s**, two existing Django URLField
  deprecation warnings, before the latest presentation/file-tool additions.
- Source/codec/signing/admission focused runs passed, including real Ed25519 keys.
- Presentation and known-state follow-up: **68 passed in 0.42s**.
- Real isolated temporary-file verifier tests: **15 passed in 0.56s**.
- Strict mypy passed for all nine new continuity sources; focused PyDocLint passed.
- Documentation structure passed at 483 Markdown files before this checkpoint.
- Initial full units encountered an inaccessible old Windows pytest temp directory.
  Repeated setup failures were stopped; a fail-fast run confirmed the permission
  cause. A fresh `.tools/issue107-unit-temp-...` directory resolved it without
  deleting old files, changing permissions or changing product code for the failure.
- An oversized synthetic parametrized value was given a short explicit test ID;
  catalog expectations were updated for the one newly registered dormant adapter.

No PostgreSQL suite/schema run, production data, Docker operation, browser session,
provider, profile promotion, scheduler or subagent was used for this increment.
This is local component evidence, not an exact-commit certification receipt.

## Remaining before #107 delivery

Wire the contracted shared-shell public/My Maru/operator HTTP, print and signed
download routes. Add end-to-end transport and maintained native authorization,
audit/race scenarios without executing PostgreSQL under ADR 0100. Document actual
key/trust provisioning, offline custody/recovery and use. Rehearse the synthetic
browser journey, retaining genuine human/native-print/screen-reader work in #92.
Then certify the exact complete candidate and require the protected GitHub gate
before merge. #108/#109 and #102/#97/#92 remain separate unfinished gates.
