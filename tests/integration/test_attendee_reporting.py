"""Purpose-limited attendee reporting and badge export."""

import csv
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.events.models import EventEdition
from maru.identity.models import Account

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]

DEMO_PASSWORD = "Synthetic-reporting-password-2026!"


def test_demo_staff_can_report_filter_and_export_without_private_fields() -> None:
    call_command("seed_demo_data", password=DEMO_PASSWORD, verbosity=0)
    chair = Account.objects.get(email="danube.convention-chair@demo.maru.invalid")
    edition = EventEdition.objects.get(slug="danube-furry-convention-2026")
    client = APIClient()
    client.force_login(chair)
    report_url = reverse(
        "api-registration-attendee-report",
        args=(edition.organization_id, edition.id),
    )

    response = client.get(report_url)

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["coming"] >= 3
    assert payload["summary"]["countries"] >= 2
    assert payload["summary"]["volunteers"] >= 1
    assert {item["code"] for item in payload["summary"]["level_breakdown"]} >= {
        "guest",
        "super_sponsor",
        "volunteer",
    }
    assert all(
        row["registration_state"] in {"confirmed", "checked_in"}
        for row in payload["results"]
    )
    assert all("amount_minor" not in row for row in payload["results"])
    assert all("address_line_1" not in row for row in payload["results"])

    country = next(
        item["country_code"]
        for item in payload["summary"]["country_breakdown"]
        if item["country_code"] != "unknown"
    )
    filtered = client.get(report_url, {"country_code": country})
    assert filtered.status_code == 200
    assert filtered.json()["results"]
    assert {row["country_code"] for row in filtered.json()["results"]} == {country}

    export_url = reverse(
        "api-registration-badge-export",
        args=(edition.organization_id, edition.id),
    )
    export = client.get(export_url, {"country_code": country})
    assert export.status_code == 200
    assert export["Content-Type"].startswith("text/csv")
    decoded = export.content.decode("utf-8-sig")
    rows = list(csv.DictReader(StringIO(decoded)))
    assert rows
    assert {row["registration_country_code"] for row in rows} == {country}
    assert "real_name" not in rows[0]
    assert "amount_minor" not in rows[0]
    assert AuditEvent.objects.filter(
        principal_id=chair.id,
        operation="registration.badge_data.export",
        outcome=AuditEvent.Outcome.ALLOW,
    ).exists()


def test_attendee_report_denies_unassigned_and_cross_tenant_access() -> None:
    call_command("seed_demo_data", password=DEMO_PASSWORD, verbosity=0)
    attendee = Account.objects.get(email="danube.first-time-attendee@demo.maru.invalid")
    danube_edition = EventEdition.objects.get(slug="danube-furry-convention-2026")
    aurora_edition = EventEdition.objects.get(slug="aurora-tails-2026")
    danube_chair = Account.objects.get(
        email="danube.convention-chair@demo.maru.invalid"
    )
    client = APIClient()

    client.force_login(attendee)
    own_edition = client.get(
        reverse(
            "api-registration-attendee-report",
            args=(danube_edition.organization_id, danube_edition.id),
        )
    )
    assert own_edition.status_code == 403
    assert "count" not in own_edition.json()

    client.force_login(danube_chair)
    other_tenant = client.get(
        reverse(
            "api-registration-attendee-report",
            args=(aurora_edition.organization_id, aurora_edition.id),
        )
    )
    assert other_tenant.status_code == 403
    assert "count" not in other_tenant.json()
