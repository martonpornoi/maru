# Run Maru locally

**Audience:** New contributors and technical evaluators\
**Outcome:** Try fictional conventions in a disposable browser preview, or
create an empty development database\
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

## 2. Try the fictional conventions

From the repository root, the same commands work in PowerShell, Bash and Zsh:

```sh
uv run --locked python scripts/try_maru.py --check
uv run --locked python scripts/try_maru.py
```

The first command checks Python, dependencies, Docker and the web port without
creating resources. The second creates one temporary PostgreSQL container,
applies migrations, prepares restricted runtime access and seeds two fictional
MaruCon editions: happening now and a future gathering. The first run may also
download PostgreSQL. Startup can take several minutes; keep this terminal open.

Open the printed **Ready** link, normally <http://127.0.0.1:8765/demo/>.
The page offers separate **Author**, **Reviewer** and **Reader** practice accounts
for each event. Expand an account and use **Copy email** and **Copy password**;
the buttons can copy a hidden password when your browser allows clipboard access.
If copying is blocked, choose **Show this practice password**, select the revealed
password and copy it with your keyboard. Email and already-revealed fields are
selected for manual copying. Sign in through the normal form.
These generated credentials are intentionally available on this unshared local
practice page. Do not expose it through a tunnel or use real data. Browser copying
cannot exclude operating-system clipboard history or synchronization; use the
explicit clear button when finished. Platform/setup passwords are not displayed.

Try this short browser journey:

1. Choose **Happening now** and sign in as **Author**. Open the Guides draft
   **Preparing the welcome desk**, edit it, save and ask for review.
2. Return to `/demo/` and **Sign out to switch roles**. Sign in as **Reviewer**,
   open the waiting guide and approve it or ask for a change.
3. Switch to **Reader**, find an approved Guide and download its text. This role
   cannot see drafts, private notes or Announcements. Authors and Reviewers can
   also try writing/reviewing Announcements; nothing is posted outside Maru.
4. Try the future event with its own accounts. Each account is limited to its
   event. Reloading keeps edits and the original dates while the preview runs.
5. Press **Ctrl+C** in the terminal. The server stops and this run's database
   and anonymous volume are deleted. A new invocation starts fresh. An unattended
   preview cleans up after 60 browser minutes; `--minutes 15` (1–240) changes this.

The initial examples cover Announcements and Guides only. Prepared decisions are
synthetic setup, not independent human review. No attendee, payment, Programme,
Workforce or external-message records are created. The original organizational
tour remains available with `--scenario legacy`; it prints its public educational
account and opens `/admin/`, and is not the exact-authority practice scenario.
See [demo data](../modules/demo-data.md) for the two distinct datasets and limits.

For a repeatable startup check without leaving a server running:

```sh
uv run --locked python scripts/try_maru.py --smoke
```

This checks migration, seed, system checks, the login form and practice page, then cleans
up. It does **not** test authenticated journeys, replace browser acceptance,
certify a commit, or relax any required CI check. For a busy web port, add
`--port 8766` to either command and use the printed URL. Both web and database
ports bind only to loopback. The launcher ignores inherited Maru/Django/database
settings and never uses an existing database or Compose volume. Email stays in
the console; invitation delivery remains unavailable without its required keys.

If the terminal is forcibly killed or Docker becomes unavailable during cleanup,
the printed container ID and `org.maru.local-preview` label identify this run.
Inspect that exact resource before removing it; never use a general Docker prune
or delete another rehearsal's volume. Stop previews before full certification so
they do not compete with its database pool.

## Optional: start with an empty, persistent database

Use the manual route below when you want to keep your work or follow the organizer
creation tour. Do not run it inside the disposable preview's database.

### Start PostgreSQL and create the first account

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

### Sign in

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

Use the empty database when following the manual organizer-setup tour. For
persistent fictional records, see [demonstration data](../development/setup.md#synthetic-demonstration-data).

## Stop or troubleshoot

For the disposable preview, Ctrl+C cleans up only its owned resources.
For the manual route, stop Django with Ctrl+C. `docker compose stop postgres` stops this project's
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
