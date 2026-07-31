"""Deterministic local Marucon admin-first educational rehearsal."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from maru.authorization.models import RoleBundle
from maru.events.models import EventEdition
from maru.events.services import transition_edition
from maru.identity.models import Account
from maru.organizations.models import ConventionSeries, Organization
from maru.registration.models import (
    AdmissionProduct,
    ConfigurationStatus,
    ProfileExtensionReviewStatus,
    ProfileExtensionStatus,
    ProfileExtensionWriter,
    QuestionClassification,
    QuestionFieldType,
    QuestionVisibility,
    RegistrationConfiguration,
    RegistrationProfileExtensionField,
    RegistrationQuestion,
    RegistrationSection,
    RegistrationTemplate,
)
from maru.registration.services import (
    activate_configuration,
    create_configuration_draft,
    publish_configuration_as_template,
)
from maru.workforce.bootstrap import bootstrap_organization_workforce
from maru.workforce.models import (
    Department,
    Position,
    PositionAssignment,
    PositionTemplate,
)
from maru.workforce.services import activate_position_assignment

from .public_roster import PublicRosterDepartment

MARUCON_NAMESPACE = UUID("743e58cb-30da-49b0-871e-945a99377ef3")
MARUCON_ADMIN_EMAIL = "admin@marucon.invalid"
MARUCON_SHARED_PASSWORD = "M4rucon-Rehearsal-2031!"  # noqa: S105
MARUCON_EDITION_SLUG = "marucon-2031"

SUBDEPARTMENT_PARENTS = {
    "Graphics Design": "Art Department",
    "Maid Cafe": "Events & Programming",
    "Ceremonies": "Events & Programming",
    "PEER": "Human Resources",
}


class MaruconRehearsalConflictError(RuntimeError):
    """The existing local database cannot preserve the scenario invariants."""


@dataclass(frozen=True, slots=True)
class MaruconRehearsalSummary:
    administrator_username: str
    administrator_email: str
    chair_username: str
    organization_slug: str
    edition_slug: str
    roster_accounts: int
    departments: int
    positions: int
    assignments: int
    registration_template: str
    registration_configuration_version: int
    public_registration_path: str

    def as_dict(self) -> dict[str, object]:
        return {
            "administrator_username": self.administrator_username,
            "administrator_email": self.administrator_email,
            "chair_username": self.chair_username,
            "organization_slug": self.organization_slug,
            "edition_slug": self.edition_slug,
            "roster_accounts": self.roster_accounts,
            "departments": self.departments,
            "positions": self.positions,
            "assignments": self.assignments,
            "registration_template": self.registration_template,
            "registration_configuration_version": (
                self.registration_configuration_version
            ),
            "public_registration_path": self.public_registration_path,
        }


def _fixture_id(kind: str, value: str) -> UUID:
    return uuid5(MARUCON_NAMESPACE, f"{kind}:{value}")


def _stable_code(prefix: str, *parts: str) -> str:
    source = ":".join(parts)
    stem = slugify("-".join(parts))[:58].strip("-") or prefix
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{stem}-{digest}"[:80].rstrip("-")


def _roster_accounts(
    *,
    departments: tuple[PublicRosterDepartment, ...],
    password: str,
) -> dict[str, Account]:
    usernames: dict[str, str] = {}
    for department in departments:
        for assignment in department.assignments:
            key = assignment.username.casefold()
            existing = usernames.get(key)
            if existing is not None and existing != assignment.username:
                raise MaruconRehearsalConflictError(
                    "The roster contains usernames that differ only by letter case: "
                    f"{existing!r} and {assignment.username!r}."
                )
            usernames[key] = assignment.username
    password_hash = make_password(password)
    accounts: dict[str, Account] = {}
    for casefolded, username in sorted(usernames.items()):
        account_id = _fixture_id("account", casefolded)
        account = Account.objects.filter(id=account_id).first()
        email = (
            "roster-"
            f"{hashlib.sha256(casefolded.encode('utf-8')).hexdigest()[:20]}"
            "@marucon.invalid"
        )
        if account is None:
            if (
                Account.objects.filter(
                    login_handle__iexact=username,
                )
                .exclude(id=account_id)
                .exists()
            ):
                raise MaruconRehearsalConflictError(
                    f"An unrelated account already uses roster username {username!r}."
                )
            account = Account(
                id=account_id,
                email=email,
                login_handle=username,
                display_name=username,
                password=password_hash,
                email_verified_at=timezone.now(),
            )
            account.full_clean()
            account.save(force_insert=True)
        elif account.login_handle != username or account.email != email:
            raise MaruconRehearsalConflictError(
                f"The fixture identity for {username!r} belongs to other data."
            )
        accounts[casefolded] = account
    return accounts


def _generic_position_template_code(department: str, role: str) -> str:
    normalized_role = role.casefold()
    normalized_department = department.casefold()
    template_code = "volunteer"
    if department == "Executive Board":
        if "chairman" in normalized_role and "vice" not in normalized_role:
            template_code = "convention-chair"
        elif "vice-chair" in normalized_role:
            template_code = "vice-chair"
        elif "accountant" in normalized_role:
            template_code = "treasurer"
        else:
            template_code = "board-member"
    elif department == "Helper Board":
        template_code = "board-member"
    elif "front desk" in normalized_department:
        template_code = "front-desk"
    elif "registration" in normalized_department and "lead" in normalized_role:
        template_code = "registration-lead"
    elif "lead" in normalized_role:
        template_code = "department-lead"
    elif "deputy" in normalized_role or "supervisor" in normalized_role:
        template_code = "staff-member"
    return template_code


def _ensure_hierarchy(
    *,
    organization: Organization,
    edition: EventEdition,
    roster: tuple[PublicRosterDepartment, ...],
) -> dict[str, Department]:
    executive = Department.objects.get(
        organization=organization,
        edition=edition,
        code__in=("convention-leadership", "executive-board"),
    )
    executive.code = "executive-board"
    executive.name = "Executive Board"
    executive.description = next(
        (
            department.description
            for department in roster
            if department.name == "Executive Board"
        ),
        "Accountable board for the organizer and every convention department.",
    )
    executive.position = 0
    executive.save(
        update_fields=("code", "name", "description", "position", "updated_at")
    )
    by_name = {"Executive Board": executive}
    for index, department in enumerate(roster, start=1):
        if department.name == "Executive Board":
            continue
        code = _stable_code("department", department.name)
        item, _ = Department.objects.update_or_create(
            organization=organization,
            edition=edition,
            code=code,
            defaults={
                "name": department.name,
                "description": department.description,
                "position": index * 10,
            },
        )
        by_name[department.name] = item
    for name, department_record in by_name.items():
        if name == "Executive Board":
            continue
        parent_name = SUBDEPARTMENT_PARENTS.get(name, "Executive Board")
        parent = by_name.get(parent_name, executive)
        if department_record.parent_id != parent.id:
            department_record.parent = parent
            department_record.save(update_fields=("parent", "updated_at"))
    return by_name


def _ensure_positions_and_assignments(
    *,
    organization: Organization,
    edition: EventEdition,
    administrator: Account,
    chair: Account,
    departments: dict[str, Department],
    roster: tuple[PublicRosterDepartment, ...],
    accounts: dict[str, Account],
) -> None:
    grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
    for department in roster:
        for assignment in department.assignments:
            grouped[(department.name, assignment.role)].add(
                assignment.username.casefold()
            )

    chair_position = Position.objects.get(edition=edition, code="convention-chair")
    for (department_name, role), account_keys in sorted(grouped.items()):
        generic_code = _generic_position_template_code(department_name, role)
        template = PositionTemplate.objects.get(
            organization=organization,
            code=generic_code,
            version=1,
        )
        position_code = _stable_code("position", department_name, role)
        is_seed_chair_position = (
            department_name == "Executive Board"
            and generic_code == "convention-chair"
            and chair.login_handle.casefold() in account_keys
        )
        if is_seed_chair_position:
            position = chair_position
            position.department = departments[department_name]
            position.title = role
            position.description = (
                f"{role} in {department_name}. Imported from the acknowledged "
                "public rehearsal roster."
            )
            position.headcount = len(account_keys)
            position.save(
                update_fields=(
                    "department",
                    "title",
                    "description",
                    "headcount",
                    "updated_at",
                )
            )
        else:
            role_code = _stable_code("roster-role", department_name, role)
            role_bundle = RoleBundle.objects.filter(
                organization=organization,
                code=role_code,
                version=1,
            ).first()
            if role_bundle is None:
                role_bundle = RoleBundle.objects.create(
                    organization=organization,
                    code=role_code,
                    name=f"{department_name}: {role}"[:120],
                    version=1,
                    capability_codes=list(template.role_bundle.capability_codes),
                    created_by=administrator,
                    approved_by=chair,
                    reason="Local Marucon public-roster rehearsal role.",
                )
            position, created = Position.objects.get_or_create(
                organization=organization,
                edition=edition,
                code=position_code,
                defaults={
                    "template": template,
                    "department": departments[department_name],
                    "role_bundle": role_bundle,
                    "title": role,
                    "description": (
                        f"{role} in {department_name}. Imported from the "
                        "acknowledged public rehearsal roster."
                    ),
                    "headcount": len(account_keys),
                    "capacity_codes": list(template.default_capacity_codes),
                    "status": Position.Status.OPEN,
                    "created_by": administrator,
                },
            )
            if not created:
                position.template = template
                position.department = departments[department_name]
                position.role_bundle = role_bundle
                position.title = role
                position.description = (
                    f"{role} in {department_name}. Imported from the "
                    "acknowledged public rehearsal roster."
                )
                position.headcount = len(account_keys)
                position.capacity_codes = list(template.default_capacity_codes)
                position.save(
                    update_fields=(
                        "template",
                        "department",
                        "role_bundle",
                        "title",
                        "description",
                        "headcount",
                        "capacity_codes",
                        "updated_at",
                    )
                )
        for account_key in sorted(account_keys):
            account = accounts[account_key]
            if PositionAssignment.objects.filter(
                position=position,
                account=account,
                status__in=(
                    PositionAssignment.Status.PROPOSED,
                    PositionAssignment.Status.ACTIVE,
                ),
            ).exists():
                continue
            assignment_actor = chair if account.id == chair.id else administrator
            assignment_approver = administrator if account.id == chair.id else chair
            activate_position_assignment(
                actor=assignment_actor,
                approver=assignment_approver,
                position_id=position.id,
                account=account,
                reason=(
                    "Activate the acknowledged public-roster role for the local "
                    "Marucon rehearsal."
                ),
                correlation_id=uuid4(),
                effective_from=timezone.now(),
                expires_at=None,
            )


def _ensure_registration(
    *,
    organization: Organization,
    edition: EventEdition,
    administrator: Account,
) -> tuple[RegistrationTemplate, RegistrationConfiguration]:
    template = RegistrationTemplate.objects.filter(
        organization=organization,
        series=edition.series,
        code="marucon-attendee-registration",
        status="published",
    ).first()
    if template is None:
        opens_at = timezone.now() - timedelta(days=1)
        closes_at = datetime(
            2031,
            7,
            15,
            23,
            59,
            tzinfo=ZoneInfo("Europe/Vienna"),
        )
        configuration = RegistrationConfiguration.objects.create(
            organization=organization,
            edition=edition,
            name="Marucon registration template source",
            version=1,
            opens_at=opens_at,
            closes_at=closes_at,
            capacity=1_500,
            currency="EUR",
            created_by_id=administrator.id,
        )
        section = RegistrationSection.objects.create(
            configuration=configuration,
            key="convention-profile",
            title="Convention profile",
            description="Details used to prepare the attendee experience.",
            position=10,
        )
        RegistrationQuestion.objects.create(
            configuration=configuration,
            section=section,
            key="badge-name",
            label="Name on badge",
            help_text="Use the name other attendees should see.",
            field_type=QuestionFieldType.SHORT_TEXT,
            required=True,
            position=10,
            purpose="Print and display the attendee badge.",
            visibility=QuestionVisibility.ATTENDEE_AND_STAFF,
            classification=QuestionClassification.PERSONAL,
        )
        RegistrationQuestion.objects.create(
            configuration=configuration,
            section=section,
            key="accessibility-note",
            label="Accessibility note",
            help_text="Optional information needed to prepare reasonable support.",
            field_type=QuestionFieldType.LONG_TEXT,
            required=False,
            position=20,
            purpose="Prepare requested accessibility support.",
            visibility=QuestionVisibility.ATTENDEE_AND_STAFF,
            classification=QuestionClassification.PERSONAL,
        )
        RegistrationQuestion.objects.create(
            configuration=configuration,
            section=section,
            key="internal-onboarding-note",
            label="Internal onboarding note",
            help_text="Registration staff evidence; never shown to the attendee.",
            field_type=QuestionFieldType.LONG_TEXT,
            required=False,
            position=30,
            purpose="Record a reasoned staff-assisted registration note.",
            visibility=QuestionVisibility.REGISTRATION_STAFF,
            classification=QuestionClassification.INTERNAL,
        )
        AdmissionProduct.objects.create(
            configuration=configuration,
            code="weekend-admission",
            name="Weekend admission",
            description="Standard Marucon admission for the full weekend.",
            price_minor=9_000,
            capacity=1_450,
            position=10,
            entitlement_code="event-admission",
            entitlement_name="Marucon admission",
        )
        AdmissionProduct.objects.create(
            configuration=configuration,
            code="infinity-admission",
            name="Infinity admission",
            description="Admission for organizer-verified Infinity holders.",
            price_minor=0,
            capacity=50,
            position=20,
            entitlement_code="infinity-ticket",
            entitlement_name="Infinity ticket",
            required_capacity_codes=["infinity-eligible"],
            eligibility_explanation=(
                "An organizer must first add the Infinity eligibility capacity "
                "to your edition participation."
            ),
        )
        activate_configuration(
            organization_id=organization.id,
            edition_id=edition.id,
            configuration_id=configuration.id,
            actor=administrator,
            reason="Review and activate the local Marucon template source.",
            correlation_id=uuid4(),
            source_channel="rehearsal",
        )
        template = publish_configuration_as_template(
            organization_id=organization.id,
            edition_id=edition.id,
            configuration_id=configuration.id,
            actor=administrator,
            code="marucon-attendee-registration",
            name="Marucon attendee registration",
            description=(
                "Educational registration starting point for the Marucon rehearsal."
            ),
            series_limited=True,
            reason="Publish the reviewed Marucon rehearsal template.",
            correlation_id=uuid4(),
            source_channel="rehearsal",
        )

    inherited = (
        RegistrationConfiguration.objects.filter(
            organization=organization,
            edition=edition,
            source_template=template,
        )
        .order_by("-version")
        .first()
    )
    if inherited is None:
        opens_at = timezone.now() - timedelta(days=1)
        closes_at = datetime(
            2031,
            7,
            15,
            23,
            59,
            tzinfo=ZoneInfo("Europe/Vienna"),
        )
        inherited = create_configuration_draft(
            organization_id=organization.id,
            edition_id=edition.id,
            actor=administrator,
            name="Marucon 2031 attendee registration",
            source_template_id=template.id,
            reason="Inherit the selected Marucon template for the rehearsal edition.",
            correlation_id=uuid4(),
            source_channel="rehearsal",
            opens_at=opens_at,
            closes_at=closes_at,
            capacity=1_500,
            currency="EUR",
        )
    if inherited.status == ConfigurationStatus.DRAFT:
        inherited = activate_configuration(
            organization_id=organization.id,
            edition_id=edition.id,
            configuration_id=inherited.id,
            actor=administrator,
            reason=(
                "Reviewed the inherited questions, writer visibility, products, "
                "capacity, dates, and currency."
            ),
            correlation_id=uuid4(),
            source_channel="rehearsal",
        )

    if not RegistrationProfileExtensionField.objects.filter(
        edition=edition,
        key="additional-address-detail",
        status=ProfileExtensionStatus.ACTIVE,
    ).exists():
        RegistrationProfileExtensionField.objects.create(
            organization=organization,
            edition=edition,
            key="additional-address-detail",
            version=1,
            label="Additional address detail",
            help_text=(
                "Add a missing building, delivery, or location detail if organizers "
                "request it after registration."
            ),
            field_type=QuestionFieldType.SHORT_TEXT,
            purpose="Complete a missing current registration address detail.",
            classification=QuestionClassification.PERSONAL,
            attendee_visible=True,
            writer_policy=ProfileExtensionWriter.ATTENDEE_AND_STAFF,
            required=False,
            position=10,
            review_status=ProfileExtensionReviewStatus.APPROVED,
            status=ProfileExtensionStatus.ACTIVE,
            created_by=administrator,
            approved_by=administrator,
            approved_at=timezone.now(),
        )
    if not RegistrationProfileExtensionField.objects.filter(
        edition=edition,
        key="internal-identity-check",
        status=ProfileExtensionStatus.ACTIVE,
    ).exists():
        RegistrationProfileExtensionField.objects.create(
            organization=organization,
            edition=edition,
            key="internal-identity-check",
            version=1,
            label="Internal identity check",
            help_text="Reasoned registration-staff verification only.",
            field_type=QuestionFieldType.BOOLEAN,
            purpose="Record whether registration staff completed the required check.",
            classification=QuestionClassification.INTERNAL,
            attendee_visible=False,
            writer_policy=ProfileExtensionWriter.REGISTRATION_STAFF,
            required=False,
            position=20,
            review_status=ProfileExtensionReviewStatus.APPROVED,
            status=ProfileExtensionStatus.ACTIVE,
            created_by=administrator,
            approved_by=administrator,
            approved_at=timezone.now(),
        )
    return template, inherited


@transaction.atomic
def seed_marucon_rehearsal(
    *,
    roster: tuple[PublicRosterDepartment, ...],
    password: str = MARUCON_SHARED_PASSWORD,
) -> MaruconRehearsalSummary:
    """Build or resume the bounded local scenario without checked-in roster data."""

    administrator_id = _fixture_id("account", "administrator")
    first_account = Account.objects.order_by("date_joined", "id").first()
    if first_account is not None and first_account.id != administrator_id:
        raise MaruconRehearsalConflictError(
            "The Marucon rehearsal requires a clean account table so its "
            "administrator is the first registered Maru account."
        )
    administrator = Account.objects.filter(id=administrator_id).first()
    if administrator is None:
        administrator = Account.objects.create_superuser(
            id=administrator_id,
            email=MARUCON_ADMIN_EMAIL,
            login_handle="admin",
            display_name="Maru Administrator",
            password=password,
            email_verified_at=timezone.now(),
        )
    roster_accounts = _roster_accounts(departments=roster, password=password)
    chair_assignment = next(
        (
            assignment
            for department in roster
            if department.name == "Executive Board"
            for assignment in department.assignments
            if "chairman" in assignment.role.casefold()
            and "vice" not in assignment.role.casefold()
        ),
        None,
    )
    if chair_assignment is None:
        raise MaruconRehearsalConflictError(
            "The roster needs a distinct Executive Board chair for dual control."
        )
    chair = roster_accounts[chair_assignment.username.casefold()]

    organization, _ = Organization.objects.get_or_create(
        slug="marucon-organizers",
        defaults={
            "name": "Marucon Organizers",
            "description": (
                "Local educational organizer created by the Marucon rehearsal."
            ),
            "country_code": "AT",
            "default_language_codes": ["en", "de"],
            "default_time_zone": "Europe/Vienna",
        },
    )
    series, _ = ConventionSeries.objects.get_or_create(
        organization=organization,
        slug="marucon",
        defaults={
            "name": "Marucon",
            "description": "Recurring Marucon convention series.",
        },
    )
    edition, _ = EventEdition.objects.get_or_create(
        organization=organization,
        series=series,
        slug=MARUCON_EDITION_SLUG,
        defaults={
            "name": "Marucon 2031",
            "time_zone": "Europe/Vienna",
            "language_codes": ["en", "de"],
            "currency_codes": ["EUR"],
            "starts_on": date(2031, 8, 14),
            "ends_on": date(2031, 8, 17),
        },
    )
    if not RoleBundle.objects.filter(organization=organization).exists():
        bootstrap_organization_workforce(
            organization=organization,
            edition=edition,
            controller=administrator,
            chair=chair,
            reason=(
                "Establish accountable authority for the local Marucon "
                "admin-first rehearsal."
            ),
            correlation_id=uuid4(),
            source_channel="rehearsal",
        )
    if edition.lifecycle == EventEdition.Lifecycle.DRAFT:
        edition = transition_edition(
            organization_id=organization.id,
            edition_id=edition.id,
            to_state=EventEdition.Lifecycle.PREPARING,
            actor=administrator,
            reason="Open the local Marucon edition for convention preparation.",
            correlation_id=_fixture_id("lifecycle-correlation", edition.slug),
            source_channel="rehearsal",
        )
    departments = _ensure_hierarchy(
        organization=organization,
        edition=edition,
        roster=roster,
    )
    _ensure_positions_and_assignments(
        organization=organization,
        edition=edition,
        administrator=administrator,
        chair=chair,
        departments=departments,
        roster=roster,
        accounts=roster_accounts,
    )
    template, configuration = _ensure_registration(
        organization=organization,
        edition=edition,
        administrator=administrator,
    )
    return MaruconRehearsalSummary(
        administrator_username=administrator.login_handle,
        administrator_email=administrator.email,
        chair_username=chair.login_handle,
        organization_slug=organization.slug,
        edition_slug=edition.slug,
        roster_accounts=len(roster_accounts),
        departments=Department.objects.filter(edition=edition).count(),
        positions=Position.objects.filter(edition=edition).count(),
        assignments=PositionAssignment.objects.filter(edition=edition).count(),
        registration_template=f"{template.code}:v{template.version}",
        registration_configuration_version=configuration.version,
        public_registration_path=f"/register/{edition.id}/",
    )
