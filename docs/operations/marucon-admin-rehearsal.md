# Marucon admin-first educational rehearsal

Status: Executable local/test scenario
Last updated: 2026-07-31

This walkthrough creates a disposable Marucon environment in which the first
registered account is the platform administrator. It imports the requested
public volunteer handles only after explicit acknowledgement. Never point it
at a database containing work you need to keep.

## 1. Create a separate empty database

Choose a new database name. Do not use `maru`, the ordinary demo database, or
any shared environment.

```powershell
docker compose up -d postgres
docker compose exec -T postgres createdb -U maru marucon_rehearsal
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/marucon_rehearsal"
uv run python src/manage.py migrate
```

Keep `MARU_DATABASE_URL` set in every terminal for this rehearsal. The seed
command refuses an account table whose first row is not its deterministic
administrator; it never flushes or resets the database.

## 2. Build the Marucon scenario

Review the source page and acknowledge the bounded import:

```powershell
uv run python src/manage.py seed_marucon_rehearsal --accept-public-roster
```

The adapter accepts only HTTPS on `awoostria.at`. It copies public handles,
department names/descriptions, and role labels. It ignores recruiting-call
headings and never downloads avatars or contact data. Accounts receive
collision-safe `.invalid` email addresses.

The JSON result includes counts and the selected public Chair handle. Local
credentials are:

```text
Administrator username: admin
Administrator email: admin@marucon.invalid
Shared password: M4rucon-Rehearsal-2031!
```

Every imported rehearsal account uses that password. It is public test data;
never reuse it for a real account or deployment.

## 3. Inspect the administrator journey

Run Maru and sign in at <http://127.0.0.1:8000/admin/> as `admin`.

1. Confirm Convention work and Specialist records share one Django
   administration shell.
2. Confirm the global Quick Start strip is absent.
3. Use the Django header's convention selector to choose Marucon 2031.
4. Open **Convention work → Organization structure**.
5. Confirm Executive Board is the root, Helper Board is below it, ordinary
   departments are Board responsibilities, and the selected subdepartments
   are nested.
6. Inspect people with several roles and positions with several holders.
7. Open a Specialist record and compare its heading, fields, buttons, modules,
   tables, spacing, and responsive behavior with a Convention work inner page.

The `admin` account is the bootstrap controller. The imported Chair is the
independent approver. The fixture uses the same guarded bootstrap and
dual-controlled workforce appointment services as ordinary administration;
displayed role labels do not grant authority by themselves.

## 4. Inspect registration and account boundaries

The seed creates and publishes a Marucon registration template, then inherits
it into the active Marucon 2031 configuration. It contains:

- attendee-visible badge-name and accessibility questions;
- a staff-only onboarding note hidden from public/self forms;
- standard paid weekend admission;
- restricted Infinity admission requiring organizer-assigned
  `infinity-eligible` capacity;
- an attendee/staff additional-address-detail profile extension; and
- a staff-only internal identity-check extension.

Sign out and sign in with any imported public handle and the shared password.
Open the `public_registration_path` from the command output. Confirm that the
attendee can complete registration but cannot see the staff-only question or
select Infinity admission without authoritative eligibility.

After a registration exists, **My registration** shows attendee-visible
profile extensions. Updating one appends a value revision; it never rewrites
the immutable submitted answer snapshot. Administrators manage reviewed field
definitions in Specialist records. Authorized registration staff can write a
shared or staff-only field only with a reason. Infinity-holder state remains a
product/entitlement fact, not an editable checkbox.

## 5. Run the educational smoke test

The automated test uses a small synthetic HTML roster, not live public
handles:

```powershell
uv run pytest tests/integration/test_marucon_rehearsal.py -q
```

It proves first-account administration, shared-password handle login,
organization/series/edition creation, nested hierarchy, multiple roles,
template inheritance, public question minimization, authoritative Infinity
eligibility, structure access, production-settings refusal, explicit network
acknowledgement, and idempotent reruns.

## 6. Cleanup

Stop the rehearsal server first. Verify that `MARU_DATABASE_URL` ends exactly
in `/marucon_rehearsal` and that no valuable work was added. Only then drop the
separately named database deliberately:

```powershell
docker compose exec -T postgres dropdb -U maru marucon_rehearsal
```

Do not run `flush`, delete the PostgreSQL volume, or drop the ordinary `maru`
database. If there is any uncertainty, retain the rehearsal database instead
of deleting it.
