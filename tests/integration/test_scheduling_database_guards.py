"""Database-enforced history, minimization and stale-evidence protection."""

from copy import deepcopy
from importlib import import_module
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import DatabaseError, connection, transaction

from maru.scheduling import command_support, evaluation_commands, evaluation_sources
from maru.scheduling.catalogs import SchedulingConflictCode, SchedulingConflictSeverity
from maru.scheduling.conflicts import SchedulingFinding
from maru.scheduling.evaluation_commands import acknowledge_scheduling_warning
from maru.scheduling.inputs import scheduling_digest
from maru.scheduling.models import (
    SchedulingEvaluation,
    SchedulingWarningAcknowledgement,
)
from tests.integration.test_scheduling_evaluations import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_evaluations import availability, evaluate
from tests.integration.test_scheduling_placements import next_request, place
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414
from tests.integration.test_scheduling_reservations import reserve

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]

RELEASE_TABLE_SUFFIXES = frozenset(
    {
        "schedulingreleasedependencykey",
        "schedulingreleasedependencychange",
        "schedulingreleasewarningacknowledgement",
        "schedulingreleaseapproval",
        "schedulingreleaseapprovalplacement",
        "schedulingreleaseapprovaldependency",
        "schedulingrelease",
        "schedulingreleaseartifact",
        "schedulingreleasepointer",
        "schedulingreleasewithdrawal",
    }
)


def assert_raw_guard_matrix(expected, *, mutable_versions):
    """Require actual populated rows and check-violation denials for every table."""
    models = {
        model._meta.model_name: model
        for model in apps.get_app_config("scheduling").get_models()
    }
    planning = set(
        import_module("maru.scheduling.migrations.0005_integrity_guards").TABLE_SUFFIXES
    )
    assert planning.isdisjoint(RELEASE_TABLE_SUFFIXES)
    assert set(models) == planning | RELEASE_TABLE_SUFFIXES
    assert set(expected) <= models.keys()
    checked = set()
    for name in sorted(expected):
        model = models[name]
        row = model.objects.first()
        assert row is not None, model.__name__
        retained = model.objects.values().get(id=row.id)
        table = connection.ops.quote_name(model._meta.db_table)
        field = mutable_versions.get(name, "updated_at")
        assert model._meta.get_field(field).concrete
        quoted = connection.ops.quote_name(field)
        update = f"{quoted} = {quoted}" + (" + 1" if name in mutable_versions else "")
        for statement in (
            f"UPDATE {table} SET {update} WHERE id = %s",  # noqa: S608 -- quoted identifiers, closed expression
            f"DELETE FROM {table} WHERE id = %s",  # noqa: S608 -- quoted table, bound identity
        ):
            with (
                pytest.raises(DatabaseError) as rejected,
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(statement, [row.id])
            assert rejected.value.__cause__.sqlstate == "23514"
        assert model.objects.values().get(id=row.id) == retained, model.__name__
        checked.add(name)
    assert checked == set(expected)


def seed(world):
    availability(world)
    placed = place(world)
    reserve(world, placed=placed)
    _, report = evaluate(world, placed)
    warning = report.conflicts.get(code="host_outside_preference")
    acknowledge_scheduling_warning(
        next_request(world), conflict_id=warning.id, authorizer=world.policy
    )
    return report


def test_every_planning_table_rejects_raw_update_and_delete(world, admitted):
    seed(world)
    mutable = {
        "schedulingeditioncontrol",
        "schedulingserviceday",
        "schedulingoccurrence",
        "schedulingcandidate",
    }
    expected = import_module(
        "maru.scheduling.migrations.0005_integrity_guards"
    ).TABLE_SUFFIXES
    assert_raw_guard_matrix(
        expected, mutable_versions=dict.fromkeys(mutable, "aggregate_version")
    )


def test_truncate_is_blocked_without_the_isolated_test_reset_factor(world, admitted):
    report = seed(world)
    names = [
        connection.ops.quote_name(model._meta.db_table)
        for model in apps.get_app_config("scheduling").get_models()
    ]
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL maru.authority_provenance_test_reset = 'off'")
        with (
            pytest.raises(
                DatabaseError, match="Scheduling history cannot be truncated"
            ),
            transaction.atomic(),
        ):
            cursor.execute("TRUNCATE TABLE " + ", ".join(names) + " CASCADE")
    assert SchedulingEvaluation.objects.filter(id=report.id).exists()


def test_evidence_schema_refuses_private_calendars_unknown_fields_and_unknown_sources(
    world, admitted
):
    report = seed(world)
    malformed = []
    for index in range(3):
        extra = deepcopy(report.source_evidence)
        extra[index]["private_calendar"] = [{"starts_at": "2030-08-02T08:00:00Z"}]
        malformed.append(extra)
    extra = deepcopy(report.source_evidence)
    extra[1]["hosts"][0]["periods"] = []
    malformed.append(extra)
    extra = deepcopy(report.source_evidence)
    extra[2]["source_code"] = "unknown-owner@1"
    malformed.append(extra)
    extra = deepcopy(report.source_evidence)
    extra[0]["not_evaluated"] = []
    malformed.append(extra)
    for payload in malformed:
        with (
            pytest.raises(DatabaseError, match="closed calendar-free"),
            transaction.atomic(),
        ):
            SchedulingEvaluation.objects.bulk_create(
                [
                    SchedulingEvaluation(
                        organization_id=report.organization_id,
                        edition_id=report.edition_id,
                        actor_id=report.actor_id,
                        occurred_at=report.occurred_at,
                        reason=report.reason,
                        revision_id=report.revision_id,
                        source_evidence=payload,
                        dependency_digest=scheduling_digest({"sources": payload}),
                        conflict_count=0,
                        is_complete=True,
                    )
                ]
            )
    assert SchedulingEvaluation.objects.count() == 1


def test_missing_event_and_outbox_cannot_be_reported_as_command_success(
    world, admitted, monkeypatch
):
    placed = place(world)
    monkeypatch.setattr(
        command_support, "publish_domain_event", lambda *_args, **_kwargs: None
    )
    with (
        pytest.raises(DatabaseError, match="audit, event or outbox"),
        transaction.atomic(),
    ):
        evaluate(world, placed)
    assert not SchedulingEvaluation.objects.exists()


def test_sql_rejects_stale_host_warning_even_if_application_refresh_regresses(
    world, admitted, monkeypatch
):
    availability(world)
    placed = place(world)
    _, report = evaluate(world, placed)
    warning = report.conflicts.get(code="host_outside_preference")
    with transaction.atomic():
        previous = evaluation_sources._current_evaluation(
            next_request(world),
            candidate_id=world.candidate.object_id,
            expected_version=placed.version,
        )
    availability(world, state="withdrawn")
    monkeypatch.setattr(
        evaluation_commands, "_current_evaluation", lambda *_args, **_kwargs: previous
    )
    with pytest.raises(DatabaseError, match="dependency evidence is stale"):
        acknowledge_scheduling_warning(
            next_request(world), conflict_id=warning.id, authorizer=world.policy
        )
    assert not SchedulingWarningAcknowledgement.objects.exists()


def test_cannot_append_a_new_well_formed_finding_to_a_completed_report(world, admitted):
    report = seed(world)
    warning = report.conflicts.get(code="host_outside_preference")
    forged = type(warning)(
        id=uuid4(),
        organization_id=warning.organization_id,
        edition_id=warning.edition_id,
        evaluation_id=warning.evaluation_id,
        occurrence_id=warning.occurrence_id,
        source_code=warning.source_code,
        code="host_overlap",
        severity="blocker",
        fingerprint=evaluation_sources._finding_fingerprint(
            report.dependency_digest,
            SchedulingFinding(
                warning.source_code,
                SchedulingConflictCode.HOST_OVERLAP,
                SchedulingConflictSeverity.BLOCKER,
                warning.occurrence_id,
            ),
        ),
    )
    with pytest.raises(DatabaseError, match="same command"), transaction.atomic():
        type(warning).objects.bulk_create([forged])


def test_fingerprint_is_bound_to_exact_findings_not_just_a_retained_uuid(
    world, admitted, monkeypatch
):
    availability(world)
    placed = place(world)
    monkeypatch.setattr(
        evaluation_commands, "_finding_fingerprint", lambda *_args: "a" * 64
    )
    with pytest.raises(DatabaseError, match="exact evaluation"):
        evaluate(world, placed)
    assert not SchedulingEvaluation.objects.exists()
