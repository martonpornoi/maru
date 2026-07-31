# ADR 0028: Human login handles and minimized workforce structure

- Status: Accepted
- Date: 2026-07-31
- Requirements: IDN-001, IDN-006, IDN-007, IDN-010, HR-007, HR-010,
  PRI-001, NFR-001 through NFR-003, NFR-006

## Context

Convention communities commonly know people by handles containing Unicode,
spaces, punctuation, or underscores rather than by private email. A local
educational rehearsal using recognizable roles is unnecessarily hard to
explore when every account can sign in only through a generated `.invalid`
email.

The workforce model already supports nested departments, reporting positions,
several position holders, and a person holding several assignments. Those
relationships were visible only as separate specialist records, so an
ordinary authorized participant could not understand the convention
structure without privileged record access.

## Decision

Add one optional human login handle to a platform account.

- It is case-insensitively unique and normalized only by trimming outer
  whitespace; display spelling and Unicode are preserved.
- It may contain community punctuation and spaces, but not control characters
  or `@`, which keeps email and handle identifiers unambiguous.
- Local authentication accepts normalized email or case-insensitive handle and
  returns one non-enumerating failure.
- Email remains the verified contact, recovery address, and Django
  `USERNAME_FIELD`; a handle is not contact evidence.
- Admin account pages show and search the handle.

Expose an edition-scoped workforce-structure projection guarded by
`workforce.view_structure`.

- It returns nested department names/descriptions, position titles and
  reporting links, and active holders by permitted display handle/name.
- It supports multiple holders and multiple positions per person.
- It omits email, private HR/application/document evidence, account state,
  technical identifiers from the rendered page, and all other tenant data.
- Query scope and policy checks happen before serialization; navigation is not
  authority.

Local/test rehearsal tooling may import explicitly selected public handles,
department descriptions, and role labels into a replaceable local database.
Live public data is not checked into automated tests or default fixtures;
tests use synthetic handles. The adapter never imports avatars, email,
contact, or profile data and requires an explicit operator acknowledgement.

## Consequences

Operators can switch among local rehearsal users by the names they recognize,
while production recovery and identity assurance remain tied to verified
email. The separate hierarchy page becomes an educational map and a useful
ordinary participant view without becoming an HR directory.

Organizations must choose and govern handles, collision resolution, and
retirement. Account merge and rename history remain future identity work.
Public-source imports are local rehearsal aids, not synchronization or a new
source of truth.

## Alternatives considered

- Put generated emails in documentation and keep email-only login: rejected
  because it makes a many-role rehearsal needlessly opaque.
- Treat display name as a login identifier: rejected because display names are
  not unique and may change without credential consequences.
- Expose specialist workforce records to all participants: rejected because
  they include editing surfaces and relationships beyond the minimized
  directory purpose.
- Check in a copy of the live public roster: rejected because repository tests
  and examples must stay synthetic and reproducible without retaining live
  personal identifiers.

