# Fictional MaruCon rehearsal

Status: Supported synthetic replacement; external-roster path removed
Last updated: 2026-08-22

Maru's supported rehearsal uses only repository-owned fictional conventions,
synthetic people, and reserved `.invalid` contacts. The former public-roster
parser, network URL, and compatibility command have been removed.

## Prepare a disposable local fixture

```powershell
uv run python src/manage.py migrate
uv run python src/manage.py seed_demo_data
```

The v6 dataset creates MaruCon and MaruDance as independent fictional tenants
with archived, preparing, and draft editions. It exercises the real Executive
Board lifecycle:

1. the platform administrator provisions the representation root;
2. two distinct verified synthetic people receive exact invitations;
3. each invitee accepts their own invitation; and
4. **Representation & access** activates the Board with independent
   cross-approval while the platform account remains external.

Use the [Maru hands-on tutorial](maru-hands-on-tutorial.md) for the complete
organization, representation, series, edition, and Department-starter journey.

## Upgrade boundary

Fixture versions before v6 used different example identities and slugs. Do not
relabel or merge those records. Use a new disposable local/test database and
seed v6. The command refuses collisions rather than deleting or silently
rewriting existing records.

No tutorial or fixture may contact a convention website, parse a people
directory, reuse a public organization chart, or imply affiliation. A real
organizer migration requires a separately accepted data-governance contract.
