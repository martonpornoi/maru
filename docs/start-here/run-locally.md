# Run Maru locally

**Audience:** New contributors and technical evaluators\
**Outcome:** Start Maru in a disposable development environment and find its
primary interfaces\
**Reading time:** 4 minutes\
**Hands-on time:** Usually 15–30 minutes after prerequisites are installed

Use a local environment only with synthetic data. Do not point a first run at an
important database, reuse real convention records, or treat a successful local
start as production approval.

## Prepare

You need Python 3.12–3.14, `uv`, Docker with Compose, Git, and—when changing the
embedded frontend—Node 22.12 or newer plus pnpm.

Follow the [development setup](../development/setup.md) from the repository
root. Its first-setup commands synchronize locked dependencies, start the
PostgreSQL service, apply migrations to the selected development database, and
start Django. Keep `MARU_DATABASE_URL` set in every terminal that runs a Maru
management command or server.

## Confirm the basic result

After setup:

1. Open <http://127.0.0.1:8000/admin/>.
2. Create the first local bootstrap administrator only if the database is
   genuinely new.
3. Use `seed_demo_data` when you want deterministic synthetic records.
4. Treat every `.invalid` address and documented fixture password as disposable
   local data.

Authenticated platform administrators can inspect the private API contract at
`/api/v1/docs/`, `/api/v1/redoc/`, and `/api/v1/schema`. Those pages do not grant
credentials or bypass normal authorization.

## If setup does not behave as expected

Do not delete a Docker volume or reset a database you have not positively
identified as disposable. Use the setup guide's troubleshooting section and the
[empty-experience runbook](../operations/empty-experience-baseline.md) before
changing local data.

**Next:** [Follow a product tour](product-tour.md).
