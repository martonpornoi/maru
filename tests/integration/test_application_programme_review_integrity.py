"""Real SQL and atomic-failure defenses for the dormant Programme review kernel."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from psycopg import sql

from maru.applications import programme_review_commands as commands
from maru.applications.models import (
    ProgrammeReviewAction as Action,
)
from maru.applications.models import (
    ProgrammeReviewAssignment,
    ProgrammeReviewCase,
    ProgrammeReviewEntry,
    ProgrammeReviewPolicy,
    ProgrammeReviewReceipt,
)
from maru.applications.programme_review_commands import ProgrammeReviewResult
from maru.applications.programme_review_inputs import (
    ProgrammeReviewCommandInput as Intent,
)
from maru.applications.programme_writer_boundary import (
    programme_application_database_writer,
)
from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent, OutboxMessage
from tests.integration.test_application_programme_services import (
    _admit_future_programme_effects,
)
from tests.support.programme_review import assign_and_score, create_review_world
from tests.unit.test_application_programme_review_inputs import review_policy

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures(_admit_future_programme_effects.__name__),
]


def _counts():
    return tuple(
        model.objects.count()
        for model in (
            ProgrammeReviewCase,
            ProgrammeReviewAssignment,
            ProgrammeReviewEntry,
            ProgrammeReviewReceipt,
            AuditEvent,
            DomainEvent,
            OutboxMessage,
        )
    )


@pytest.mark.parametrize(
    "table",
    [
        "applications_programmereviewpolicy",
        "applications_programmereviewcase",
        "applications_programmereviewentry",
        "applications_programmereviewreceipt",
    ],
)
def test_raw_review_changes_fail_without_the_closed_writer(table):
    world = create_review_world()
    with (
        pytest.raises(IntegrityError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            sql.SQL("UPDATE public.{} SET updated_at = CURRENT_TIMESTAMP").format(
                sql.Identifier(table)
            )
        )
    assert world.version == 1


@pytest.mark.parametrize(
    "table",
    [
        "applications_programmereviewpolicy",
        "applications_programmereviewentry",
        "applications_programmereviewreceipt",
    ],
)
def test_even_the_migration_owner_cannot_rewrite_or_delete_review_evidence(table):
    create_review_world()
    for operation in (
        sql.SQL("UPDATE public.{} SET updated_at = CURRENT_TIMESTAMP").format(
            sql.Identifier(table)
        ),
        sql.SQL("DELETE FROM public.{}").format(sql.Identifier(table)),
    ):
        with (
            pytest.raises(IntegrityError),
            transaction.atomic(),
            programme_application_database_writer(),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(operation)


def test_case_cursor_cannot_advance_without_the_matching_entry_and_receipt():
    world = create_review_world()
    with (
        pytest.raises(IntegrityError, match="exact immutable evidence"),
        transaction.atomic(),
        programme_application_database_writer(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE public.applications_programmereviewcase "
            "SET version = version + 1 WHERE id = %s",
            [world.case_id],
        )
    assert world.version == 1


def test_omitted_receipt_rolls_back_the_entire_transition(monkeypatch):
    world = create_review_world()
    before = _counts()

    def omit_receipt(*_args, **_kwargs):
        return ProgrammeReviewResult(uuid4(), uuid4(), world.case_id, 2, replayed=False)

    monkeypatch.setattr(commands, "_record", omit_receipt)
    with pytest.raises(IntegrityError, match="receipt is absent"):
        world.command(
            world.call.manager.id,
            Intent(
                Action.REVIEWER_ASSIGNED, world.case_id, reference_id=world.reviewer.id
            ),
        )
    assert _counts() == before
    assert world.version == 1


@pytest.mark.parametrize("failure", ["audit", "event", "receipt"])
def test_downstream_failure_rolls_back_state_audit_event_outbox_and_receipt(
    monkeypatch, failure
):
    world = create_review_world()
    before = _counts()
    target, attribute = (
        (commands, "append_audit")
        if failure == "audit"
        else (commands, "publish_domain_event")
        if failure == "event"
        else (ProgrammeReviewReceipt.objects, "create")
    )
    real = getattr(target, attribute)

    def unavailable(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("Synthetic review persistence outage")

    monkeypatch.setattr(target, attribute, unavailable)
    with pytest.raises(RuntimeError, match="Synthetic review persistence outage"):
        world.command(
            world.call.manager.id,
            Intent(
                Action.REVIEWER_ASSIGNED, world.case_id, reference_id=world.reviewer.id
            ),
        )
    assert _counts() == before


@pytest.mark.parametrize(
    "payload",
    [
        {"scores": {"fit": 999}},
        {"scores": {"fit": True}},
        {"scores": {"missing": 2}},
        {"scores": {"fit": 2}, "private_extra": "not allowed"},
    ],
)
def test_sql_rejects_forged_score_payloads_after_service_validation(
    monkeypatch, payload
):
    world = create_review_world()
    assignment = assign_and_score(world, world.reviewer.id)
    real = ProgrammeReviewEntry.objects.create

    def corrupt_entry(**kwargs):
        kwargs["payload"] = payload
        return real(**kwargs)

    before = _counts()
    monkeypatch.setattr(ProgrammeReviewEntry.objects, "create", corrupt_entry)
    with pytest.raises(IntegrityError):
        world.command(
            world.reviewer.id,
            Intent(
                Action.SCORED,
                world.case_id,
                reference_id=assignment,
                scores=(("fit", 4),),
            ),
        )
    assert _counts() == before


def test_sql_rejects_a_different_pinned_revision_even_inside_writer_context():
    world = create_review_world()
    other = create_review_world()
    with (
        pytest.raises(IntegrityError, match="binding is immutable"),
        transaction.atomic(),
        programme_application_database_writer(),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE public.applications_programmereviewcase "
            "SET revision_id = %s, version = version + 1 WHERE id = %s",
            [
                ProgrammeReviewCase.objects.get(id=other.case_id).revision_id,
                world.case_id,
            ],
        )


def test_sql_rejects_an_open_case_payload_disguised_as_a_decision(monkeypatch):
    world = create_review_world()
    real = ProgrammeReviewEntry.objects.create

    def corrupt_entry(**kwargs):
        kwargs["action"] = Action.CASE_OPENED
        kwargs["payload"] = {"policy_id": str(world.policy_id)}
        return real(**kwargs)

    monkeypatch.setattr(ProgrammeReviewEntry.objects, "create", corrupt_entry)
    with pytest.raises(IntegrityError):
        world.command(
            world.call.manager.id,
            Intent(
                Action.REVIEWER_ASSIGNED, world.case_id, reference_id=world.reviewer.id
            ),
        )


@pytest.mark.parametrize("part", ["stages", "templates"])
def test_sql_refuses_malformed_policy_json_without_trusting_python_validation(
    monkeypatch, part
):
    world = create_review_world()
    real = ProgrammeReviewPolicy.objects.create

    def corrupt_policy(**kwargs):
        kwargs[part] = {"not": "an array"}
        return real(**kwargs)

    monkeypatch.setattr(ProgrammeReviewPolicy.objects, "create", corrupt_policy)

    with pytest.raises(IntegrityError):
        world.command(
            world.call.manager.id,
            Intent(Action.POLICY_CREATED, world.call.call_id, policy=review_policy()),
            expected_version=1,
        )
