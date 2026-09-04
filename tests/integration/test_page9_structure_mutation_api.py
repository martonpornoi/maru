"""Strict HTTP contract for Page 9a.1 structure mutations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.effects.models import DomainEvent, OutboxMessage
from maru.organizations.models import Organization
from maru.workforce.models import (
    Department,
    EditionStructureCommandReceipt,
    EditionStructureControl,
)
from maru.workforce.structure_commands import (
    StructureCommandError,
    StructureDependencyUnavailableError,
    StructureLimitConflictError,
    StructureStateConflictError,
)
from maru.workforce.structure_templates import MARUCON_REFERENCE_V1
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory

if TYPE_CHECKING:
    from maru.events.models import EventEdition

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _administrator() -> object:
    return AccountFactory(is_staff=True, is_superuser=True)


def _client(account: object | None = None) -> APIClient:
    client = APIClient()
    if account is not None:
        client.force_authenticate(account)
    return client


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


def _retire_url(edition: EventEdition, department_id: UUID) -> str:
    return f"{_department_url(edition, department_id)}/retire"


def _create_payload(*, expected_version: object = 0, **changes: object):
    payload: dict[str, object] = {
        "name": "  Synthetic   Operations  ",
        "description": "  Coordinates synthetic operations.  ",
        "parent_department_id": None,
        "display_order": 10,
        "expected_version": expected_version,
        "reason": "  Establish the synthetic structure.  ",
    }
    payload.update(changes)
    return payload


def _template_payload(edition: EventEdition, **changes: object):
    payload: dict[str, object] = {
        "template": MARUCON_REFERENCE_V1.identifier,
        "expected_version": 0,
        "confirmation_name": edition.name,
        "reason": "Use the reviewed reference structure.",
    }
    payload.update(changes)
    return payload


def _post_create(
    *,
    client: APIClient,
    edition: EventEdition,
    retry_key: UUID | None = None,
    expected_version: int = 0,
    name: str = "Synthetic Operations",
    parent_department_id: UUID | None = None,
):
    return client.post(
        _collection_url(edition),
        _create_payload(
            name=name,
            parent_department_id=(
                str(parent_department_id) if parent_department_id else None
            ),
            expected_version=expected_version,
        ),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(retry_key or uuid4()),
    )


def _problem_shape(response: object) -> tuple[object, object, object]:
    body = response.json()  # type: ignore[attr-defined]
    return body["code"], body["detail"], body.get("errors")


def test_template_application_returns_minimized_201_then_byte_equivalent_200() -> None:
    actor = _administrator()
    edition = EventEditionFactory(name="Synthetic Reference Edition")
    client = _client(actor)
    key = uuid4()
    payload = _template_payload(edition)

    created = client.post(
        _template_url(edition),
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(key),
    )
    replayed = client.post(
        _template_url(edition),
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(key),
    )

    assert created.status_code == 201
    assert replayed.status_code == 200
    assert "private" in created.headers["Cache-Control"]
    assert "no-store" in created.headers["Cache-Control"]
    assert "no-store" in replayed.headers["Cache-Control"]
    assert replayed.content == created.content
    assert created.json() == {"aggregate_version": 1}
    assert Department.objects.filter(edition=edition).count() == 22
    assert EditionStructureControl.objects.get(edition=edition).aggregate_version == 1
    assert EditionStructureCommandReceipt.objects.filter(edition=edition).count() == 1
    assert (
        AuditEvent.objects.filter(operation="workforce.structure.change").count() == 1
    )
    assert (
        DomainEvent.objects.filter(event_name="workforce.structure.changed.v1").count()
        == 1
    )
    assert OutboxMessage.objects.count() == 1


def test_create_update_retire_and_delete_use_complete_minimized_results() -> None:
    actor = _administrator()
    edition = EventEditionFactory()
    client = _client(actor)
    create_key = uuid4()

    created = _post_create(client=client, edition=edition, retry_key=create_key)
    replayed = _post_create(client=client, edition=edition, retry_key=create_key)

    assert created.status_code == 201
    assert replayed.status_code == 200
    assert replayed.content == created.content
    assert set(created.json()) == {"department_id", "aggregate_version"}
    assert created.json()["aggregate_version"] == 1
    department_id = UUID(created.json()["department_id"])
    department = Department.objects.get(pk=department_id)
    assert department.name == "Synthetic Operations"
    assert department.description == "Coordinates synthetic operations."

    updated = client.put(
        _department_url(edition, department_id),
        _create_payload(
            name="  Event   Operations ",
            description="Coordinates the updated synthetic operation.",
            display_order=20,
            expected_version=1,
            reason="Replace every editable property.",
        ),
        format="json",
    )
    assert updated.status_code == 200
    assert updated.json() == {
        "department_id": str(department_id),
        "aggregate_version": 2,
    }

    evidence_counts = (
        EditionStructureCommandReceipt.objects.count(),
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )
    noop = client.put(
        _department_url(edition, department_id),
        _create_payload(
            name=" Event Operations ",
            description="Coordinates the updated synthetic operation.",
            display_order=20,
            expected_version=2,
            reason="Confirm the normalized record is unchanged.",
        ),
        format="json",
    )
    assert noop.status_code == 200
    assert noop.json() == {
        "department_id": str(department_id),
        "aggregate_version": 2,
    }
    assert evidence_counts == (
        EditionStructureCommandReceipt.objects.count(),
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )

    temporary = _post_create(
        client=client,
        edition=edition,
        expected_version=2,
        name="Temporary Department",
    )
    assert temporary.status_code == 201
    temporary_id = UUID(temporary.json()["department_id"])

    deleted = client.delete(
        _department_url(edition, temporary_id),
        {
            "expected_version": 3,
            "confirmation_name": "Temporary Department",
            "reason": "Remove the unused synthetic leaf.",
        },
        format="json",
    )
    assert deleted.status_code == 200
    assert deleted.json() == {
        "department_id": str(temporary_id),
        "aggregate_version": 4,
    }
    assert not Department.objects.filter(pk=temporary_id).exists()

    retired = client.post(
        _retire_url(edition, department_id),
        {
            "expected_version": 4,
            "reason": "Retain the completed Department as history.",
        },
        format="json",
    )
    assert retired.status_code == 200
    assert retired.json() == {
        "department_id": str(department_id),
        "aggregate_version": 5,
    }
    assert Department.objects.get(pk=department_id).retired_at is not None


@pytest.mark.parametrize(
    "granted_capability",
    [None, "workforce.view_structure", "workforce.manage_structure"],
)
def test_missing_either_capability_denies_before_header_and_body_parsing(
    granted_capability: str | None,
) -> None:
    edition = EventEditionFactory()
    account = AccountFactory()
    if granted_capability is not None:
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            principal=account,
            capability_code=granted_capability,
        )
    response = _client(account).generic(
        "POST",
        _collection_url(edition),
        data=b'{"malformed"',
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="not-a-uuid",
    )

    assert response.status_code == 403
    assert response.json()["code"] == "structure_authorization_denied"
    assert response.json()["detail"] == "The requested structure is unavailable."
    assert not Department.objects.exists()


def test_anonymous_inactive_unknown_and_mismatched_routes_share_safe_403() -> None:
    edition = EventEditionFactory()
    administrator = _administrator()
    inactive = AccountFactory(is_active=False)
    malformed = b'{"private_name":"Hidden tenant"'
    cases = (
        _client().generic(
            "POST",
            _collection_url(edition),
            data=malformed,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="invalid",
        ),
        _client(inactive).generic(
            "POST",
            _collection_url(edition),
            data=malformed,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="invalid",
        ),
        _client(administrator).generic(
            "POST",
            (
                f"/api/v1/organizations/{uuid4()}/editions/{uuid4()}/"
                "workforce/departments"
            ),
            data=malformed,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="invalid",
        ),
        _client(administrator).generic(
            "POST",
            (
                f"/api/v1/organizations/{uuid4()}/editions/{edition.id}/"
                "workforce/departments"
            ),
            data=malformed,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="invalid",
        ),
    )

    for response in cases:
        assert response.status_code == 403
        assert response.headers["Content-Type"].startswith("application/problem+json")
        assert response.json()["code"] == "structure_authorization_denied"
        assert response.json()["detail"] == "The requested structure is unavailable."
        assert "Hidden tenant" not in response.content.decode()
    assert not Department.objects.exists()


def test_malformed_basic_authentication_returns_a_stable_name_free_problem() -> None:
    edition = EventEditionFactory()
    response = _client().generic(
        "POST",
        _collection_url(edition),
        data=b'{"private_name":"Hidden tenant"}',
        content_type="application/json",
        HTTP_AUTHORIZATION="Basic !!!",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 403
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert _problem_shape(response) == (
        "authentication_failed",
        "Invalid basic header. Credentials not correctly base64 encoded.",
        None,
    )
    assert "Hidden tenant" not in response.content.decode()
    assert not Department.objects.exists()


def test_locked_command_recheck_turns_revoked_authority_into_uniform_403() -> None:
    edition = EventEditionFactory()
    account = AccountFactory()
    for capability_code in (
        "workforce.view_structure",
        "workforce.manage_structure",
    ):
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            principal=account,
            capability_code=capability_code,
        )
    revoked = PolicyDecision(
        allowed=False,
        fields=frozenset(),
        obligations=frozenset(),
        reason_code="authority_revoked",
    )

    # The API module retains its real preliminary policy function. Patching
    # only the command module models authority disappearing before the command's
    # independent pre-lock/locked recheck.
    with patch(
        "maru.workforce.structure_commands.decide",
        return_value=revoked,
    ) as locked_decide:
        response = _client(account).post(
            _collection_url(edition),
            _create_payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )

    assert response.status_code == 403
    assert locked_decide.called
    assert response.json()["code"] == "structure_authorization_denied"
    assert response.json()["detail"] == "The requested structure is unavailable."
    assert not Department.objects.exists()
    assert not EditionStructureControl.objects.exists()
    assert not EditionStructureCommandReceipt.objects.exists()
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


@pytest.mark.parametrize(
    ("header", "expected_code"),
    [
        (None, "missing_idempotency_key"),
        ("   ", "missing_idempotency_key"),
        ("not-a-uuid", "invalid_idempotency_key"),
        ("A6A8A503-95A9-4F38-8767-1BB24C84B406", "invalid_idempotency_key"),
        ("{a6a8a503-95a9-4f38-8767-1bb24c84b406}", "invalid_idempotency_key"),
        (
            "a6a8a503-95a9-4f38-8767-1bb24c84b406,b6a8a503-95a9-4f38-8767-1bb24c84b406",
            "invalid_idempotency_key",
        ),
        (" " * 65, "missing_idempotency_key"),
    ],
)
def test_idempotency_header_is_required_bounded_and_canonical(
    header: str | None,
    expected_code: str,
) -> None:
    edition = EventEditionFactory()
    kwargs = {} if header is None else {"HTTP_IDEMPOTENCY_KEY": header}
    response = _client(_administrator()).post(
        _collection_url(edition),
        _create_payload(),
        format="json",
        **kwargs,
    )

    assert response.status_code == 400
    assert response.json()["code"] == expected_code
    assert "Idempotency-Key" in response.json()["errors"]
    assert not Department.objects.exists()


def test_idempotency_header_precedes_body_parsing_and_allows_surrounding_ows() -> None:
    edition = EventEditionFactory()
    client = _client(_administrator())

    malformed = client.generic(
        "POST",
        _collection_url(edition),
        data=b'{"malformed"',
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="invalid",
    )
    assert malformed.status_code == 400
    assert malformed.json()["code"] == "invalid_idempotency_key"

    key = uuid4()
    accepted = client.post(
        _collection_url(edition),
        _create_payload(),
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"  {key}\t",
    )
    assert accepted.status_code == 201


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_version": "0"},
        {"expected_version": False},
        {"expected_version": 0.0},
        {"display_order": "10"},
        {"display_order": True},
        {"name": 42},
        {"description": False},
        {"reason": 99},
        {"parent_department_id": str(uuid4()).upper()},
    ],
)
def test_json_fields_reject_coercion_and_noncanonical_uuid(
    changes: dict[str, object],
) -> None:
    edition = EventEditionFactory()
    response = _client(_administrator()).post(
        _collection_url(edition),
        _create_payload(**changes),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 400
    assert not Department.objects.exists()
    assert not EditionStructureControl.objects.exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"retry_key": str(uuid4())},
        {"organization_id": str(uuid4())},
        {"actor_id": str(uuid4())},
        {"retired_at": "2030-01-01T00:00:00Z"},
    ],
)
def test_closed_payload_rejects_every_server_owned_or_unknown_field(
    changes: dict[str, object],
) -> None:
    edition = EventEditionFactory()
    response = _client(_administrator()).post(
        _collection_url(edition),
        _create_payload(**changes),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "unknown_input_field"
    assert not Department.objects.exists()


def test_unknown_query_reserved_name_control_character_and_confirmation_are_400() -> (
    None
):
    actor = _administrator()
    edition = EventEditionFactory()
    client = _client(actor)

    unknown_query = client.post(
        f"{_collection_url(edition)}?page=1",
        _create_payload(),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    reserved = client.post(
        _collection_url(edition),
        _create_payload(name="Executive Board"),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    control = client.post(
        _collection_url(edition),
        _create_payload(reason="Unsafe\u0000reason"),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    confirmation = client.post(
        _template_url(edition),
        _template_payload(edition, confirmation_name="Wrong edition"),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert unknown_query.status_code == 400
    assert unknown_query.json()["code"] == "unknown_input_field"
    assert reserved.status_code == 400
    assert reserved.json()["code"] == "structure_executive_board_reserved"
    assert control.status_code == 400
    assert control.json()["code"] == "structure_control_character"
    assert confirmation.status_code == 400
    assert confirmation.json()["code"] == "structure_confirmation_mismatch"
    assert not Department.objects.exists()


def test_unknown_foreign_retired_department_and_parent_targets_share_safe_404() -> None:
    actor = _administrator()
    edition = EventEditionFactory()
    foreign = EventEditionFactory()
    client = _client(actor)
    current = _post_create(client=client, edition=edition, name="Current")
    retired_target = _post_create(
        client=client,
        edition=edition,
        expected_version=1,
        name="Retired target",
    )
    foreign_target = _post_create(
        client=client,
        edition=foreign,
        name="Foreign target",
    )
    current_id = UUID(current.json()["department_id"])
    retired_id = UUID(retired_target.json()["department_id"])
    foreign_id = UUID(foreign_target.json()["department_id"])
    retirement = client.post(
        _retire_url(edition, retired_id),
        {"expected_version": 2, "reason": "Retire the synthetic target."},
        format="json",
    )
    assert retirement.status_code == 200

    update_payload = _create_payload(
        name="Unavailable replacement",
        expected_version=3,
    )
    responses = (
        client.put(
            _department_url(edition, uuid4()),
            update_payload,
            format="json",
        ),
        client.put(
            _department_url(edition, foreign_id),
            update_payload,
            format="json",
        ),
        client.put(
            _department_url(edition, retired_id),
            update_payload,
            format="json",
        ),
        client.post(
            _collection_url(edition),
            _create_payload(
                parent_department_id=str(foreign_id),
                expected_version=3,
            ),
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        ),
        client.post(
            _collection_url(edition),
            _create_payload(
                parent_department_id=str(retired_id),
                expected_version=3,
            ),
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        ),
    )

    for response in responses:
        assert response.status_code == 404
        assert _problem_shape(response) == (
            "structure_department_unavailable",
            "The requested structure is unavailable.",
            None,
        )
        assert "Foreign target" not in response.content.decode()
        assert "Retired target" not in response.content.decode()
    assert Department.objects.get(pk=current_id).retired_at is None
    assert EditionStructureControl.objects.get(edition=edition).aggregate_version == 3


def test_retire_and_delete_hide_unknown_foreign_and_retired_targets_uniformly() -> None:
    actor = _administrator()
    edition = EventEditionFactory()
    foreign = EventEditionFactory()
    client = _client(actor)
    retired = _post_create(
        client=client,
        edition=edition,
        name="Private retired target",
    )
    foreign_target = _post_create(
        client=client,
        edition=foreign,
        name="Private foreign target",
    )
    retired_id = UUID(retired.json()["department_id"])
    foreign_id = UUID(foreign_target.json()["department_id"])
    retired_result = client.post(
        _retire_url(edition, retired_id),
        {"expected_version": 1, "reason": "Retire the synthetic target."},
        format="json",
    )
    assert retired_result.status_code == 200

    target_ids = (uuid4(), foreign_id, retired_id)
    responses = tuple(
        client.post(
            _retire_url(edition, department_id),
            {"expected_version": 2, "reason": "Attempt a protected retirement."},
            format="json",
        )
        for department_id in target_ids
    ) + tuple(
        client.delete(
            _department_url(edition, department_id),
            {
                "expected_version": 2,
                "confirmation_name": "Private hidden target",
                "reason": "Attempt a protected deletion.",
            },
            format="json",
        )
        for department_id in target_ids
    )

    for response in responses:
        assert response.status_code == 404
        assert response.headers["Content-Type"].startswith("application/problem+json")
        assert _problem_shape(response) == (
            "structure_department_unavailable",
            "The requested structure is unavailable.",
            None,
        )
        assert "Private retired target" not in response.content.decode()
        assert "Private foreign target" not in response.content.decode()
        assert "Private hidden target" not in response.content.decode()
    assert EditionStructureControl.objects.get(edition=edition).aggregate_version == 2


def test_stale_retry_lifecycle_and_dependency_conflicts_are_exact_409() -> None:
    actor = _administrator()
    edition = EventEditionFactory()
    client = _client(actor)
    key = uuid4()
    parent = _post_create(
        client=client,
        edition=edition,
        retry_key=key,
        name="Parent",
    )
    parent_id = UUID(parent.json()["department_id"])

    stale = _post_create(
        client=client,
        edition=edition,
        expected_version=0,
        name="Stale",
    )
    retry_conflict = _post_create(
        client=client,
        edition=edition,
        retry_key=key,
        expected_version=0,
        name="Changed reuse",
    )
    child = _post_create(
        client=client,
        edition=edition,
        expected_version=1,
        name="Child",
        parent_department_id=parent_id,
    )
    dependency = client.post(
        _retire_url(edition, parent_id),
        {"expected_version": 2, "reason": "A child must block retirement."},
        format="json",
    )
    assert child.status_code == 201

    noneditable = EventEditionFactory(
        series__organization__lifecycle=Organization.Lifecycle.CLOSED,
    )
    lifecycle = _post_create(
        client=client,
        edition=noneditable,
        expected_version=0,
        name="Read-only",
    )

    assert stale.status_code == 409
    assert stale.json()["code"] == "structure_version_conflict"
    assert retry_conflict.status_code == 409
    assert retry_conflict.json()["code"] == "structure_retry_conflict"
    assert dependency.status_code == 409
    assert dependency.json()["code"] == "structure_department_has_dependencies"
    assert lifecycle.status_code == 409
    assert lifecycle.json()["code"] == "structure_lifecycle_conflict"


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (StructureStateConflictError(), "structure_state_conflict"),
        (StructureLimitConflictError(), "structure_limit_exceeded"),
    ],
)
def test_remaining_domain_conflicts_have_stable_409_codes(
    error: StructureCommandError,
    expected_code: str,
) -> None:
    edition = EventEditionFactory()
    with patch("maru.workforce.api.create_department", side_effect=error):
        response = _client(_administrator()).post(
            _collection_url(edition),
            _create_payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )

    assert response.status_code == 409
    assert response.json()["code"] == expected_code


@pytest.mark.parametrize(
    "error",
    [
        DatabaseError("private database label"),
        StructureCommandError("private command label"),
        StructureDependencyUnavailableError("private Programme dependency label"),
    ],
)
def test_infrastructure_and_base_command_failures_are_name_free_503(
    error: Exception,
) -> None:
    edition = EventEditionFactory()
    with patch("maru.workforce.api.create_department", side_effect=error):
        response = _client(_administrator()).post(
            _collection_url(edition),
            _create_payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )

    assert response.status_code == 503
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert response.json()["code"] == "service_unavailable"
    assert "private database" not in response.content.decode()
    assert "private command" not in response.content.decode()
    assert "private Programme" not in response.content.decode()
    assert not Department.objects.exists()


def test_retirement_dependency_unavailability_is_name_free_503() -> None:
    """The retirement API must keep Programme dependency failure details private."""
    edition = EventEditionFactory()
    client = _client(_administrator())
    created = _post_create(client=client, edition=edition, name="Programme")
    department_id = UUID(created.json()["department_id"])

    with patch(
        "maru.workforce.api.retire_department",
        side_effect=StructureDependencyUnavailableError(
            "private Programme dependency detail"
        ),
    ):
        response = client.post(
            _retire_url(edition, department_id),
            {
                "expected_version": 1,
                "reason": "Keep the dependency failure non-disclosing.",
            },
            format="json",
        )

    assert response.status_code == 503
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert response.json()["code"] == "service_unavailable"
    assert response.json()["detail"] == (
        "A required Maru service is temporarily unavailable."
    )
    assert "private Programme" not in response.content.decode()
    assert Department.objects.get(pk=department_id).retired_at is None
    assert EditionStructureControl.objects.get(edition=edition).aggregate_version == 1


def test_server_owned_command_validation_is_a_name_free_503() -> None:
    edition = EventEditionFactory()
    error = ValidationError(
        {
            "source_channel": ValidationError(
                "private server-owned source label",
                code="structure_source_channel_invalid",
            )
        }
    )
    with patch("maru.workforce.api.create_department", side_effect=error):
        response = _client(_administrator()).post(
            _collection_url(edition),
            _create_payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )

    assert response.status_code == 503
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert response.json()["code"] == "service_unavailable"
    assert "source_channel" not in response.content.decode()
    assert "private server-owned" not in response.content.decode()
    assert "structure_source_channel_invalid" not in response.content.decode()
    assert not Department.objects.exists()


@pytest.mark.parametrize(
    "failure_target",
    [
        "maru.workforce.structure_commands.append_audit",
        "maru.workforce.structure_commands.publish_domain_event",
        "maru.effects.services.OutboxMessage.objects.create",
    ],
)
def test_audit_event_and_outbox_failures_roll_back_the_whole_command(
    failure_target: str,
) -> None:
    edition = EventEditionFactory()
    with patch(
        failure_target,
        side_effect=RuntimeError("private downstream dependency label"),
    ):
        response = _client(_administrator()).post(
            _collection_url(edition),
            _create_payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        )

    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"
    assert "private downstream" not in response.content.decode()
    assert not Department.objects.exists()
    assert not EditionStructureControl.objects.exists()
    assert not EditionStructureCommandReceipt.objects.exists()
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


@pytest.mark.parametrize("request_id", [None, "not-a-safe-request-id"])
def test_generated_request_id_is_safe_and_persisted_consistently(
    request_id: str | None,
) -> None:
    edition = EventEditionFactory()
    kwargs = {} if request_id is None else {"HTTP_X_REQUEST_ID": request_id}
    response = _client(_administrator()).post(
        _collection_url(edition),
        _create_payload(),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        **kwargs,
    )

    assert response.status_code == 201
    safe_id = UUID(response.headers["X-Request-ID"])
    assert str(safe_id) == response.headers["X-Request-ID"]
    assert response.headers["X-Request-ID"] != request_id
    receipt = EditionStructureCommandReceipt.objects.get(edition=edition)
    audit = AuditEvent.objects.get(operation="workforce.structure.change")
    event = DomainEvent.objects.get(event_name="workforce.structure.changed.v1")
    assert receipt.correlation_id == safe_id
    assert audit.correlation_id == safe_id
    assert audit.request_id == safe_id
    assert event.correlation_id == safe_id


def test_valid_request_id_is_echoed_and_persisted_consistently() -> None:
    edition = EventEditionFactory()
    request_id = uuid4()
    response = _client(_administrator()).post(
        _collection_url(edition),
        _create_payload(),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        HTTP_X_REQUEST_ID=str(request_id),
    )

    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == str(request_id)
    receipt = EditionStructureCommandReceipt.objects.get(edition=edition)
    audit = AuditEvent.objects.get(operation="workforce.structure.change")
    event = DomainEvent.objects.get(event_name="workforce.structure.changed.v1")
    assert receipt.correlation_id == request_id
    assert audit.correlation_id == request_id
    assert audit.request_id == request_id
    assert event.correlation_id == request_id


def test_session_authenticated_unsafe_methods_retain_csrf_enforcement() -> None:
    actor = _administrator()
    edition = EventEditionFactory()
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(actor)

    create = client.post(
        _collection_url(edition),
        _create_payload(),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    delete = client.delete(
        _department_url(edition, uuid4()),
        {
            "expected_version": 1,
            "confirmation_name": "Unavailable",
            "reason": "This request must not reach the command.",
        },
        format="json",
    )

    assert create.status_code == 403
    assert delete.status_code == 403
    assert not Department.objects.exists()


def test_session_authenticated_request_with_valid_csrf_succeeds() -> None:
    actor = _administrator()
    edition = EventEditionFactory()
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(actor)
    csrf_response = client.get("/api/v1/public/csrf")
    csrf_token = csrf_response.json()["csrf_token"]

    response = client.post(
        _collection_url(edition),
        _create_payload(),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert csrf_response.status_code == 200
    assert response.status_code == 201
    assert response.json()["aggregate_version"] == 1
    assert Department.objects.filter(edition=edition).count() == 1


def test_unsupported_methods_and_unmounted_route_do_not_mutate_structure() -> None:
    edition = EventEditionFactory()
    actor = _administrator()
    client = _client(actor)
    unsupported = (
        client.get(_collection_url(edition)),
        client.patch(
            _department_url(edition, uuid4()),
            _create_payload(),
            format="json",
        ),
        client.put(
            _retire_url(edition, uuid4()),
            {"expected_version": 1, "reason": "Unsupported method."},
            format="json",
        ),
    )
    removed_route = client.post(
        (
            f"/api/v1/organizations/{edition.organization_id}/"
            f"editions/{edition.id}/workforce/structure/departments"
        ),
        _create_payload(),
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    for response in unsupported:
        assert response.status_code == 405
        assert response.headers["Content-Type"].startswith("application/problem+json")
        assert response.json()["code"] == "method_not_allowed"
    assert removed_route.status_code == 404
    assert not Department.objects.exists()
    assert not EditionStructureControl.objects.exists()
    assert not EditionStructureCommandReceipt.objects.exists()


def _component_for_operation(schema: dict[str, object], operation: dict[str, object]):
    request_schema = operation["requestBody"]["content"]["application/json"][  # type: ignore[index]
        "schema"
    ]
    reference = request_schema["$ref"]  # type: ignore[index]
    return schema["components"]["schemas"][reference.rsplit("/", 1)[-1]]  # type: ignore[index]


def test_page9_mutation_openapi_declares_closed_routes_and_problem_responses() -> None:
    response = _client(_administrator()).get(
        "/api/v1/schema",
        HTTP_ACCEPT="application/vnd.oai.openapi+json",
    )
    assert response.status_code == 200
    schema = response.json()
    prefix = "/api/v1/organizations/{organization_id}/editions/{edition_id}"
    template = schema["paths"][f"{prefix}/workforce/structure/template-applications"][
        "post"
    ]
    collection = schema["paths"][f"{prefix}/workforce/departments"]["post"]
    detail_path = f"{prefix}/workforce/departments/{{department_id}}"
    update = schema["paths"][detail_path]["put"]
    delete = schema["paths"][detail_path]["delete"]
    retire = schema["paths"][f"{detail_path}/retire"]["post"]

    assert set(template["responses"]) == {"200", "201", "400", "403", "409", "503"}
    assert set(collection["responses"]) == {
        "200",
        "201",
        "400",
        "403",
        "404",
        "409",
        "503",
    }
    for operation in (update, delete, retire):
        assert set(operation["responses"]) == {
            "200",
            "400",
            "403",
            "404",
            "409",
            "503",
        }
        for status_code in ("400", "403", "404", "409", "503"):
            problem = operation["responses"][status_code]["content"][
                "application/problem+json"
            ]["schema"]
            assert problem["$ref"].endswith("/WorkforceProblem")

    for operation in (template, collection):
        header = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "Idempotency-Key"
        )
        assert header["in"] == "header"
        assert header["required"] is True
        assert header["schema"]["format"] == "uuid"
        assert header["schema"]["pattern"] == (
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$"
        )
    for operation in (update, delete, retire):
        assert all(
            parameter["name"] != "Idempotency-Key"
            for parameter in operation["parameters"]
        )

    forbidden = {
        "retry_key",
        "organization_id",
        "edition_id",
        "department_id",
        "actor_id",
        "code",
        "retired_at",
        "aggregate_version",
    }
    for operation in (template, collection, update, delete, retire):
        assert operation["security"] == [
            {"cookieAuth": []},
            {"basicAuth": []},
        ]
        assert {} not in operation["security"]
        component = _component_for_operation(schema, operation)
        assert not forbidden.intersection(component["properties"])
        assert component["additionalProperties"] is False

    canonical_uuid_pattern = (
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
        r"[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    for operation in (collection, update):
        component = _component_for_operation(schema, operation)
        assert component["properties"]["parent_department_id"]["pattern"] == (
            canonical_uuid_pattern
        )

    template_success = template["responses"]["201"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    template_component = schema["components"]["schemas"][
        template_success.rsplit("/", 1)[-1]
    ]
    department_success = collection["responses"]["201"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    department_component = schema["components"]["schemas"][
        department_success.rsplit("/", 1)[-1]
    ]
    assert set(template_component["properties"]) == {"aggregate_version"}
    assert set(department_component["properties"]) == {
        "department_id",
        "aggregate_version",
    }
    assert delete["requestBody"]["required"] is True
    assert set(delete["requestBody"]["content"]) == {"application/json"}
    delete_component = _component_for_operation(schema, delete)
    assert set(delete_component["properties"]) == {
        "expected_version",
        "reason",
        "confirmation_name",
    }
    assert set(delete_component["required"]) == {
        "expected_version",
        "reason",
        "confirmation_name",
    }
