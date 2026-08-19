# Registration profile audiences and platform starter catalog

Date: 2026-08-09

The registration module now models post-submission profile readers as a closed
policy vocabulary instead of one attendee-visible boolean. The supported
audiences are the registration owner, exact registration staff, one exact
active Department/team, all confirmed attendees, and public. Writer policy is
separate. Platform-administrator status alone grants no value access; staff and
Department reads resolve the current scoped capability. Confirmed/public
directory values require current edition consent and confirmation, are
minimized and audited, and disappear immediately when consent is withdrawn.

Migration `registration.0039` backfills legacy visible fields to `self` and
legacy hidden fields to `registration_staff`, adds the exact Department scope,
enforces audience/writer shape in both Django and PostgreSQL, and fences unsafe
reverse migration after richer audiences are populated.

Maru also ships the immutable `convention-registration` platform starter v1.
Page 10 HTML and the canonical strict setup-start API list its deterministic
identifier, version, and digest. An authorized organizer explicitly copies it
into independent edition-owned draft rows. The copy retains provenance,
requires review before activation, supports scope-bound replay, and never
live-updates from catalog or other-tenant edits.

Verification at this checkpoint:

- focused Ruff and Python import/URL resolution passed;
- five focused profile/starter integration cases passed;
- the strict profile definition API compatibility case passed;
- the canonical setup-start API starter listing/copy/replay case passed;
- the governed active-configuration profile HTML case passed after replacing
  its raw status fixture with product, review, and activation commands; and
- the `0039` legacy-visibility backfill and compatible reverse case passed
  after correcting its reverse-operation fence ordering;
- a populated `0038` rehearsal with an approved active profile field upgraded
  through `0039`, mapped its audience, rejected a raw post-upgrade mutation,
  and completed the reverse/reapply cycle, proving the exact immutability guard
  was re-enabled; and
- migration drift then reported no registration changes.

The remaining release gate is the repository-wide coordinated test/static
matrix and independent review of the shared dirty worktree.
