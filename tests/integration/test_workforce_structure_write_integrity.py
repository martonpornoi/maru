from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from threading import Event
from uuid import uuid4

import pytest
from django.db import (
    DatabaseError,
    IntegrityError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.utils import timezone

from maru.authorization.bindings import ensure_workforce_position_binding
from maru.workforce.models import (
    Department,
    EditionStructureCommandReceipt,
    EditionStructureControl,
    Position,
    PositionTemplate,
)
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RoleBundleFactory,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


@dataclass(frozen=True, slots=True)
class _StructureWorld:
    control: EditionStructureControl
    department: Department
    actor: object


def _append_receipt(
    *,
    world: _StructureWorld,
    action: str,
    version: int,
    changed_fields: list[str],
    affected_ids: list[object],
    deleted_name: str = "",
    actor: object | None = None,
) -> EditionStructureCommandReceipt:
    return EditionStructureCommandReceipt.objects.create(
        structure=world.control,
        organization=world.control.organization,
        edition=world.control.edition,
        action=action,
        resulting_version=version,
        actor=world.actor if actor is None else actor,
        reason="Exercise the exact Page 9 database protocol.",
        correlation_id=uuid4(),
        source_channel="service",
        changed_fields=changed_fields,
        affected_department_ids=affected_ids,
        retry_key=(
            uuid4()
            if action == EditionStructureCommandReceipt.Action.DEPARTMENT_CREATED
            else None
        ),
        request_digest=(
            "a" * 64
            if action == EditionStructureCommandReceipt.Action.DEPARTMENT_CREATED
            else ""
        ),
        deleted_name_snapshot=deleted_name,
    )


def _structure_world(*, code: str = "operations") -> _StructureWorld:
    edition = EventEditionFactory()
    actor = AccountFactory()
    with transaction.atomic():
        control = EditionStructureControl.objects.create(
            organization=edition.organization,
            edition=edition,
            origin=EditionStructureControl.Origin.MANUAL,
            aggregate_version=1,
        )
        department = Department.objects.create(
            organization=edition.organization,
            edition=edition,
            code=code,
            name="Operations",
            description="Synthetic operations Department.",
            created_in_structure_version=1,
            last_changed_in_structure_version=1,
        )
        world = _StructureWorld(
            control=control,
            department=department,
            actor=actor,
        )
        _append_receipt(
            world=world,
            action=EditionStructureCommandReceipt.Action.DEPARTMENT_CREATED,
            version=1,
            changed_fields=["departments"],
            affected_ids=[department.id],
        )
    return world


def _advance_control(world: _StructureWorld, version: int) -> None:
    world.control.aggregate_version = version
    world.control.save(update_fields=("aggregate_version", "updated_at"))


def _retire(world: _StructureWorld, *, version: int = 2) -> None:
    with transaction.atomic():
        _advance_control(world, version)
        world.department.retired_at = timezone.now()
        world.department.retired_by = world.actor
        world.department.retired_in_structure_version = version
        world.department.last_changed_in_structure_version = version
        world.department.save(
            update_fields=(
                "retired_at",
                "retired_by",
                "retired_in_structure_version",
                "last_changed_in_structure_version",
                "updated_at",
            )
        )
        _append_receipt(
            world=world,
            action=EditionStructureCommandReceipt.Action.DEPARTMENT_RETIRED,
            version=version,
            changed_fields=["retirement"],
            affected_ids=[world.department.id],
        )
    world.department.refresh_from_db()
    world.control.refresh_from_db()


def _closed_position(world: _StructureWorld, *, suffix: str) -> Position:
    bundle = RoleBundleFactory(
        organization=world.control.organization,
        capability_codes=["workforce.view_structure"],
    )
    template = PositionTemplate.objects.create(
        organization=world.control.organization,
        code=f"closed-helper-{suffix}",
        name=f"Closed helper {suffix}",
        description="Synthetic immutable Position template.",
        default_capacity_codes=["volunteer"],
        role_bundle=bundle,
        created_by=world.actor,
    )
    return Position.objects.create(
        organization=world.control.organization,
        edition=world.control.edition,
        template=template,
        department=world.department,
        role_bundle=bundle,
        code=f"closed-helper-{suffix}",
        title=f"Closed helper {suffix}",
        description="Synthetic closed Position.",
        capacity_codes=["volunteer"],
        status=Position.Status.CLOSED,
        created_by=world.actor,
    )


def _update_without_receipt(world: _StructureWorld) -> None:
    with transaction.atomic():
        _advance_control(world, 2)
        Department.objects.filter(pk=world.department.pk).update(
            name="Missing receipt",
            last_changed_in_structure_version=2,
            updated_at=timezone.now(),
        )


def _write_duplicate_changed_fields(world: _StructureWorld) -> None:
    with transaction.atomic():
        _advance_control(world, 2)
        world.department.name = "Invalid evidence"
        world.department.last_changed_in_structure_version = 2
        world.department.save(
            update_fields=(
                "name",
                "last_changed_in_structure_version",
                "updated_at",
            )
        )
        EditionStructureCommandReceipt.objects.bulk_create(
            [
                EditionStructureCommandReceipt(
                    structure=world.control,
                    organization=world.control.organization,
                    edition=world.control.edition,
                    action=EditionStructureCommandReceipt.Action.DEPARTMENT_UPDATED,
                    resulting_version=2,
                    actor=world.actor,
                    reason="Reject duplicate changed fields.",
                    correlation_id=uuid4(),
                    source_channel="service",
                    changed_fields=["name", "name"],
                    affected_department_ids=[world.department.id],
                )
            ]
        )


def _truncate_receipts_without_test_reset() -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL maru.authority_provenance_test_reset = 'off'")
        cursor.execute("TRUNCATE TABLE workforce_editionstructurecommandreceipt")


def _change_same_department_twice_at_one_version(world: _StructureWorld) -> None:
    with transaction.atomic():
        _advance_control(world, 2)
        world.department.name = "First protected update"
        world.department.last_changed_in_structure_version = 2
        world.department.save(
            update_fields=("name", "last_changed_in_structure_version", "updated_at")
        )
        world.department.name = "Second forbidden update"
        world.department.save(update_fields=("name", "updated_at"))


def _retire_with_receipt_actor(world: _StructureWorld, *, actor: object) -> None:
    with transaction.atomic():
        _advance_control(world, 2)
        world.department.retired_at = timezone.now()
        world.department.retired_by = world.actor
        world.department.retired_in_structure_version = 2
        world.department.last_changed_in_structure_version = 2
        world.department.save(
            update_fields=(
                "retired_at",
                "retired_by",
                "retired_in_structure_version",
                "last_changed_in_structure_version",
                "updated_at",
            )
        )
        _append_receipt(
            world=world,
            action=EditionStructureCommandReceipt.Action.DEPARTMENT_RETIRED,
            version=2,
            changed_fields=["retirement"],
            affected_ids=[world.department.id],
            actor=actor,
        )


def test_control_must_advance_before_department_and_exact_receipt_must_follow() -> None:
    world = _structure_world()

    with (
        pytest.raises(IntegrityError, match=r"version evidence|already changed"),
        transaction.atomic(),
    ):
        Department.objects.filter(pk=world.department.pk).update(
            name="Changed too early",
            last_changed_in_structure_version=2,
        )

    with pytest.raises(
        IntegrityError,
        match=r"immutable receipt|immutable command evidence",
    ):
        _update_without_receipt(world)

    world.control.refresh_from_db()
    world.department.refresh_from_db()
    assert world.control.aggregate_version == 1
    assert world.department.name == "Operations"

    with transaction.atomic():
        _advance_control(world, 2)
        world.department.name = "Convention Operations"
        world.department.last_changed_in_structure_version = 2
        world.department.save(
            update_fields=(
                "name",
                "last_changed_in_structure_version",
                "updated_at",
            )
        )
        _append_receipt(
            world=world,
            action=EditionStructureCommandReceipt.Action.DEPARTMENT_UPDATED,
            version=2,
            changed_fields=["name"],
            affected_ids=[world.department.id],
        )

    world.control.refresh_from_db()
    world.department.refresh_from_db()
    assert world.control.aggregate_version == 2
    assert world.department.name == "Convention Operations"


def test_receipt_arrays_actions_and_immutability_fail_closed() -> None:
    world = _structure_world()

    with pytest.raises(IntegrityError, match="unique and canonical"):
        _write_duplicate_changed_fields(world)

    receipt = EditionStructureCommandReceipt.objects.get(
        structure=world.control,
        resulting_version=1,
    )
    with pytest.raises(IntegrityError, match="immutable"), transaction.atomic():
        EditionStructureCommandReceipt.objects.filter(pk=receipt.pk).update(
            reason="Forbidden mutation."
        )
    with pytest.raises(IntegrityError, match="cannot be truncated"):
        _truncate_receipts_without_test_reset()


def test_one_department_cannot_change_twice_at_one_structure_version() -> None:
    world = _structure_world()

    with pytest.raises(IntegrityError, match="already changed"):
        _change_same_department_twice_at_one_version(world)

    world.control.refresh_from_db()
    world.department.refresh_from_db()
    assert world.control.aggregate_version == 1
    assert world.department.name == "Operations"


def test_retirement_receipt_actor_must_match_retirement_actor() -> None:
    world = _structure_world()
    different_actor = AccountFactory()

    with pytest.raises(IntegrityError, match="exact immutable command evidence"):
        _retire_with_receipt_actor(world, actor=different_actor)

    world.control.refresh_from_db()
    world.department.refresh_from_db()
    assert world.control.aggregate_version == 1
    assert world.department.retired_at is None


def test_historical_binding_survives_retirement_and_rejects_operations() -> None:
    world = _structure_world()
    position = _closed_position(world, suffix="history")
    binding = ensure_workforce_position_binding(position=position)

    _retire(world)

    assert type(binding).objects.filter(pk=binding.pk).exists()
    with (
        pytest.raises(IntegrityError, match="retired Department"),
        transaction.atomic(),
    ):
        _closed_position(world, suffix="forbidden")


def test_current_or_future_authority_blocks_retirement() -> None:
    world = _structure_world()
    CapabilityGrantFactory(
        organization=world.control.organization,
        edition=world.control.edition,
        department=world.department,
        principal=AccountFactory(),
        capability_code="workforce.view_structure",
        effective_from=timezone.now() + timedelta(days=7),
        expires_at=timezone.now() + timedelta(days=30),
    )

    with pytest.raises(
        IntegrityError,
        match=r"current or future operations|current authority blocks",
    ):
        _retire(world)

    world.control.refresh_from_db()
    world.department.refresh_from_db()
    assert world.control.aggregate_version == 1
    assert world.department.retired_at is None


def test_protected_delete_requires_creation_only_history_and_tombstone() -> None:
    world = _structure_world()
    department_id = world.department.id
    department_name = world.department.name

    with transaction.atomic():
        _advance_control(world, 2)
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM workforce_department WHERE id = %s",
                [department_id],
            )
        _append_receipt(
            world=world,
            action=EditionStructureCommandReceipt.Action.DEPARTMENT_DELETED,
            version=2,
            changed_fields=["departments"],
            affected_ids=[department_id],
            deleted_name=department_name,
        )

    assert not Department.objects.filter(pk=department_id).exists()
    assert EditionStructureCommandReceipt.objects.filter(
        structure=world.control,
        action=EditionStructureCommandReceipt.Action.DEPARTMENT_DELETED,
        affected_department_ids=[department_id],
    ).exists()


def test_exclusive_cutover_barrier_rejects_a_concurrent_raw_writer() -> None:
    world = _structure_world()
    acquired = Event()
    release = Event()

    def hold_exclusive_barrier() -> None:
        close_old_connections()
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(4400460007)")
                acquired.set()
                assert release.wait(timeout=10)
        finally:
            acquired.set()
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        holder = executor.submit(hold_exclusive_barrier)
        assert acquired.wait(timeout=10)
        try:
            with pytest.raises(DatabaseError), transaction.atomic():
                EditionStructureControl.objects.filter(pk=world.control.pk).update(
                    aggregate_version=2,
                )
        finally:
            release.set()
        holder.result(timeout=10)
