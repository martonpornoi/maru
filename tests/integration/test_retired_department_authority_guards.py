from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from time import sleep
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.utils import timezone

from maru.authorization.bindings import ensure_workforce_position_binding
from maru.authorization.models import (
    CapabilityGrant,
    RoleAssignment,
    ScopedResourceBinding,
)
from maru.authorization.policy import (
    resolve_department_target,
    resolve_resource_target,
)
from maru.workforce.models import (
    Department,
    EditionStructureControl,
    Position,
    PositionTemplate,
)
from maru.workforce.structure_commands import retire_department
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)
from tests.workforce_helpers import create_department_for_test, save_position_for_test

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _department_world() -> tuple[Department, object, object]:
    edition = EventEditionFactory()
    actor = AccountFactory(is_staff=True, is_superuser=True)
    department = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
        actor=actor,
    )
    return department, edition, actor


def _position(*, department: Department, actor: object, suffix: str) -> Position:
    bundle = RoleBundleFactory(
        organization=department.organization,
        capability_codes=["workforce.view_structure"],
    )
    template = PositionTemplate.objects.create(
        organization=department.organization,
        code=f"helper-{suffix}",
        name=f"Helper {suffix}",
        description="Synthetic position template.",
        default_capacity_codes=["volunteer"],
        role_bundle=bundle,
        created_by=actor,
    )
    return save_position_for_test(
        position=Position(
            organization=department.organization,
            edition=department.edition,
            template=template,
            department=department,
            role_bundle=bundle,
            code=f"helper-{suffix}",
            title=f"Helper {suffix}",
            description="Synthetic position.",
            capacity_codes=["volunteer"],
            status=Position.Status.CLOSED,
            created_by=actor,
        )
    )


def _retire(*, department: Department, actor: object) -> None:
    current_version = EditionStructureControl.objects.get(
        organization=department.organization,
        edition=department.edition,
    ).aggregate_version
    retire_department(
        actor=actor,  # type: ignore[arg-type]
        organization_id=department.organization_id,
        series_id=department.edition.series_id,
        edition_id=department.edition_id,
        department_id=department.id,
        expected_version=current_version,
        reason="Retire the synthetic Department guard target.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    department.refresh_from_db()


def test_runtime_resolvers_and_binding_writer_reject_retired_department() -> None:
    department, edition, actor = _department_world()
    position = _position(department=department, actor=actor, suffix="one")
    binding = ensure_workforce_position_binding(position=position)

    assert (
        resolve_department_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            department_id=department.id,
        )
        is not None
    )
    assert (
        resolve_resource_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            department_id=department.id,
            resource_binding_id=binding.id,
        )
        is not None
    )

    retired_department = create_department_for_test(
        edition=edition,
        name="Retired Operations",
        expected_code="retired-operations",
        actor=actor,  # type: ignore[arg-type]
    )
    unbound_position = _position(
        department=retired_department,
        actor=actor,
        suffix="two",
    )
    _retire(department=retired_department, actor=actor)

    assert (
        resolve_department_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            department_id=retired_department.id,
        )
        is None
    )
    with pytest.raises(ValidationError, match="retired Department"):
        ensure_workforce_position_binding(position=unbound_position)


def test_database_blocks_new_binding_and_authority_but_retains_history() -> None:
    department, edition, actor = _department_world()
    position = _position(department=department, actor=actor, suffix="history")
    principal = AccountFactory()
    bundle = RoleBundleFactory(
        organization=edition.organization,
        capability_codes=["workforce.view_structure"],
    )
    now = timezone.now()
    expired_grant = CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        department=department,
        principal=principal,
        capability_code="workforce.view_structure",
        effective_from=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )
    expired_assignment = RoleAssignmentFactory(
        organization=edition.organization,
        edition=edition,
        department=department,
        principal=principal,
        role_bundle=bundle,
        effective_from=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )

    _retire(department=department, actor=actor)

    with pytest.raises(IntegrityError), transaction.atomic():
        ScopedResourceBinding.objects.bulk_create(
            [
                ScopedResourceBinding(
                    id=uuid4(),
                    organization=edition.organization,
                    edition=edition,
                    department=department,
                    resource_kind=ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION,
                    resource_id=position.id,
                )
            ]
        )

    with pytest.raises(ValidationError, match="retired Department"):
        CapabilityGrant(
            organization=edition.organization,
            edition=edition,
            department=department,
            principal=principal,
            capability_code="workforce.view_structure",
            effective_from=now,
            granted_by=actor,
            reason="Forbidden current grant.",
        ).full_clean()

    with pytest.raises(IntegrityError), transaction.atomic():
        CapabilityGrant.objects.bulk_create(
            [
                CapabilityGrant(
                    organization=edition.organization,
                    edition=edition,
                    department=department,
                    principal=principal,
                    capability_code="workforce.view_structure",
                    effective_from=now,
                    granted_by=actor,
                    reason="Forbidden raw grant.",
                )
            ]
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        RoleAssignment.objects.bulk_create(
            [
                RoleAssignment(
                    organization=edition.organization,
                    edition=edition,
                    department=department,
                    principal=principal,
                    role_bundle=bundle,
                    effective_from=now,
                    granted_by=actor,
                    reason="Forbidden raw assignment.",
                )
            ]
        )

    CapabilityGrant.objects.filter(pk=expired_grant.pk).update(
        revoked_at=now,
        revoked_by=actor,
        revocation_reason="Close retained historical grant.",
    )
    RoleAssignment.objects.filter(pk=expired_assignment.pk).update(
        revoked_at=now,
        revoked_by=actor,
        revocation_reason="Close retained historical assignment.",
    )
    expired_grant.refresh_from_db()
    expired_assignment.refresh_from_db()
    assert expired_grant.revoked_at == now
    assert expired_assignment.revoked_at == now


def test_current_authority_must_close_before_department_retirement() -> None:
    department, edition, actor = _department_world()
    principal = AccountFactory()
    grant = CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        department=department,
        principal=principal,
        capability_code="workforce.view_structure",
    )

    def attempt_raw_retirement() -> None:
        with transaction.atomic():
            control = EditionStructureControl.objects.select_for_update().get(
                organization=department.organization,
                edition=department.edition,
            )
            control.aggregate_version += 1
            control.save(update_fields=("aggregate_version", "updated_at"))
            Department.objects.filter(pk=department.pk).update(
                last_changed_in_structure_version=control.aggregate_version,
                retired_at=timezone.now(),
                retired_by=actor,
                retired_in_structure_version=control.aggregate_version,
            )

    with pytest.raises(IntegrityError):
        attempt_raw_retirement()

    now = timezone.now()
    CapabilityGrant.objects.filter(pk=grant.pk).update(
        revoked_at=now,
        revoked_by=actor,
        revocation_reason="Close authority before retirement.",
    )
    _retire(department=department, actor=actor)
    assert department.retired_at is not None


def test_existing_resource_binding_is_retained_after_department_retirement() -> None:
    department, _edition, actor = _department_world()
    position = _position(department=department, actor=actor, suffix="binding")
    binding = ensure_workforce_position_binding(position=position)

    _retire(department=department, actor=actor)

    assert ScopedResourceBinding.objects.filter(pk=binding.pk).exists()
    department.refresh_from_db()
    assert department.retired_at is not None


def test_binding_and_retirement_serialize_without_deadlock() -> None:
    department, _edition, actor = _department_world()
    position = _position(department=department, actor=actor, suffix="race")
    binding_inserted = Event()
    release_binding = Event()

    def insert_binding() -> object:
        close_old_connections()
        try:
            with transaction.atomic():
                locked_position = Position.objects.get(pk=position.pk)
                binding = ensure_workforce_position_binding(position=locked_position)
                binding_inserted.set()
                assert release_binding.wait(timeout=5)
                return binding.id
        finally:
            close_old_connections()

    def retire_department() -> str:
        close_old_connections()
        try:
            persisted_department = Department.objects.select_related("edition").get(
                pk=department.pk
            )
            _retire(department=persisted_department, actor=actor)
        except IntegrityError:
            return "rejected"
        finally:
            close_old_connections()
        return "retired"

    with ThreadPoolExecutor(max_workers=2) as executor:
        binding_future = executor.submit(insert_binding)
        assert binding_inserted.wait(timeout=5)
        retirement_future = executor.submit(retire_department)
        sleep(0.2)
        assert not retirement_future.done()
        release_binding.set()
        assert binding_future.result(timeout=5) is not None
        assert retirement_future.result(timeout=5) == "retired"

    department.refresh_from_db()
    assert department.retired_at is not None
