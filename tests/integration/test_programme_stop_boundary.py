"""Programme native terminal closure and exact retained personal privacy commands."""

from contextlib import contextmanager
from dataclasses import replace
from importlib import import_module
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from psycopg import sql

from maru.events import adoption
from maru.events.programme_stop_readiness import programme_stop_preparation_is_ready
from maru.programme import commands
from maru.programme.authorization import DEFAULT_PROGRAMME_AUTHORIZER
from maru.programme.commands import ProgrammeLifecycleConflictError
from maru.programme.models import (
    ProgrammeHostAvailabilityWindow,
    ProgrammeHostRelationship,
    ProgrammeItem,
    ProgrammePublicRenditionWithdrawal,
    ProgrammeReadinessRequirement,
)
from maru.programme.public_copy_commands import withdraw_programme_public_rendition
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.integration.test_programme_commands import _create
from tests.integration.test_programme_hosts import invite, remove, respond, share
from tests.integration.test_scheduling_programme_stop import _terminal
from tests.rehearsals.programme_candidate import PROGRAMME_REHEARSAL_PROFILE
from tests.support.programme_schema import admit_transaction_local_schema_candidate

pytestmark = [pytest.mark.django_db, pytest.mark.integration]
GUARDS = import_module("maru.programme.migrations.0022_programme_stop_boundary")


@pytest.fixture
def candidate(monkeypatch):
    admit_transaction_local_schema_candidate(monkeypatch)
    monkeypatch.setattr(
        adoption,
        "ADOPTION_PROFILES",
        {
            **adoption.ADOPTION_PROFILES,
            ("programme_operations", 1): PROGRAMME_REHEARSAL_PROFILE,
        },
    )
    return EventEditionFactory(adoption_profile_code="programme_operations")


@pytest.fixture
def world(candidate):
    manager, person = AccountFactory(), AccountFactory()
    for capability in ("programme.manage_items", "programme.manage_hosts"):
        CapabilityGrantFactory(
            organization=candidate.organization,
            edition=candidate,
            principal=manager,
            capability_code=capability,
        )
    item, _, _ = _create(
        actor=manager,
        edition=candidate,
        authorizer=DEFAULT_PROGRAMME_AUTHORIZER,
    )
    return (
        manager,
        person,
        {
            "organization_id": candidate.organization_id,
            "edition_id": candidate.id,
            "item_id": item.item_id,
            "authorizer": DEFAULT_PROGRAMME_AUTHORIZER,
            "source_channel": "test",
        },
    )


def test_person_can_decline_retained_invitation_after_stop(world, candidate):
    invitation = invite(world)
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    _terminal(candidate, "archived")
    result = respond(world, invitation, "decline")
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert ProgrammeHostRelationship.objects.get(id=result.host_id).state == "declined"


def test_person_can_erase_shared_periods_then_withdraw_hosting(world, candidate):
    shared = share(world, respond(world, invite(world)))
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    _terminal(candidate, "archived")
    erased = share(world, shared, state="withdrawn", periods=())
    result = respond(world, erased, "withdraw")
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert not ProgrammeHostAvailabilityWindow.objects.filter(
        host_id=result.host_id
    ).exists()
    assert ProgrammeHostRelationship.objects.get(id=result.host_id).state == "withdrawn"


@pytest.mark.parametrize("model", GUARDS.GUARDED_MODELS)
def test_native_fresh_programme_work_requires_more_than_terminal_scope(
    candidate, model
):
    _terminal(candidate, "archived")
    with (
        connection.cursor() as cursor,
        pytest.raises(IntegrityError),
        transaction.atomic(),
    ):
        cursor.execute(
            sql.SQL(
                "INSERT INTO {} (id, organization_id, edition_id) VALUES (%s, %s, %s)"
            ).format(sql.Identifier("public", f"programme_{model}")),
            [uuid4(), candidate.organization_id, candidate.id],
        )


def test_exact_programme_stop_preparation_is_ready():
    assert programme_stop_preparation_is_ready()


@pytest.mark.parametrize("model", GUARDS.GUARDED_MODELS)
def test_missing_content_stop_guard_refuses_preparation_readiness(model):
    index = GUARDS.GUARDED_MODELS.index(model)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER TABLE {} DISABLE TRIGGER {}").format(
                sql.Identifier("public", f"programme_{model}"),
                sql.Identifier(f"a00_programme_stop_{index}"),
            )
        )
    assert not programme_stop_preparation_is_ready()


@pytest.mark.parametrize("operation", ["confirm", "share", "remove"])
def test_real_commands_cannot_resume_host_operation(world, candidate, operation):
    current = invite(world)
    if operation != "confirm":
        current = respond(world, current)
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    _terminal(candidate, "archived")
    with pytest.raises(ProgrammeLifecycleConflictError):
        {"confirm": respond, "share": share, "remove": remove}[operation](
            world, current
        )


@pytest.mark.parametrize("extra", ["kind = 'break'", "lifecycle = 'retired'"])
def test_personal_exit_cannot_smuggle_item_content_changes(world, candidate, extra):
    invitation = invite(world)
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    _terminal(candidate, "archived")
    with (
        connection.cursor() as cursor,
        pytest.raises(IntegrityError, match="Stopped Programme refuses"),
        transaction.atomic(),
    ):
        cursor.execute(
            sql.SQL(
                "UPDATE public.programme_programmeitem SET "
                "aggregate_version = aggregate_version + 1, {} WHERE id = %s"
            ).format(sql.SQL(extra)),
            [invitation.item_id],
        )


def test_native_privacy_exit_rejects_unrelated_transaction_audit(
    world, candidate, monkeypatch
):
    invitation = invite(world)
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    _terminal(candidate, "archived")
    original = commands.audited_mutation

    @contextmanager
    def mismatched(record, **kwargs):
        with original(
            replace(record, idempotency_key_hash="0" * 64), **kwargs
        ) as mutation:
            yield mutation

    monkeypatch.setattr(commands, "audited_mutation", mismatched)
    with (  # noqa: PT012 -- mutation and deferred check must roll back together.
        pytest.raises(
            IntegrityError, match="privacy exit requires exact native evidence"
        ),
        transaction.atomic(),
    ):
        respond(world, invitation, "decline")
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert (
        ProgrammeHostRelationship.objects.get(id=invitation.host_id).state == "invited"
    )


def test_exact_public_copy_withdrawal_remains_authorized_after_stop(world, candidate):
    manager, _, common = world
    CapabilityGrantFactory(
        organization=candidate.organization,
        edition=candidate,
        principal=manager,
        capability_code="programme.approve_public_copy",
    )
    item = ProgrammeItem.objects.get(id=common["item_id"])
    approved = commands.approve_programme_public_rendition(
        **common,
        actor_id=manager.id,
        source_working_revision_id=item.working_revisions.get().id,
        public_title="Synthetic approved copy",
        expected_version=item.aggregate_version,
        reason="Approve exact synthetic public copy.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
    )
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    _terminal(candidate, "archived")
    key = uuid4()
    arguments = dict(
        common,
        actor_id=manager.id,
        rendition_id=approved.result_object_id,
        expected_version=item.aggregate_version,
        reason="Withdraw exact synthetic public copy.",
        idempotency_key=key,
    )
    result = withdraw_programme_public_rendition(**arguments, correlation_id=uuid4())
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert (
        ProgrammePublicRenditionWithdrawal.objects.get(
            id=result.result_object_id
        ).rendition_id
        == approved.result_object_id
    )
    assert withdraw_programme_public_rendition(
        **arguments, correlation_id=uuid4()
    ).replayed


def test_privacy_exit_moves_only_its_original_readiness_dependencies(world, candidate):
    manager, _, common = world
    current = share(world, respond(world, invite(world)))
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    CapabilityGrantFactory(
        organization=candidate.organization,
        edition=candidate,
        principal=manager,
        capability_code="programme.manage_readiness",
    )
    for concern in ("host_confirmation", "schedule_availability", "technical_needs"):
        configured = commands.configure_programme_readiness(
            **common,
            actor_id=manager.id,
            concern=concern,
            disposition="required",
            expected_version=ProgrammeItem.objects.get(
                id=common["item_id"]
            ).aggregate_version,
            reason="Keep independent synthetic readiness obligations.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
        )
    current = replace(current, resulting_item_version=configured.resulting_item_version)
    before = dict(
        ProgrammeReadinessRequirement.objects.values_list(
            "concern", "dependency_version"
        )
    )
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    _terminal(candidate, "archived")
    result = share(world, current, state="withdrawn", periods=())
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    after = dict(
        ProgrammeReadinessRequirement.objects.values_list(
            "concern", "dependency_version"
        )
    )
    assert after == {**before, "schedule_availability": result.resulting_item_version}
