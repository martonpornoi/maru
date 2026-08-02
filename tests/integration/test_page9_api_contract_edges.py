"""Boundary-focused coverage for strict Page 9 API failure contracts."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.policy import decide
from maru.events.models import EventEdition
from maru.workforce.models import Department, EditionStructureControl
from maru.workforce.structure_templates import AWOOSTRIA_REFERENCE_V1
from tests.factories import AccountFactory, EventEditionFactory

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _administrator() -> object:
    return AccountFactory(is_staff=True, is_superuser=True)


def _client(account: object | None = None) -> APIClient:
    client = APIClient()
    if account is not None:
        client.force_authenticate(account)
    return client


def _structure_url(edition: EventEdition) -> str:
    return (
        f"/api/v1/organizations/{edition.organization_id}/"
        f"editions/{edition.id}/workforce/structure"
    )


def _collection_url(edition: EventEdition) -> str:
    return (
        f"/api/v1/organizations/{edition.organization_id}/"
        f"editions/{edition.id}/workforce/departments"
    )


def _template_url(edition: EventEdition) -> str:
    return (
        f"/api/v1/organizations/{edition.organization_id}/"
        f"editions/{edition.id}/workforce/structure/template-applications"
    )


def _department_url(edition: EventEdition, department_id: UUID) -> str:
    return f"{_collection_url(edition)}/{department_id}"


def _create_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Synthetic Operations",
        "description": "Coordinates synthetic operations.",
        "parent_department_id": None,
        "display_order": 10,
        "expected_version": 0,
        "reason": "Establish the synthetic structure.",
    }
    payload.update(overrides)
    return payload


def _template_payload(edition: EventEdition) -> dict[str, object]:
    return {
        "template": AWOOSTRIA_REFERENCE_V1.identifier,
        "expected_version": 0,
        "confirmation_name": edition.name,
        "reason": "Use the reviewed reference structure.",
    }


@pytest.mark.parametrize(
    ("failure_target", "failure"),
    [
        (
            "maru.workforce.api.resolve_edition_target",
            DatabaseError("Private target-resolution detail."),
        ),
        (
            "maru.workforce.api.decide",
            RuntimeError("Private policy-engine detail."),
        ),
    ],
)
def test_mutation_authorization_dependency_failures_precede_header_and_body_parsing(
    failure_target: str,
    failure: Exception,
) -> None:
    edition = EventEditionFactory(name="Private dependency edition")

    with patch(failure_target, side_effect=failure):
        response = _client(_administrator()).generic(
            "POST",
            _collection_url(edition),
            data=b'{"malformed"',
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="not-a-uuid",
        )

    assert response.status_code == 503
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert response.json()["code"] == "service_unavailable"
    rendered = response.content.decode()
    assert "Private dependency edition" not in rendered
    assert "Private target-resolution" not in rendered
    assert "Private policy-engine" not in rendered
    assert not Department.objects.exists()


def test_mutation_denies_when_the_edition_disappears_after_authorization() -> None:
    edition = EventEditionFactory()
    real_decide = decide
    decision_count = 0

    def decide_then_remove_edition(*args: Any, **kwargs: Any):
        nonlocal decision_count
        result = real_decide(*args, **kwargs)
        decision_count += 1
        if decision_count == 2:
            EventEdition.objects.filter(pk=edition.id).delete()
        return result

    with patch("maru.workforce.api.decide", side_effect=decide_then_remove_edition):
        response = _client(_administrator()).post(
            _collection_url(edition),
            _create_payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )

    assert decision_count == 2
    assert response.status_code == 403
    assert response.json()["code"] == "structure_authorization_denied"
    assert not Department.objects.exists()
    assert not EditionStructureControl.objects.exists()


def test_read_denies_when_the_edition_disappears_between_policy_and_projection() -> (
    None
):
    edition = EventEditionFactory(name="Private disappearing edition")

    with (
        patch("maru.workforce.api.EventEdition.objects.select_related") as selected,
        patch("maru.workforce.api.append_structure_read_audit") as audit,
    ):
        selected.return_value.only.return_value.get.side_effect = (
            EventEdition.DoesNotExist
        )
        response = _client(_administrator()).get(_structure_url(edition))

    assert response.status_code == 403
    assert response.json()["code"] == "target_unavailable"
    assert "Private disappearing edition" not in response.content.decode()
    audit.assert_not_called()


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_field"),
    [
        (
            ValidationError(
                {
                    "name": ValidationError(
                        "Choose a different Department name.",
                        code="structure_name_conflict",
                    )
                }
            ),
            "structure_name_conflict",
            "name",
        ),
        (
            ValidationError({"description": ["Review the Department description."]}),
            "structure_input_invalid",
            "description",
        ),
    ],
)
def test_safe_command_validation_errors_remain_field_local_400s(
    error: ValidationError,
    expected_code: str,
    expected_field: str,
) -> None:
    edition = EventEditionFactory()

    with patch("maru.workforce.api.create_department", side_effect=error):
        response = _client(_administrator()).post(
            _collection_url(edition),
            _create_payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )

    assert response.status_code == 400
    assert response.json()["code"] == expected_code
    assert set(response.json()["errors"]) == {expected_field}
    assert not Department.objects.exists()


@pytest.mark.parametrize(
    "error",
    [
        ValidationError(
            "Private non-field command invariant.",
            code="private_internal_invariant",
        ),
        ValidationError(
            {
                "name": ValidationError(
                    "Private safe-looking name detail.",
                    code="private_name_code",
                ),
                "organization_id": ValidationError(
                    "Private server-owned scope detail.",
                    code="private_scope_code",
                ),
            }
        ),
    ],
)
def test_internal_or_mixed_command_validation_errors_fail_name_free(
    error: ValidationError,
) -> None:
    edition = EventEditionFactory(name="Private invariant edition")

    with patch("maru.workforce.api.create_department", side_effect=error):
        response = _client(_administrator()).post(
            _collection_url(edition),
            _create_payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )

    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"
    rendered = response.content.decode()
    assert "Private invariant edition" not in rendered
    assert "Private non-field" not in rendered
    assert "Private safe-looking" not in rendered
    assert "Private server-owned" not in rendered
    assert not Department.objects.exists()


@pytest.mark.parametrize(
    "body",
    [
        pytest.param([], id="empty-array"),
        pytest.param([{"name": "Array item"}], id="array"),
        pytest.param("text", id="string"),
        pytest.param(42, id="integer"),
        pytest.param(False, id="boolean"),
        pytest.param(None, id="null"),
    ],
)
def test_create_rejects_every_non_object_json_body(body: object) -> None:
    edition = EventEditionFactory()
    response = _client(_administrator()).generic(
        "POST",
        _collection_url(edition),
        data=json.dumps(body).encode(),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 400
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert not Department.objects.exists()
    assert not EditionStructureControl.objects.exists()


def _request_mutation_with_unknown_query(
    *,
    client: APIClient,
    edition: EventEdition,
    operation: str,
):
    department_id = uuid4()
    if operation == "template":
        return client.post(
            f"{_template_url(edition)}?unexpected=1",
            _template_payload(edition),
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )
    if operation == "create":
        return client.post(
            f"{_collection_url(edition)}?unexpected=1",
            _create_payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )
    if operation == "update":
        return client.put(
            f"{_department_url(edition, department_id)}?unexpected=1",
            _create_payload(expected_version=1),
            format="json",
        )
    if operation == "retire":
        return client.post(
            f"{_department_url(edition, department_id)}/retire?unexpected=1",
            {"expected_version": 1, "reason": "Retire the Department."},
            format="json",
        )
    return client.delete(
        f"{_department_url(edition, department_id)}?unexpected=1",
        {
            "expected_version": 1,
            "confirmation_name": "Synthetic Operations",
            "reason": "Delete the unused Department.",
        },
        format="json",
    )


@pytest.mark.parametrize(
    "operation",
    ["template", "create", "update", "retire", "delete"],
)
def test_every_mutation_adapter_rejects_unknown_query_input(operation: str) -> None:
    edition = EventEditionFactory()

    response = _request_mutation_with_unknown_query(
        client=_client(_administrator()),
        edition=edition,
        operation=operation,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "unknown_input_field"
    assert "private" in response.headers["Cache-Control"]
    assert "no-store" in response.headers["Cache-Control"]
    assert not Department.objects.exists()
    assert not EditionStructureControl.objects.exists()


def test_oversized_nonblank_idempotency_header_is_invalid_not_missing() -> None:
    edition = EventEditionFactory()
    response = _client(_administrator()).post(
        _collection_url(edition),
        _create_payload(),
        format="json",
        HTTP_IDEMPOTENCY_KEY="x" * 65,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_idempotency_key"
    assert not Department.objects.exists()


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_structure_read_route_allows_only_get_head_and_options(method: str) -> None:
    edition = EventEditionFactory()
    client = _client(_administrator())

    with patch("maru.workforce.api.append_structure_read_audit") as audit:
        response = client.generic(
            method,
            _structure_url(edition),
            data=b"{}",
            content_type="application/json",
        )

    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"
    assert set(response.headers["Allow"].replace(" ", "").split(",")) == {
        "GET",
        "HEAD",
        "OPTIONS",
    }
    assert "no-store" in response.headers["Cache-Control"]
    audit.assert_not_called()
    assert not AuditEvent.objects.filter(operation="workforce.structure.read").exists()


def test_structure_head_rejects_query_input_before_audit_or_projection() -> None:
    edition = EventEditionFactory(name="Private forged-query edition")

    with patch("maru.workforce.api.append_structure_read_audit") as audit:
        response = _client(_administrator()).head(
            f"{_structure_url(edition)}?forged=true"
        )

    assert response.status_code == 400
    assert response.content == b""
    assert "private" in response.headers["Cache-Control"]
    assert "no-store" in response.headers["Cache-Control"]
    audit.assert_not_called()
    assert not AuditEvent.objects.filter(operation="workforce.structure.read").exists()
