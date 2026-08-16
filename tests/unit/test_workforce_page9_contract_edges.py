"""Focused edge contracts for Page 9 forms, serializers, schema, and audit."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from django import forms
from django.core.exceptions import ValidationError as DjangoValidationError

from maru.authorization.policy import PolicyDecision
from maru.identity.models import Account
from maru.workforce.api import WorkforceDepartmentDetailView
from maru.workforce.forms import DepartmentCreationForm
from maru.workforce.serializers import (
    WorkforceDepartmentCreateSerializer,
    WorkforceStructureProjectionSerializer,
    WorkforceStructureTemplateApplySerializer,
)
from maru.workforce.structure_audit import append_structure_read_audit
from maru.workforce.structure_templates import AWOOSTRIA_REFERENCE_V1


def _form_data(**overrides: str) -> dict[str, str]:
    data = {
        "name": "Registration",
        "description": "Attendee intake and badge support.",
        "parent_department_id": "",
        "expected_version": "0",
        "reason": "Establish the operational structure.",
        "retry_key": str(uuid4()),
    }
    data.update(overrides)
    return data


def _department_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Registration",
        "description": "Attendee intake and badge support.",
        "parent_department_id": None,
        "display_order": 20,
        "expected_version": 0,
        "reason": "Establish the operational structure.",
    }
    payload.update(overrides)
    return payload


def _allowed_decision(*, obligations: frozenset[str] = frozenset()) -> PolicyDecision:
    return PolicyDecision(
        allowed=True,
        fields=frozenset(),
        obligations=obligations,
        reason_code="platform_oversight",
    )


def test_creation_form_reports_a_required_missing_integer_without_coercion() -> None:
    data = _form_data()
    del data["expected_version"]

    form = DepartmentCreationForm(
        data,
        parent_choices=(),
        expected_version=0,
    )

    assert not form.is_valid()
    assert form.errors.as_data()["expected_version"][0].code == "required"


def test_form_hides_a_domain_error_attached_to_the_wrong_field() -> None:
    wrong_shape = forms.ValidationError(
        {
            "reason": forms.ValidationError(
                "Private mismatched domain detail.",
                code="private_mismatched_code",
            )
        }
    )

    with patch(
        "maru.workforce.forms.normalize_department_name",
        side_effect=wrong_shape,
    ):
        form = DepartmentCreationForm(
            _form_data(),
            parent_choices=(),
            expected_version=0,
        )
        is_valid = form.is_valid()

    assert not is_valid
    error = form.errors.as_data()["name"][0]
    assert error.code == "structure_field_invalid"
    assert "Review this value" in error.message
    assert "Private mismatched" not in str(form.errors)


@pytest.mark.parametrize("field_name", ["name", "description", "reason"])
def test_department_serializer_preserves_domain_control_character_codes(
    field_name: str,
) -> None:
    serializer = WorkforceDepartmentCreateSerializer(
        data=_department_payload(**{field_name: "Unsafe\u0000value"})
    )

    assert not serializer.is_valid()
    error = serializer.errors[field_name][0]
    assert error.code == "structure_control_character"
    assert "Control characters" in str(error)


@pytest.mark.parametrize(
    ("domain_error", "expected_code"),
    [
        (
            DjangoValidationError(
                "A plain domain validation error.",
                code="plain_description_error",
            ),
            "plain_description_error",
        ),
        (
            DjangoValidationError("A plain uncoded validation error."),
            "structure_description_invalid",
        ),
    ],
)
def test_serializer_translates_plain_domain_validation_errors(
    domain_error: DjangoValidationError,
    expected_code: str,
) -> None:
    with patch(
        "maru.workforce.serializers.normalize_department_description",
        side_effect=domain_error,
    ):
        serializer = WorkforceDepartmentCreateSerializer(data=_department_payload())
        assert not serializer.is_valid()

    assert serializer.errors["description"][0].code == expected_code
    assert "plain" in str(serializer.errors["description"][0]).lower()


@pytest.mark.parametrize(
    ("parent_value", "expected_code"),
    [
        (42, "invalid"),
        ("not-a-uuid", "invalid"),
        ("A7CBF0A8-B0B1-4991-A650-6DD8E12E8810", "non_canonical"),
        ("{a7cbf0a8-b0b1-4991-a650-6dd8e12e8810}", "non_canonical"),
    ],
)
def test_department_serializer_rejects_noncanonical_parent_identifiers(
    parent_value: object,
    expected_code: str,
) -> None:
    serializer = WorkforceDepartmentCreateSerializer(
        data=_department_payload(parent_department_id=parent_value)
    )

    assert not serializer.is_valid()
    assert serializer.errors["parent_department_id"][0].code == expected_code


@pytest.mark.parametrize(
    "template_value",
    [1, True, [AWOOSTRIA_REFERENCE_V1.identifier]],
)
def test_template_serializer_never_coerces_non_string_choices(
    template_value: object,
) -> None:
    serializer = WorkforceStructureTemplateApplySerializer(
        data={
            "template": template_value,
            "expected_version": 0,
            "confirmation_name": "Synthetic Edition",
            "reason": "Use the reviewed structure.",
        }
    )

    assert not serializer.is_valid()
    assert serializer.errors["template"][0].code == "invalid_choice"


@pytest.mark.parametrize("source", [{}, {"kind": "future_source"}])
def test_projection_serializer_minimizes_unknown_source_discriminators(
    source: dict[str, object],
) -> None:
    serializer = WorkforceStructureProjectionSerializer(
        {
            "state": "complete",
            "aggregate_version": 0,
            "source": source,
            "departments": [],
        }
    )

    assert serializer.data["source"] == {}


def test_delete_schema_handles_absent_and_optional_media_schemas() -> None:
    schema = type(WorkforceDepartmentDetailView.schema)()
    schema.method = "DELETE"

    with patch.object(
        schema,
        "_get_request_for_media_type",
        return_value=(None, False),
    ):
        assert schema._get_request_body() is None

    with patch.object(
        schema,
        "_get_request_for_media_type",
        return_value=({"type": "object"}, False),
    ):
        assert schema._get_request_body() == {
            "content": {"application/json": {"schema": {"type": "object"}}}
        }


@pytest.mark.parametrize("http_method", ["GET", "HEAD", "POST"])
def test_structure_read_audit_accepts_only_the_exact_supported_methods(
    http_method: str,
) -> None:
    actor = Account(id=uuid4(), email="synthetic-auditor@example.invalid")
    organization_id = uuid4()
    edition_id = uuid4()
    correlation_id = uuid4()
    occurred_at = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    sentinel = object()

    with patch(
        "maru.workforce.structure_audit.append_audit",
        return_value=sentinel,
    ) as append:
        result = append_structure_read_audit(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            decision=_allowed_decision(obligations=frozenset({"existing"})),
            correlation_id=correlation_id,
            route_name="workforce-structure",
            http_method=http_method,
            source_channel="api",
            occurred_at=occurred_at,
        )

    assert result is sentinel
    record = append.call_args.args[0]
    assert record.safe_metadata["http_method"] == http_method
    assert record.obligations == ("audit_sensitive_read", "existing")
    assert append.call_args.kwargs == {"occurred_at": occurred_at}


def test_structure_read_audit_rejects_a_denied_policy_decision() -> None:
    actor = Account(id=uuid4(), email="synthetic-auditor@example.invalid")
    denied = PolicyDecision(
        allowed=False,
        fields=frozenset(),
        obligations=frozenset(),
        reason_code="authority_denied",
    )

    with (
        patch("maru.workforce.structure_audit.append_audit") as append,
        pytest.raises(ValueError, match="denied structure decision"),
    ):
        append_structure_read_audit(
            actor=actor,
            organization_id=uuid4(),
            edition_id=uuid4(),
            decision=denied,
            correlation_id=uuid4(),
            route_name="workforce-structure",
            http_method="GET",
            source_channel="api",
            occurred_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
        )

    append.assert_not_called()


@pytest.mark.parametrize("http_method", ["get", "PUT", "DELETE", "OPTIONS"])
def test_structure_read_audit_rejects_unsupported_or_noncanonical_methods(
    http_method: str,
) -> None:
    actor = Account(id=uuid4(), email="synthetic-auditor@example.invalid")

    with (
        patch("maru.workforce.structure_audit.append_audit") as append,
        pytest.raises(ValueError, match="exact supported structure audit HTTP method"),
    ):
        append_structure_read_audit(
            actor=actor,
            organization_id=uuid4(),
            edition_id=uuid4(),
            decision=_allowed_decision(),
            correlation_id=uuid4(),
            route_name="workforce-structure",
            http_method=http_method,
            source_channel="api",
            occurred_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
        )

    append.assert_not_called()
