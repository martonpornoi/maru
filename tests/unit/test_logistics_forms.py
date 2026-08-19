from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.http import QueryDict

from maru.core.forms import StrictBase10IntegerField, StrictInputForm
from maru.logistics.forms import CanonicalLocalDateTimeField, EquipmentOfferForm
from maru.logistics.models import MAX_LOGISTICS_REASON_LENGTH
from maru.logistics.staff_forms import (
    CommandForm,
    ManifestStateForm,
    RestrictedContactReadForm,
)


def test_logistics_forms_share_closed_input_contract() -> None:
    assert issubclass(CommandForm, StrictInputForm)
    assert issubclass(EquipmentOfferForm, StrictInputForm)
    assert issubclass(RestrictedContactReadForm, StrictInputForm)


def test_command_form_rejects_unknown_and_duplicate_values() -> None:
    data = QueryDict(mutable=True)
    data.update(
        {
            "idempotency_key": str(uuid4()),
            "reason": "Register one governed Logistics record.",
            "unexpected": "must not be ignored",
        }
    )
    data.appendlist("reason", "duplicate")

    form = CommandForm(data)

    assert form.is_valid() is False
    assert {error.code for error in form.non_field_errors().as_data()} == {
        "invalid_input_cardinality"
    }

    unknown = CommandForm(
        {
            "idempotency_key": str(uuid4()),
            "reason": "Register one governed Logistics record.",
            "unexpected": "must not be ignored",
        }
    )
    assert unknown.is_valid() is False
    assert unknown.non_field_errors().as_data()[0].code == "unknown_input_field"


@pytest.mark.parametrize(
    "alias",
    [
        "123E4567-E89B-42D3-A456-426614174000",
        "123e4567e89b42d3a456426614174000",
        "{123e4567-e89b-42d3-a456-426614174000}",
        " 123e4567-e89b-42d3-a456-426614174000",
    ],
)
def test_logistics_command_rejects_noncanonical_uuid_aliases(alias: str) -> None:
    form = CommandForm(
        {
            "idempotency_key": alias,
            "reason": "Register one governed Logistics record.",
        }
    )

    assert form.is_valid() is False
    assert form.errors.as_data()["idempotency_key"][0].code == "invalid"


@pytest.mark.parametrize("alias", ["+1", "01", " 1", "1 ", "1.0", "true"])
def test_logistics_versions_reject_noncanonical_integer_aliases(alias: str) -> None:
    form = ManifestStateForm(
        {
            "idempotency_key": str(uuid4()),
            "manifest_id": str(uuid4()),
            "expected_version": alias,
            "action": "seal",
            "reason": "Seal the checked manifest.",
        }
    )

    assert form.is_valid() is False
    assert form.errors.as_data()["expected_version"][0].code == "invalid"
    assert isinstance(
        ManifestStateForm.base_fields["expected_version"],
        StrictBase10IntegerField,
    )


def test_restricted_contact_purpose_is_closed() -> None:
    form = RestrictedContactReadForm(
        {
            "address_id": str(uuid4()),
            "purpose": "pickup",
            "access_purpose": "free text is forbidden",
        }
    )

    assert form.is_valid() is False
    assert form.errors.as_data()["access_purpose"][0].code == "invalid_choice"


@pytest.mark.parametrize(
    ("local_value", "expected_code"),
    [
        ("2026-03-29T02:30", "nonexistent"),
        ("2026-10-25T02:30", "ambiguous"),
    ],
)
def test_logistics_local_time_rejects_dst_gaps_and_folds(
    local_value: str,
    expected_code: str,
) -> None:
    field = CanonicalLocalDateTimeField(zone_name="Europe/Budapest")

    with pytest.raises(ValidationError) as error:
        field.clean(local_value)

    assert error.value.code == expected_code
    parsed = field.clean("2026-08-09T12:00")
    assert parsed is not None
    assert parsed.utcoffset() == timedelta(hours=2)


def test_offer_reason_uses_domain_length_limit() -> None:
    assert EquipmentOfferForm.base_fields["reason"].max_length == (
        MAX_LOGISTICS_REASON_LENGTH
    )


def test_logistics_templates_are_same_shell_and_free_of_mojibake() -> None:
    template_root = (
        Path(__file__).parents[2]
        / "src"
        / "maru"
        / "logistics"
        / "templates"
        / "logistics"
    )
    for template_path in template_root.glob("*.html"):
        source = template_path.read_text(encoding="utf-8")
        assert '{% extends "admin/base_site.html" %}' in source
        assert "\ufffd" not in source
        assert "\u00c2" not in source
        assert "\u00e2" not in source


def test_personal_offer_templates_have_one_page_landmark_and_heading() -> None:
    template_root = (
        Path(__file__).parents[2]
        / "src"
        / "maru"
        / "logistics"
        / "templates"
        / "logistics"
    )

    for template_name in ("my_offer_index.html", "my_offers.html"):
        source = (template_root / template_name).read_text(encoding="utf-8")
        assert "{% block content_title %}{% endblock %}" in source
        assert '<div id="content-main" class="maru-management-page">' in source
        assert "<main" not in source
        assert source.count("<h1>My equipment offers</h1>") == 1


def test_management_templates_have_one_page_landmark_and_heading() -> None:
    template_root = (
        Path(__file__).parents[2]
        / "src"
        / "maru"
        / "logistics"
        / "templates"
        / "logistics"
    )

    for template_name in (
        "workspace.html",
        "stage_receiving.html",
        "manifest_detail.html",
        "restricted_contact.html",
    ):
        source = (template_root / template_name).read_text(encoding="utf-8")
        assert "{% block content_title %}{% endblock %}" in source
        assert '<div id="content-main" class="maru-management-page">' in source
        assert "<main" not in source
        assert source.count("<h1") == 1
