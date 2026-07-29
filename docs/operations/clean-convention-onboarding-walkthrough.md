# Clean convention and volunteer onboarding walkthrough

Status: Executable local rehearsal  
Last updated: 2026-07-29

This walkthrough starts with an empty, separately named local database. It
does not use `seed_demo_data`, and it does not delete or modify an existing
demo database. Use synthetic identities and documents only.

## 1. Start Maru and create the bootstrap administrator

```powershell
docker compose up -d postgres
docker compose exec -T postgres createdb -U maru maru_walkthrough
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru_walkthrough"
uv run python src/manage.py migrate
uv run python src/manage.py createsuperuser
uv run python src/manage.py runserver
```

Sign in at <http://127.0.0.1:8000/admin/>. Keep this first account as the
bootstrap controller; do not share it with the Convention Chair.

Use a different new database name if `maru_walkthrough` already exists. Keep
`MARU_DATABASE_URL` set in every terminal used for this walkthrough; otherwise
a command will use the ordinary `maru` database. The database name is explicit
so cleanup can be deliberate after the rehearsal.

## 2. Create the convention structure and people

In bootstrap admin:

1. create an Organization at `/admin/organizations/organization/add/`;
2. create its Convention Series at
   `/admin/organizations/conventionseries/add/`;
3. create the Event Edition at `/admin/events/eventedition/add/`;
4. create a separate active Convention Chair account at
   `/admin/identity/account/add/`.

Use lowercase stable slugs. Keep the edition in a non-closed lifecycle.
The attendee may already have an account, but you no longer need to create one
in bootstrap admin before staff-assisted registration.

## 3. Establish the first Chairman and starter templates

In bootstrap administration, choose **First convention setup**:

1. choose the organization and its matching edition;
2. choose the separate Chair account;
3. record why this initial authority is being established;
4. type the organization slug exactly;
5. confirm the logged-in superuser's current password; and
6. submit once.

The wizard creates the Chair position and starter template catalog through the
same audited one-shot service as the operator command. Repeating it is expected
to fail, and an organization with existing authority is omitted.

No command line is needed for this normal path after the environment,
migrations, and first superuser have been prepared. For operator recovery or
automation, the equivalent PowerShell fallback is below. The database
assignment and Python invocation must be separate statements:

```powershell
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru_walkthrough"
& ".\.venv\Scripts\python.exe" src/manage.py bootstrap_convention `
  --organization YOUR_ORGANIZATION_SLUG `
  --edition YOUR_EDITION_SLUG `
  --controller-email YOUR_ADMIN_EMAIL `
  --chair-email YOUR_CHAIR_EMAIL `
  --reason "Establish the first accountable convention leadership." `
  --confirm-organization YOUR_ORGANIZATION_SLUG
```

The command prints the same created counts.

## 4. Create and activate the registration form

Open `/admin/registration/registrationconfiguration/add/`.

1. select the organization and edition;
2. set name, opening/closing dates, overall capacity, currency, minimum age,
   payment window, and wait-list behavior;
3. save the draft;
4. add at least one section/question and one paid admission product;
5. verify each question purpose and visibility and each product's price,
   capacity, sales window, entitlement, and payment window; and
6. open Staff Console `/staff/`, select the edition, open Commerce, and
   activate the reviewed draft with a meaningful reason.

The public dates may deliberately be in the future for this rehearsal.

## 5. Staff-register the attendee outside opening hours

From Staff Console Commerce choose **Add attendee outside public hours**.

1. enter the attendee email;
2. if it exact-matches an active Maru account, verify that person is intended;
3. if Maru shows the new-email warning, enter the person's display name and a
   policy-valid temporary password, then transfer that password through a
   separate secure channel;
4. choose the paid product;
5. complete the same profile and configured questions, choosing telephone
   country initials/flag/calling prefix before each local number;
6. record why staff is acting for this person; and
7. submit.

The missing-email fallback creates an unverified platform account atomically
with the participation and registration. It never overwrites an existing or
inactive account and records a separate privileged audit event.

Maru ignores only the public configuration and product sale windows. It still
checks active configuration, account/restriction, age, answers, product
eligibility, price, capacity, duplicates, and payment deadline. The new record
must say `Payment pending`; staff assistance never marks a paid ticket paid.

## 6. Open the NDA upload

In bootstrap admin:

1. create an active version of **Volunteer NDA** at
   `/admin/workforce/onboardingdocumenttype/add/`;
2. create a request at `/admin/workforce/onboardingdocumentrequest/add/`;
3. select the exact organization, edition, document version, and attendee;
4. add safe instructions and an optional due date; and
5. save.

Activation freezes the agreement version. Correct wording by creating a new
version, not editing the active one.

## 7. Sign in as the attendee, pay, and upload

Sign out, then sign in with the attendee account. Open
`/register/<edition_id>/profile/`.

1. choose **Simulate payment (local only)** and verify the registration becomes
   Confirmed;
2. choose **My onboarding documents** and upload a signed PDF;
3. choose **Edit convention profile**;
4. add a profile image;
5. enable bringing fursuits, add a fursuit and image; and
6. save.

The payment button exists only with the local/test payment adapter. It records
a successful synthetic provider attempt; it is not production payment
verification. Local uploads are marked unscanned rehearsal files. New images
must show Pending review.

## 8. Review agreement and images

Sign back in as the bootstrap administrator.

1. open Workforce onboarding document requests;
2. open the exact PDF through its protected download;
3. compare the account, agreement version, signature, and expected file;
4. set Approved and record a review reason;
5. open Staff Console Commerce;
6. find the pending profile and fursuit images; and
7. approve or reject each with its own reason.

Approved evidence cannot be rewritten. Rejected documents can be replaced by
the owner.

## 9. Create the department, position, hierarchy, and public opening

In Workforce bootstrap admin:

1. create a department, optionally under Convention Leadership;
2. create a position from a starter template such as Registration Lead;
3. set headcount, department, and `reports to` position;
4. attach Volunteer NDA as a position document requirement;
5. save, then edit its automatically created Volunteer Opportunity;
6. publish the opportunity and keep **visible when filled** enabled.

Use headcount greater than one for roles with multiple holders. Filled
published opportunities stay visible but stop accepting applications.

## 10. Activate the position assignment

Open `/admin/workforce/positionassignment/add/`.

1. choose the position and attendee;
2. set the effective time and optional expiry;
3. choose the separate authorized Chair as approver;
4. record the appointment reason;
5. enable **Activate immediately after independent approval**; and
6. save.

Maru refuses activation when the NDA is missing, headcount is full, controllers
are identical or unauthorized, or scope does not agree. Success creates the
exact role assignment and edition capacities in one transaction.

For shared or production use, the named approver must actually review the
appointment. The current bootstrap selector is a rehearsal interface, not a
substitute for the planned separate approval inbox and step-up.

## 11. Verify the resulting user access

Sign in as the attendee and open `/staff/`.

For a Registration Lead example:

1. select the convention edition;
2. open Commerce;
3. verify the registration service queue is available;
4. open a safe attendee summary; and
5. verify an operation outside the assigned template remains denied.

Also revisit the attendee profile. Roles and benefits must now include
organizer-derived staff/volunteer/position capacities. They are not editable
profile claims.

## 12. Useful negative tests

- repeat `bootstrap_convention` and expect rejection;
- enter the wrong password in **First convention setup** and expect no records;
- staff-register an email that has never existed and verify the warning,
  account, `payment_pending` registration, and account-creation audit;
- enter an inactive account email and expect rejection rather than replacement;
- use a wrong tenant or edition ID and expect no record disclosure;
- try assignment before NDA approval and expect rejection;
- choose the same controller twice and expect rejection;
- fill the approved headcount and expect the opportunity to remain visible but
  stop accepting applications;
- upload a non-PDF agreement and expect rejection;
- try editing an approved agreement record and expect the database guard to
  reject it;
- let payment expire and verify lifecycle releases capacity; and
- confirm the local payment and unscanned-upload helpers are absent under
  production settings.
