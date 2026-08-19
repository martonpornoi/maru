# Page 10 profile-extension definition lifecycle core

Date: 2026-08-03

This checkpoint records the focused profile-extension definition lifecycle
application core for REG-022, REG-024, and UX-026. It does not claim that its
HTML/API lifecycle adapters are mounted, compatibility writers are retired,
the stopped-writer migration is installed, or Maru is production ready.

## Outcome

- `maru.registration.setup_definition_commands` now exposes separate approval,
  activation, successor-start, and retirement commands for edition-owned
  profile-extension definitions.
- Approval accepts only a draft, records the persisted actor and database-
  server time, advances the exact setup aggregate once, and creates immutable
  review evidence bound to the field's current schema and content digest.
- Activation requires the exact current review receipt and its matching target,
  audit, domain event, and required internal outbox. Review is bound to the
  field's own last-changed setup version rather than an unrelated later
  aggregate mutation. The current activator is freshly authorized; later
  reviewer deactivation does not invalidate historical approval evidence.
- A successor starts only from the exact active field. It uses the same stable
  key, next version, and explicit `supersedes` relation; it copies an independent
  editable draft and resets approval. Template/prior-edition source pointers
  are not copied into successor lineage, so later source retirement cannot
  strand the correction.
- Successor activation atomically retires its sole exact predecessor and makes
  the reviewed successor active. A first version refuses an existing active
  same-key field, a second open successor conflicts, and concurrent activation
  commits one transition.
- Direct retirement preserves all value revisions. An active field with an
  open successor draft is protected until that draft is explicitly retired,
  preventing an unusable successor from being stranded.
- Active definitions are immutable except for the command-governed retirement
  stamp. Definition lifecycle commands do not query, rewrite, or delete
  `RegistrationProfileExtensionValueRevision` rows.
- Authorization runs before protected input parsing and again beneath exact
  organization, series, edition, actor, setup, and definition locks. Every
  successful mutation uses a positive expected version and UUID retry key and
  atomically commits state, receipt/targets, minimized audit, registered domain
  event, and outbox evidence.
- Replay validates the complete exact evidence graph, not receipt existence
  alone. Missing or malformed retry evidence, request digest, audit fields,
  event fields, required outbox, target digest/schema, or historical state is
  rejected instead of replayed as success.

## Schema and recovery

Registration migration `0034_profile_extension_definition_lifecycle` adds the
distinct successor receipt action and replaces the profile-definition guard.
The guard enforces exact successor version/source state, coherent approval
evidence, approved active state, active immutability, protected deletion, and
strict setup-version advancement for retirement. Its reverse restores the
prior `0029` trigger and action choices exactly.

All canonical transitions and their evidence share one PostgreSQL transaction.
Receipt, target, audit, event, or outbox failure therefore restores the field,
setup aggregate, and predecessor state. Recovery is an exact retry with the
original key and payload after the dependency is healthy; operators must not
manufacture lifecycle or evidence rows manually.

The additive guard cannot yet prove that every deployed database login is
unable to issue a raw legacy retirement while a successor is open. Repository-
writer reconciliation, runtime-role review, and the stopped-writer cutover must
close that path before deployment.

## Verification

- Fresh PostgreSQL focused lifecycle and forward/reverse migration matrix:
  **24 passed in 52.83 seconds**.
- Fresh PostgreSQL adjacent registration definition, profile-value, model-
  policy, and setup-schema regression matrix: **23 passed in 71.46 seconds**.
- Coverage includes authorization-before-parsing, exact tenant/scope locks,
  approval/activation replay, unrelated edits, reviewer deactivation,
  successor copy/edit/reapproval/activation, retired optional sources,
  value-history preservation, dependency-protected retirement, malformed and
  forged evidence graphs, rollback at audit/outbox failure, active
  immutability, database guard behavior, duplicate lineage, historical replay,
  and concurrent activation.
- Ruff check and format pass for the model, command service, migration, and
  focused tests. Strict mypy passes for the changed model and command service.
- Django system check passes with only the expected fail-closed invitation-key
  warning, and migration drift reports no changes.

## Open boundary

- Mount strict closed-input HTML and canonical v1 API adapters for these
  lifecycle commands, with RFC 9457 mappings and OpenAPI evidence.
- Reconcile every repository-owned compatibility/admin/fixture writer before
  installing and rehearsing stopped-writer database guards.
- Add configuration retirement/successor choreography and then run the complete
  Page 10 browser, 390-pixel, keyboard/screen-reader, deployment, recovery/PITR,
  and owner-tutorial gates.
