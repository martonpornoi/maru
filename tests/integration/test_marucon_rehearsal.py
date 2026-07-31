import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from rest_framework.test import APIClient

from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import ConventionSeries, Organization
from maru.registration.models import (
    AdmissionProduct,
    ConfigurationStatus,
    ProfileExtensionWriter,
    QuestionVisibility,
    RegistrationConfiguration,
    RegistrationProfileExtensionField,
    RegistrationTemplate,
)
from maru.workforce.models import Department, PositionAssignment
from tests.factories import AccountFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

SHARED_PASSWORD = "M4rucon-Rehearsal-2031!"
SYNTHETIC_ROSTER = """
<main>
  <h2>Executive Board</h2>
  <p>Accountable convention board.</p>
  <article><h3>ChairFox</h3><p>Chairman | Director</p></article>
  <article><h3>NumbersOtter</h3><p>Accountant | Director</p></article>
  <h2>Helper Board</h2>
  <p>Supports the Executive Board.</p>
  <article><h3>HelperHare</h3><p>Director</p></article>
  <h2>Art Department</h2>
  <p>Creates the convention's visual work.</p>
  <article><h3>CrossRoleCat</h3><p>Lead</p></article>
  <article><h3>ArtMarten</h3><p>Volunteer</p></article>
  <h2>Graphics Design</h2>
  <p>A nested visual production team.</p>
  <article><h3>CrossRoleCat</h3><p>Deputy</p></article>
  <h2>Registration Department</h2>
  <p>Runs attendee registration.</p>
  <article><h3>RegisterRaven</h3><p>Lead</p></article>
  <article><h3>HelperHare</h3><p>Volunteer</p></article>
  <aside><h3>This department is recruiting!</h3><p>Open positions</p></aside>
</main>
"""


def _write_roster(path: Path) -> Path:
    path.write_text(SYNTHETIC_ROSTER, encoding="utf-8")
    return path


def test_marucon_rehearsal_is_an_admin_first_educational_smoke_test(  # noqa: PLR0915
    tmp_path: Path,
) -> None:
    output = StringIO()
    roster_path = _write_roster(tmp_path / "synthetic-roster.html")

    call_command(
        "seed_marucon_rehearsal",
        roster_file=roster_path,
        password=SHARED_PASSWORD,
        stdout=output,
    )
    result = json.loads(output.getvalue())

    assert result["local_only"] is True
    assert result["administrator_username"] == "admin"
    assert result["organization_slug"] == "marucon-organizers"
    assert result["edition_slug"] == "marucon-2031"
    assert result["roster_accounts"] == 6
    assert result["shared_password"] == SHARED_PASSWORD

    accounts = list(Account.objects.order_by("date_joined", "id"))
    administrator = accounts[0]
    assert administrator.login_handle == "admin"
    assert administrator.is_staff
    assert administrator.is_superuser
    assert all(account.check_password(SHARED_PASSWORD) for account in accounts)
    assert Organization.objects.filter(slug="marucon-organizers").count() == 1
    assert ConventionSeries.objects.filter(slug="marucon").count() == 1
    edition = EventEdition.objects.get(slug="marucon-2031")

    departments = {
        item.name: item for item in Department.objects.filter(edition=edition)
    }
    assert departments["Executive Board"].parent_id is None
    assert departments["Helper Board"].parent_id == departments["Executive Board"].id
    assert departments["Art Department"].parent_id == departments["Executive Board"].id
    assert departments["Graphics Design"].parent_id == departments["Art Department"].id
    cross_role = Account.objects.get(login_handle="CrossRoleCat")
    assert (
        PositionAssignment.objects.filter(
            edition=edition,
            account=cross_role,
            status=PositionAssignment.Status.ACTIVE,
        ).count()
        == 2
    )

    template = RegistrationTemplate.objects.get(
        organization=edition.organization,
        code="marucon-attendee-registration",
        status="published",
    )
    configuration = RegistrationConfiguration.objects.get(
        edition=edition,
        source_template=template,
        status=ConfigurationStatus.ACTIVE,
    )
    assert configuration.version == 2
    assert (
        configuration.questions.filter(
            visibility=QuestionVisibility.REGISTRATION_STAFF
        ).count()
        == 1
    )
    infinity_product = AdmissionProduct.objects.get(
        configuration=configuration,
        code="infinity-admission",
    )
    assert infinity_product.required_capacity_codes == ["infinity-eligible"]
    address_field = RegistrationProfileExtensionField.objects.get(
        edition=edition,
        key="additional-address-detail",
    )
    assert address_field.attendee_visible
    assert address_field.writer_policy == ProfileExtensionWriter.ATTENDEE_AND_STAFF
    internal_field = RegistrationProfileExtensionField.objects.get(
        edition=edition,
        key="internal-identity-check",
    )
    assert not internal_field.attendee_visible
    assert internal_field.writer_policy == ProfileExtensionWriter.REGISTRATION_STAFF

    login_client = Client()
    assert login_client.login(
        username="CrossRoleCat",
        password=SHARED_PASSWORD,
    )
    registration_page = login_client.get(f"/register/{edition.id}/")
    assert registration_page.status_code == 200
    assert "Internal onboarding note" not in registration_page.content.decode()

    api_client = APIClient()
    api_client.force_authenticate(cross_role)
    definition = api_client.get(f"/api/v1/public/editions/{edition.id}/registration")
    assert definition.status_code == 200
    definition_payload = definition.json()
    assert {question["label"] for question in definition_payload["questions"]} == {
        "Name on badge",
        "Accessibility note",
    }
    infinity_payload = next(
        product
        for product in definition_payload["products"]
        if product["name"] == "Infinity admission"
    )
    assert infinity_payload["selectable"] is False

    structure = api_client.get(
        f"/api/v1/organizations/{edition.organization_id}/"
        f"editions/{edition.id}/workforce/structure"
    )
    assert structure.status_code == 200
    assert structure.json()["organization_name"] == "Marucon Organizers"
    assert "CrossRoleCat" in str(structure.json())

    counts_before = {
        "accounts": Account.objects.count(),
        "departments": Department.objects.count(),
        "assignments": PositionAssignment.objects.count(),
    }
    second_output = StringIO()
    call_command(
        "seed_marucon_rehearsal",
        roster_file=roster_path,
        password=SHARED_PASSWORD,
        stdout=second_output,
    )
    assert counts_before == {
        "accounts": Account.objects.count(),
        "departments": Department.objects.count(),
        "assignments": PositionAssignment.objects.count(),
    }


def test_marucon_rehearsal_requires_acknowledgement_for_network_import() -> None:
    with pytest.raises(CommandError, match="accept-public-roster"):
        call_command(
            "seed_marucon_rehearsal",
            stdout=StringIO(),
        )


def test_marucon_rehearsal_refuses_nonlocal_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "maru.settings.production")

    with pytest.raises(CommandError, match="only with local or test settings"):
        call_command(
            "seed_marucon_rehearsal",
            roster_file=_write_roster(tmp_path / "synthetic-roster.html"),
            stdout=StringIO(),
        )


def test_marucon_rehearsal_reports_password_file_and_database_conflicts(
    tmp_path: Path,
) -> None:
    roster_path = _write_roster(tmp_path / "synthetic-roster.html")
    with pytest.raises(CommandError, match="does not satisfy password validation"):
        call_command(
            "seed_marucon_rehearsal",
            roster_file=roster_path,
            password="weak",
            stdout=StringIO(),
        )
    with pytest.raises(CommandError, match="Could not load the rehearsal roster"):
        call_command(
            "seed_marucon_rehearsal",
            roster_file=tmp_path / "missing.html",
            stdout=StringIO(),
        )

    AccountFactory()
    with pytest.raises(CommandError, match="requires a clean account table"):
        call_command(
            "seed_marucon_rehearsal",
            roster_file=roster_path,
            stdout=StringIO(),
        )


def test_marucon_rehearsal_requires_a_distinct_executive_chair(
    tmp_path: Path,
) -> None:
    roster_path = tmp_path / "no-chair.html"
    roster_path.write_text(
        """
        <main>
          <h2>Executive Board</h2>
          <h3>DirectorFox</h3><p>Director</p>
          <h2>Helpers</h2>
          <h3>HelperHare</h3><p>Volunteer</p>
        </main>
        """,
        encoding="utf-8",
    )

    with pytest.raises(CommandError, match="needs a distinct Executive Board chair"):
        call_command(
            "seed_marucon_rehearsal",
            roster_file=roster_path,
            stdout=StringIO(),
        )
