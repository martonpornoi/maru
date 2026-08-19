# Page 10 profile-extension staff capability catalog

Date: 2026-08-03

## Outcome

The working tree now declares the two exact-edition, persistable capabilities
required by ADR 0047 and REG-022:

- `registration.view_profile_extensions` permits a purpose-limited C2 value
  projection and requires a sensitive-read audit before release; and
- `registration.update_profile_extensions` permits a reasoned, audited staff
  append only where the active field's writer policy also permits staff.

Neither capability is added to an existing role bundle, bootstrap template, or
grant. In particular, `registration.register_on_behalf`, registration setup
management, Django staff state, and platform administration do not imply either
new capability.

## Database contract

Authorization migration
`0011_registration_profile_extension_capabilities` updates the code-owned
PostgreSQL minimum-scope catalog so both capabilities can be persisted only at
edition scope or narrower. The migration retains fail-closed handling for
unknown and relationship-only capability codes, preserves the hardened
function search path and public-execute revocation, and updates the reviewed
authority-readiness fingerprint.

An empty database can reverse the migration and returns both codes to unknown.
Reversal refuses once either capability appears in any capability grant or role
bundle, because old application/database generations could not safely interpret
that authority. Recovery must then fix forward or restore the complete
authorization state to one compatible point.

## Verification

- 12 capability-catalog unit tests passed.
- 3 fresh PostgreSQL migration/fingerprint cases passed, including exact empty
  reverse and reapplication.
- 103 adjacent authority-provenance readiness, retired-Department contract,
  and runtime-role unit cases passed on a separate fresh PostgreSQL database.
- Ruff, migration drift, and whitespace checks passed for this slice.

These checks prove the catalog boundary only. They do not grant production
authority and do not yet replace the legacy profile-value writer or staff read
adapter.

## Next boundary

Implement one canonical append-only profile-extension value command with
expected field sequence, scope-bound retry evidence, field-policy enforcement,
atomic audit/event/outbox evidence, and an audited query that uses the new read
capability. Only then may maintained API/HTML compatibility adapters be cut over
from `registration.register_on_behalf` and the broader service projection.
