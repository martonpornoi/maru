# Programme continuity: dormant signature and known-state foundation

Date: 2026-09-13. Local supporting work inside #107 on
`codex/programme-onsite-continuity`, following protected #104 / PR #110.
This is not a new delivery item, complete #107, protected acceptance or activation.

ADR 0103 fixes a read-only continuity contract around existing public, personal
and operator projections. It separates live authority, signed byte integrity,
independently provisioned trust, limited source age, private-file custody and
known-state suppression. The initial lifetime ceiling is four hours, with a
one-hour issuance default to be implemented; neither is a partner safety SLA.
The profile and all source owners remain independently required.

The local pure protocol uses the installed cryptography library's Ed25519
implementation and a dedicated domain separator. Exact tenant/edition/audience,
person/purpose/field ceiling, observation/issue/expiry, release state/pointer,
time zone and payload hash are signed. Bounded canonical parsers reject extra
or duplicate fields, malformed identities/state, unknown keys, noncanonical or
oversized input, invalid signatures, future issue time and expiry. The package
includes no verification key; trust is provided separately. Authenticated bytes
still require their owning payload decoder before rendering.

The known-state layer retains signed metadata only. Explicit initialization is
required; ordinary missing/corrupt history never silently resets. An older source
or release pointer is refused, including after an old suppression record expires.
A personal source becoming unobserved cannot erase the highest release pointer
previously observed. Known state applies across optional field selections for
the same person and purpose. Equal-observation contradictory facts fail closed.
Local file custody remains a trust prerequisite: these helpers cannot detect an
attacker restoring the entire filesystem or an unseen online revocation.

Verification: **70 database-free tests passed in 0.40s**, including real signature
round trips and negative/rollback cases. Strict mypy and focused PyDocLint pass
for both new sources; Ruff formatting/lint passes. Semantic docstring validation
passed before the final documentation-only correction to propagated exceptions.
The initial module-style PyDocLint invocation was unsupported; the executable
then identified a propagated exception listed as directly raised. Moving that
contract to Notes resolved it without changing exception behavior.

No PostgreSQL suite, database, container, signing-key provisioning, server,
provider or browser session ran for this increment. Ephemeral synthetic signing
keys exist only inside test processes. No production key or data was read.

Next: implement the closed audience payload and pure now/next projection, fresh
owner-authorized issuance/admission, key configuration, same-shell HTML/print and
bounded offline verification/rendering with deliberate known-state custody.
Define the page/operations/privacy contracts, add appropriate maintained native
tests without executing them, and collect bounded synthetic browser evidence.
Only the complete exact #107 candidate goes through certification and protected
delivery. #108/#109, #102 database restoration, #97 recovery and #92 human
acceptance remain mandatory before Programme activation or a pilot.
