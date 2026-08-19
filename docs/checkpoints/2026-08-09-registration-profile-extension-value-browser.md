# Registration profile-extension browser editing

Date: 2026-08-09

## Outcome

Registration profile-extension values can now be edited through Maru's
existing attendee and registration-staff shells without introducing a second
profile store or page-local access controls.

- The attendee registration profile links to a policy-filtered self editor.
- The governed Registration admin detail links to an exact-scope staff editor
  only when the relationship read is allowed.
- Every POST authorizes the exact tenant, edition, registration, field, and
  writer policy before binding input.
- Forms use canonical UUID and integer fields, close unknown inputs, require
  expected sequence and idempotency evidence, and use PRG responses.
- Writes continue through the append-only profile-extension command and its
  audit, event, outbox, and immutable receipt graph.
- Optional boolean, integer, and single-choice fields can be cleared with JSON
  `null`; required fields fail closed. SQL `NULL` remains forbidden.
- Consent and audience projections are evaluated at read time, so clearing or
  withdrawing publication removes a directory value immediately.

## Migration and recovery

Registration migration `0040_optional_profile_value_clear` replaces the
profile-value database guard without changing the non-null column. It accepts
JSON `null` only for optional boolean, integer, and single-choice definitions.
Its reverse operation refuses to proceed after any clear revision has been
recorded, because older guards cannot represent that evidence safely.

## Verification

- Profile-extension form unit matrix: 15 passed.
- Browser, authorization, replay/stale, clear/reappend, directory removal,
  API parity, and migration guard matrix: 5 passed.
- Focused Ruff, mypy, Django route/template checks, and migration drift check
  passed. Django reported only the existing invitation-encryption warning.

An existing API compatibility sweep found that a recent adapter hardening
change returned command-result JSON instead of the documented workspace and
allowed a staff write to commit when the post-write audited read was denied.
The adapter correction restores the workspace response and performs that read
inside the atomic command boundary. The final serialized matrix passed all 14
collected cases: the exact eight prior API failures, the OpenAPI workspace
response assertion, and all five browser/migration workflows.
