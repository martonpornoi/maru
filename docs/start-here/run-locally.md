# Run Maru locally

**Audience:** New contributors and technical evaluators\
**Outcome:** Sign in to an empty local Maru instance using your own synthetic
administrator\
**Reading time:** 5 minutes\
**Hands-on time:** Usually 15–30 minutes after prerequisites are installed

This route starts a development server for synthetic exploration. It does not
activate every module or prepare a production deployment. To edit prose only,
skip the database and use the [first contribution guide](first-contribution.md).

## 1. Get the source and tools

Install Git, Python 3.12–3.14, [uv](https://docs.astral.sh/uv/), and Docker with
Compose. Start Docker before continuing. Node 22.12 or newer and the repository's
pinned pnpm are needed when changing the embedded frontend; see
[development setup](../development/setup.md).

Clone the repository, or clone your fork if you plan to submit changes:

```sh
git clone https://github.com/martonpornoi/maru.git
cd maru
uv sync --locked --all-groups
```

Run the remaining commands from this directory. They assume a new local setup.
If you already have a Maru database or Compose volume, identify it before
applying migrations. The [hands-on tutorial](../operations/maru-hands-on-tutorial.md)
explains how to create a separate tutorial database without overwriting one.

## 2. Start PostgreSQL and create the first account

In PowerShell:

```powershell
docker compose up -d --wait postgres
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru"
uv run python src/manage.py migrate
uv run python src/manage.py check
uv run python src/manage.py createsuperuser
```

On Bash or Zsh, replace the `$env:MARU_DATABASE_URL` line with:

```sh
export MARU_DATABASE_URL="postgresql://maru:maru@127.0.0.1:5432/maru"
```

Compose creates **`maru`**, the database selected above. It does not create the
separately named databases used by some historical rehearsals. Maru does not
automatically load `.env`; keep the database variable in every terminal that
runs a server or management command.

Follow `createsuperuser`'s prompts. Use a synthetic address such as
`developer@example.invalid` and a password chosen for this local account. A new database has **no predefined login**. The
bootstrap account is a platform administrator, separate from convention
participation.

## 3. Sign in

```powershell
uv run python src/manage.py runserver
```

Open <http://127.0.0.1:8000/admin/> and sign in with the account you just created.
You should reach the administration shell. Follow **Choose an organization**
to the Organizations page; **No organizations yet** is the expected starting
point.

The authenticated platform administrator can also read the private API
reference at <http://127.0.0.1:8000/api/v1/docs/> or
<http://127.0.0.1:8000/api/v1/redoc/>. The canonical schema is at
<http://127.0.0.1:8000/api/v1/schema>.

For pre-populated fictional records, stop the server with Ctrl+C, then follow
[the demonstration-data instructions](../development/setup.md#fictional-demonstration-data).
Use the empty database when following the manual organizer-setup tour.

## Stop or troubleshoot

Stop Django with Ctrl+C. `docker compose stop postgres` stops this project's
PostgreSQL service and keeps its database. Do not delete a volume to resolve a
setup problem without identifying the data it contains.

| Symptom | Check |
| --- | --- |
| PostgreSQL cannot start on port 5432 | Check for an existing local PostgreSQL service or Compose project before starting another. |
| Database does not exist | Confirm the URL ends in `/maru`, or explicitly create the separate tutorial database using its runbook. |
| `identity.W001` reports invitation encryption unavailable | The basic local shell can start, but invitation commands fail closed until their dedicated keys and policy are configured. See the [invitation boundary](../development/setup.md#local-invitation-boundary); creating a bootstrap administrator does not configure invitation delivery. |
| Login fails on a fresh installation | Use the account created by `createsuperuser`; historical tutorial credentials are not installed automatically. |
| Python version is unsupported | Run `uv python find` and use Python 3.12–3.14. |

For settings, fixtures, frontend development, and release-image evaluation,
continue with [development setup](../development/setup.md).

**Next:** [Follow a product tour](product-tour.md), or
[make a first contribution](first-contribution.md).
