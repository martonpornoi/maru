# Workforce module

Status: Position, hierarchy, opportunity, agreement, and authority-onboarding slice
Last updated: 2026-07-31

## Purpose and requirements

`maru.workforce` owns the first executable HR-007 and HR-008 slice defined by
ADR 0019. It turns an edition responsibility into explicit structure:

```text
department hierarchy
  -> position from an immutable organization template
  -> always-present publishable volunteer opportunity
  -> application and requested agreement evidence
  -> independently approved position assignment
  -> exact role-bundle version and participation capacities
```

It does not infer access from a job title, an application, a registration
answer, an uploaded file, or a profile label. Authority remains owned by
`maru.authorization`; convention participation remains owned by
`maru.participation`.

## Empty-organization bootstrap

An empty organization cannot use its own scoped permission commands before it
has a controller. Convention work's **Establish convention leadership**
ceremony is therefore a one-shot, trust-on-first-use exception.
It requires:

- an existing active Django superuser as bootstrap controller;
- a different active account as Convention Chair;
- an active organization and matching non-closed edition;
- an exact repeated organization slug and reason;
- no existing grants, role assignments, or role bundles in the organization.

It creates organization-scoped authority-controller roles for both people,
edition-scoped Convention Chair authority, the first leadership department and
chair position, and ten furry-convention position templates. A second run
fails closed.

The ceremony appears contextually in Convention work's **Setup guide** only to
an active superuser while an eligible organizer has no authority records. It lists recognizable
organization, edition, and Chair labels, requires the controller's current
password, exact organization slug, and a permanent reason, and delegates to
the same atomic service as the command. Candidate account reads, denied
attempts, and success are audited. After completion it becomes a read-only
explanation; later changes use ordinary dual-controlled access and appointment
workflows.

`bootstrap_convention` remains the recovery/operator fallback. In PowerShell,
set the database in a separate statement and invoke the virtual-environment
Python with `&`:

```powershell
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru_walkthrough"
& ".\.venv\Scripts\python.exe" src/manage.py bootstrap_convention `
  --organization ORGANIZATION_SLUG `
  --edition EDITION_SLUG `
  --controller-email ADMIN_EMAIL `
  --chair-email CHAIR_EMAIL `
  --reason "Establish the first accountable convention leadership." `
  --confirm-organization ORGANIZATION_SLUG
```

Starter templates cover Convention Chair, Vice Chair, Board Member, Department
Lead, Registration Lead, Front Desk, Treasurer, Profile Media Moderator, Staff
Member, and Volunteer. Templates pin an exact immutable role-bundle version,
default headcount, and capacity codes.

## Organization structure projection

Convention work has a separate **Organization structure** page backed by:

```text
GET /api/v1/organizations/{organization_id}/editions/{edition_id}/workforce/structure
```

The projection requires `workforce.view_structure`, exact organization and
edition scope, and returns nested department relationships, positions, current
holders, login handles, and each holder's other current positions. It omits
email, document evidence, application data, private profile data, and technical
authority records. Department parents support arbitrary same-edition nesting;
position headcount supports several leads or deputies; one account may hold
several positions in several departments.

The local-only Marucon rehearsal demonstrates Executive Board as the root,
Helper Board and ordinary departments below it, and selected nested
subdepartments. Public roster labels become workforce appointments through the
ordinary dual-controlled service; labels alone never grant authority.

## Positions and published opportunities

A department belongs to exactly one organization and edition and may have one
same-edition parent. A position belongs to one department, may report to
another same-edition position, pins one template and role bundle, and has an
explicit headcount. PostgreSQL rejects cross-organization or cross-edition
relationships even when ORM validation is bypassed.

Creating a position automatically creates its one-to-one volunteer
opportunity. Organizers may publish, close, or withdraw the opportunity and
set application dates. A published filled position remains in the public list
when `visible_when_filled` is enabled, but it no longer accepts applications.
Headcount greater than one supports roles with multiple holders.

An application is an expression of interest only. Accepting or reviewing it
does not grant a role, capacity, or access.

## Reviewed onboarding documents

An onboarding document type is an edition-owned, versioned agreement such as a
Volunteer NDA. Activating it freezes its wording, size limit, and retention
notice; replacement requires a new version.

Staff creates a document request for an exact account and document version.
The account can upload a PDF from its convention profile or API. Maru limits
size, verifies PDF signature and media type, computes a SHA-256 digest, and
requires malware-scanner evidence. The exact submitted file stays private.
Review requires `workforce.manage_documents` and a reason.

Local debug settings deliberately provide an unscanned rehearsal adapter so a
developer can exercise the workflow without ClamAV. It is labelled
`local_rehearsal_clean_unscanned`, cannot activate outside `DEBUG`, and does
not weaken production's fail-closed scanner requirement.

Approved evidence is immutable at the database layer. A rejected request may
receive a replacement; a new agreement version needs a new request.

## Assignment and authority

Position activation requires:

- a non-closed position below its headcount;
- every document type attached to the position approved for the recipient;
- two distinct controllers who both hold
  `workforce.manage_assignments` and `authorization.manage_roles`;
- an explicit reason and effective interval; and
- the recipient, role bundle, organization, and edition to agree.

The transaction invokes the authorization module's dual-control role command,
activates the person's edition participation, adds the configured
`staff`/`volunteer` capacities and a stable `position.<position-code>`
capacity, records the position assignment, updates filled/open state, writes
both controller audits, and publishes a registered domain event. A failure
rolls the whole operation back.

The current position-assignment Advanced-record form identifies the second
controller and checks their live authority. A production approval inbox with a
separate approver session and step-up remains future work; selecting an
identity in the local rehearsal must not be represented as that future UX.

## Interfaces

Reference web routes:

```text
/volunteer/<edition_id>/
/volunteer/<edition_id>/<opportunity_id>/apply/
/volunteer/<edition_id>/documents/
/volunteer/<edition_id>/documents/<request_id>/upload/
```

Versioned client routes:

```text
GET  /api/v1/management/convention-bootstrap
POST /api/v1/management/convention-bootstrap
GET  /api/v1/public/editions/<edition_id>/volunteer-opportunities
POST /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/opportunities/<opportunity_id>/applications/me
GET  /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/documents/me
POST /api/v1/organizations/<organization_id>/editions/<edition_id>/workforce/documents/me/<request_id>/upload
```

Specialist records:

```text
/admin/workforce/department/
/admin/workforce/positiontemplate/
/admin/workforce/position/
/admin/workforce/volunteeropportunity/
/admin/workforce/volunteerapplication/
/admin/workforce/onboardingdocumenttype/
/admin/workforce/onboardingdocumentrequest/
/admin/workforce/positionassignment/
```

## Current limitations

Qualifications, availability, shifts, time records, acceptance decisions,
position ending/replacement UX, approval notifications, document download
through the REST API, a purpose-built structure editor, and a separately
authenticated approval inbox remain Phase 3 work. The first slice is intended
to prove the safe path from a known person and reviewed agreement to scoped
working access.
