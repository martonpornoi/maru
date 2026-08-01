# Retired Marucon public-roster rehearsal

Status: Retired; fail-closed compatibility command only
Last updated: 2026-08-01

The former `seed_marucon_rehearsal` journey imported public volunteer handles
and established convention authority through the broad legacy bootstrap. That
behavior conflicts with Maru's synthetic-data boundary and the rule that a
platform administrator never participates in a convention.

Do not run the former command. It remains registered only so old automation,
including calls with `--accept-public-roster`, `--roster-url`, `--roster-file`,
or `--password`, stops with a stable `CommandError` before validation, file or
network access, and database writes. The former network adapter is also
permanently fail-closed.

## Supported synthetic rehearsal

Create or refresh the deterministic local fixture:

```powershell
uv run python src/manage.py migrate
uv run python src/manage.py seed_demo_data
```

Then sign in with one of the synthetic accounts reported by the command and
open `/admin/`. The fixture uses `.invalid` identities and exercises the real
Executive Board lifecycle:

1. the platform administrator provisions the representation root;
2. two distinct verified synthetic people receive exact invitations;
3. each invitee accepts their own invitation; and
4. Page 8, **Representation & access**, activates the Board with independent
   cross-approval while the platform account remains external.

Use the current
[Maru hands-on tutorial](maru-hands-on-tutorial.md) for the organization,
representation, series, and edition journey. Department-template and hierarchy
editor work must use synthetic taxonomy and accounts; live public handles are
not fixture input.

Historical checkpoints remain evidence of the retired experiment and are not
instructions to re-enable it.
