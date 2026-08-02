"""Live creation coverage for workforce-position authorization bindings."""

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import RequestFactory

from maru.authorization.bindings import (
    ensure_workforce_position_binding,
    workforce_position_binding_id,
)
from maru.authorization.models import RoleBundle, ScopedResourceBinding
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.workforce.admin import PositionAdmin
from maru.workforce.bootstrap import bootstrap_organization_workforce
from maru.workforce.models import Department, Position, PositionTemplate
from tests.factories import AccountFactory, EventEditionFactory, RoleBundleFactory
from tests.workforce_helpers import (
    create_department_for_test,
    save_position_for_test,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


@dataclass(frozen=True, slots=True)
class _PositionScope:
    edition: EventEdition
    creator: Account
    role_bundle: RoleBundle
    department: Department
    template: PositionTemplate


def _position_scope() -> _PositionScope:
    edition = EventEditionFactory()
    creator = AccountFactory()
    role_bundle = RoleBundleFactory(organization=edition.organization)
    department = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="operations-lead",
        name="Operations lead",
        description="Synthetic position template.",
        default_capacity_codes=["volunteer"],
        role_bundle=role_bundle,
        created_by=creator,
    )
    return _PositionScope(
        edition=edition,
        creator=creator,
        role_bundle=role_bundle,
        department=department,
        template=template,
    )


def _create_position(
    scope: _PositionScope,
    *,
    code: str = "operations-lead",
) -> Position:
    return save_position_for_test(
        position=Position(
            organization=scope.edition.organization,
            edition=scope.edition,
            template=scope.template,
            department=scope.department,
            role_bundle=scope.role_bundle,
            code=code,
            title="Operations lead",
            description="Synthetic position.",
            capacity_codes=["volunteer"],
            created_by=scope.creator,
        )
    )


def test_service_creates_exact_deterministic_position_binding() -> None:
    scope = _position_scope()
    position = _create_position(scope)

    binding = ensure_workforce_position_binding(position=position)

    assert binding.id == workforce_position_binding_id(position.id)
    assert binding.resource_kind == (
        ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION
    )
    assert binding.resource_id == position.id
    assert binding.organization_id == position.organization_id
    assert binding.edition_id == position.edition_id
    assert binding.department_id == position.department_id


def test_service_rejects_an_unsaved_position() -> None:
    with pytest.raises(ValidationError) as error:
        ensure_workforce_position_binding(position=Position())

    assert error.value.code == "workforce_position_unavailable"


def test_service_rejects_a_position_deleted_after_resolution() -> None:
    position = Position(id=uuid4())
    position._state.adding = False

    with pytest.raises(ValidationError) as error:
        ensure_workforce_position_binding(position=position)

    assert error.value.code == "workforce_position_unavailable"


def test_service_rejects_an_occupied_deterministic_binding_identifier() -> None:
    scope = _position_scope()
    position = _create_position(scope)
    other_position = _create_position(scope, code="operations-deputy")
    ScopedResourceBinding.objects.create(
        id=workforce_position_binding_id(position.id),
        organization=scope.edition.organization,
        edition=scope.edition,
        department=scope.department,
        resource_kind=ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION,
        resource_id=other_position.id,
    )

    with pytest.raises(ValidationError) as error:
        ensure_workforce_position_binding(position=position)

    assert error.value.code == "resource_binding_scope_mismatch"


def test_service_is_idempotent_and_uses_the_persisted_position_scope() -> None:
    scope = _position_scope()
    position = _create_position(scope)
    first = ensure_workforce_position_binding(position=position)
    other_department = create_department_for_test(
        edition=scope.edition,
        name="Programming",
        expected_code="programming",
    )
    position.department = other_department

    second = ensure_workforce_position_binding(position=position)

    assert second.id == first.id
    assert second.department_id == scope.department.id
    assert (
        ScopedResourceBinding.objects.filter(
            resource_kind=ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION,
            resource_id=position.id,
        ).count()
        == 1
    )


def test_service_fails_closed_for_an_existing_mismatched_binding() -> None:
    scope = _position_scope()
    position = _create_position(scope)
    other_department = create_department_for_test(
        edition=scope.edition,
        name="Programming",
        expected_code="programming",
    )

    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE authorization_scopedresourcebinding DISABLE TRIGGER "
            "authorization_scoped_resource_binding_guard"
        )
    try:
        ScopedResourceBinding.objects.bulk_create(
            [
                ScopedResourceBinding(
                    id=workforce_position_binding_id(position.id),
                    organization=scope.edition.organization,
                    edition=scope.edition,
                    department=other_department,
                    resource_kind=(
                        ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION
                    ),
                    resource_id=position.id,
                )
            ]
        )
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE authorization_scopedresourcebinding ENABLE TRIGGER "
                "authorization_scoped_resource_binding_guard"
            )

    with pytest.raises(ValidationError) as error:
        ensure_workforce_position_binding(position=position)

    assert error.value.code == "resource_binding_scope_mismatch"
    binding = ScopedResourceBinding.objects.get(resource_id=position.id)
    assert binding.department_id == other_department.id


def test_position_admin_creates_binding_after_saving_position() -> None:
    scope = _position_scope()
    request = RequestFactory().post("/admin/workforce/position/add/")
    request.user = scope.creator
    position = Position(
        organization=scope.edition.organization,
        edition=scope.edition,
        template=scope.template,
        department=scope.department,
        role_bundle=scope.role_bundle,
        code="admin-created-position",
        title="Admin-created position",
        description="Synthetic admin creation.",
        capacity_codes=["volunteer"],
    )

    PositionAdmin(Position, admin.site).save_model(
        request,
        position,
        SimpleNamespace(),  # type: ignore[arg-type]
        change=False,
    )

    binding = ScopedResourceBinding.objects.get(resource_id=position.id)
    assert position.created_by_id == scope.creator.id
    assert binding.department_id == scope.department.id


def test_preserved_workforce_bootstrap_creates_chair_position_binding() -> None:
    controller = AccountFactory(
        is_staff=True,
        is_superuser=True,
    )
    chair = AccountFactory(is_staff=True)
    edition = EventEditionFactory()

    bootstrap_organization_workforce(
        organization=edition.organization,
        edition=edition,
        controller=controller,
        chair=chair,
        reason="Synthetic recovery-path bootstrap.",
        correlation_id=uuid4(),
    )

    position = Position.objects.get(edition=edition, code="convention-chair")
    binding = ScopedResourceBinding.objects.get(
        resource_kind=ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION,
        resource_id=position.id,
    )
    assert binding.organization_id == edition.organization_id
    assert binding.edition_id == edition.id
    assert binding.department_id == position.department_id
