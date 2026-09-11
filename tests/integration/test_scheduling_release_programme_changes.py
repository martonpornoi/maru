from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction

from maru.audit.models import AuditEvent
from maru.programme.commands import (
    approve_programme_public_rendition,
    revise_programme_delivery,
    revise_programme_working,
)
from maru.programme.host_commands import replace_programme_host_availability
from maru.programme.host_inputs import (
    ProgrammeHostAvailabilityInput,
    ProgrammeHostAvailabilityPeriod,
)
from maru.programme.models import (
    ProgrammeHostRelationship,
    ProgrammeItem,
    ProgrammeWorkingRevision,
)
from maru.scheduling.models import (
    SchedulingReleaseDependencyChange,
    SchedulingReleaseDependencyKey,
)
from maru.scheduling.writer_boundary import scheduling_writer
from tests.integration import test_programme_hosts as hosts

world = hosts.world
pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def _track(world, *, kind="programme_item", source_id=None):
    common = world[2]
    with transaction.atomic(), scheduling_writer():
        return SchedulingReleaseDependencyKey.objects.create(
            kind=kind,
            source_id=source_id or common["item_id"],
            organization_id=common["organization_id"],
            edition_id=common["edition_id"],
        )


def _command(world, *, expected_version=1, idempotency_key=None):
    return {
        **world[2],
        "actor_id": world[0].id,
        "expected_version": expected_version,
        "reason": "Synthetic source update",
        "idempotency_key": idempotency_key or uuid4(),
        "correlation_id": uuid4(),
    }


def test_native_delivery_change_advances_exact_item_source(world):
    key = _track(world)
    result = revise_programme_delivery(
        **_command(world), technical_requirements="Synthetic microphone requirement"
    )
    key.refresh_from_db()
    change = SchedulingReleaseDependencyChange.objects.get(dependency=key)
    assert key.generation == change.generation == 2
    assert change.organization_id == world[2]["organization_id"]
    assert change.edition_id == world[2]["edition_id"]
    assert change.source_audit.target_id == result.item_id
    assert change.source_audit.operation == "programme.command.delivery_revise"


def test_private_working_change_does_not_withdraw_retained_release(world):
    key = _track(world)
    revise_programme_working(**_command(world), internal_title="Synthetic private edit")
    key.refresh_from_db()
    assert key.generation == 1
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_new_public_rendition_does_not_withdraw_previous_approved_copy(world):
    first = approve_programme_public_rendition(
        **_command(world),
        source_working_revision_id=ProgrammeWorkingRevision.objects.get().id,
        public_title="Synthetic first approved title",
    )
    key = _track(world, kind="programme_public_copy", source_id=first.result_object_id)
    approve_programme_public_rendition(
        **_command(world),
        source_working_revision_id=ProgrammeWorkingRevision.objects.get().id,
        public_title="Synthetic later approved title",
    )
    key.refresh_from_db()
    assert key.generation == 1
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_exact_delivery_retry_does_not_advance_dependency_twice(world):
    key = _track(world)
    command = _command(world)
    first = revise_programme_delivery(
        **command, technical_requirements="Synthetic input"
    )
    replay = revise_programme_delivery(
        **command, technical_requirements="Synthetic input"
    )
    assert replay == replace(first, replayed=True)
    key.refresh_from_db()
    assert key.generation == 2
    assert SchedulingReleaseDependencyChange.objects.count() == 1


def test_skipped_programme_join_cannot_commit_native_delivery(world):
    key = _track(world)
    with (
        patch("maru.programme.commands.record_programme_release_change"),
        pytest.raises(IntegrityError, match="native release invalidation"),
    ):
        revise_programme_delivery(
            **_command(world), technical_requirements="Synthetic must roll back"
        )
    key.refresh_from_db()
    assert key.generation == 1
    assert ProgrammeItem.objects.get().aggregate_version == 1
    assert not SchedulingReleaseDependencyChange.objects.exists()
    assert not AuditEvent.objects.filter(
        operation="programme.command.delivery_revise", outcome="allow"
    ).exists()


def test_host_withdrawal_changes_operational_and_disclosure_sources(world):
    confirmed = hosts.respond(world, hosts.invite(world))
    item = _track(world)
    operational = _track(
        world, kind="programme_host_operational", source_id=confirmed.host_id
    )
    disclosure = _track(
        world, kind="programme_host_disclosure", source_id=confirmed.host_id
    )
    result = hosts.respond(world, confirmed, action="withdraw")
    for key in (item, operational, disclosure):
        key.refresh_from_db()
        assert key.generation == 2
    changes = tuple(SchedulingReleaseDependencyChange.objects.all())
    assert len(changes) == 3
    assert len({change.source_audit_id for change in changes}) == 1
    assert changes[0].source_audit.target_id == world[2]["item_id"]
    assert ProgrammeHostRelationship.objects.get(pk=result.host_id).state == "withdrawn"


def test_host_availability_changes_safety_without_withdrawing_relationship_copy(world):
    confirmed = hosts.respond(world, hosts.invite(world))
    operational = _track(
        world, kind="programme_host_operational", source_id=confirmed.host_id
    )
    disclosure = _track(
        world, kind="programme_host_disclosure", source_id=confirmed.host_id
    )
    replace_programme_host_availability(
        **world[2],
        actor_id=world[1].id,
        availability=ProgrammeHostAvailabilityInput(
            confirmed.host_id,
            "shared",
            (
                ProgrammeHostAvailabilityPeriod(
                    datetime(2030, 8, 2, 8, tzinfo=UTC),
                    datetime(2030, 8, 2, 10, tzinfo=UTC),
                ),
            ),
            confirmed.resulting_item_version,
            confirmed.resulting_host_version,
        ),
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    operational.refresh_from_db()
    disclosure.refresh_from_db()
    assert operational.generation == 2
    assert disclosure.generation == 1


def test_host_mutation_failure_rolls_back_every_dependency_and_native_relationship(
    world,
):
    confirmed = hosts.respond(world, hosts.invite(world))
    item = _track(world)
    operational = _track(
        world, kind="programme_host_operational", source_id=confirmed.host_id
    )

    def fail_native_append(execute, sql, params, many, context):
        if "maru_scheduling_record_native_release_change(" in sql:
            raise RuntimeError("Synthetic append unavailable")
        return execute(sql, params, many, context)

    with (
        connection.execute_wrapper(fail_native_append),
        pytest.raises(RuntimeError, match="Synthetic append unavailable"),
    ):
        hosts.respond(world, confirmed, action="withdraw")
    for key in (item, operational):
        key.refresh_from_db()
        assert key.generation == 1
    assert ProgrammeHostRelationship.objects.get().state == "confirmed"
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_programme_source_mapping_is_closed_for_missing_receipt(world):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM public.maru_programme_release_mutation_sources(%s)",
            [uuid4()],
        )
        assert cursor.fetchall() == []
