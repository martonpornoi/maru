"""Real owner commands and PostgreSQL guards for retained Programme work needs."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from threading import Barrier
from uuid import uuid4

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test.utils import CaptureQueriesContext

import maru.effects.services as effects
from maru.core.database_integrity_readiness import inspect_database_integrity_catalog
from maru.effects.models import DomainEvent, OutboxMessage
from maru.programme import queries as programme_queries
from maru.programme import scheduling_queries, staffing_commands, staffing_queries
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.commands import (
    ProgrammeIdempotencyConflictError,
    ProgrammeLifecycleConflictError,
    ProgrammeUnavailableError,
    ProgrammeVersionConflictError,
)
from maru.programme.models import (
    ProgrammeItem,
    ProgrammeStaffingRequirement,
    ProgrammeStaffingRevision,
)
from maru.programme.queries import ProgrammeQueryUnavailableError
from maru.programme.readiness import (
    _STAFFING_INTEGRITY_CONTRACT,
    programme_database_integrity_is_ready,
)
from maru.programme.staffing_commands import change_programme_staffing_requirement
from maru.programme.staffing_inputs import (
    ProgrammeStaffingChange,
    ProgrammeStaffingExpectation,
)
from maru.programme.staffing_queries import (
    ProgrammeStaffingReadRequest,
    load_programme_staffing_history,
    load_programme_staffing_requirements,
)
from maru.scheduling import occurrence_commands
from maru.scheduling.inputs import SchedulingCommandRequest, SchedulingOccurrenceInput
from maru.scheduling.occurrence_commands import create_scheduling_occurrence
from maru.workforce.models import Position, PositionTemplate, ShiftDemand
from tests.factories import AccountFactory, EventEditionFactory
from tests.integration.test_programme_commands import (
    _AllowThenDenyProgrammeAuthorizer,
    _create,
    _TrustedProgrammeAuthorizer,
)
from tests.integration.test_scheduling_days import TrustedSchedulingPolicy
from tests.support.authority import create_provenance_backed_role_bundle
from tests.workforce_helpers import create_department_for_test, save_position_for_test

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(
        effects, "require_effect_delivery_allowed", lambda **_kwargs: None
    )
    actor, edition = AccountFactory(), EventEditionFactory()
    policy = _TrustedProgrammeAuthorizer()
    item, _, _ = _create(actor=actor, edition=edition, authorizer=policy)
    monkeypatch.setattr(
        scheduling_queries, "profile_allows_conflict_source", lambda *_args: True
    )
    monkeypatch.setattr(
        occurrence_commands,
        "load_programme_scheduling_dependencies",
        partial(
            scheduling_queries.load_programme_scheduling_dependencies,
            authorizer=policy,
        ),
    )
    occurrence = create_scheduling_occurrence(
        SchedulingCommandRequest(
            actor.id,
            edition.organization_id,
            edition.id,
            uuid4(),
            uuid4(),
            "Synthetic staffing occurrence",
            "test",
        ),
        occurrence=SchedulingOccurrenceInput(item.item_id),
        expected_control_version=0,
        authorizer=TrustedSchedulingPolicy(),
    )
    position = staffing_position(actor, edition)
    edition.refresh_from_db()
    terms = ProgrammeStaffingExpectation(
        position.id,
        "Stage preparation",
        "East stage",
        "Prepare the stage",
        "Report to the stage lead",
        datetime(2030, 8, 2, 8, tzinfo=UTC),
        datetime(2030, 8, 2, 10, tzinfo=UTC),
        2,
        15,
        30,
    )
    change = ProgrammeStaffingChange(
        item.item_id,
        occurrence.object_id,
        None,
        1,
        0,
        1,
        edition.aggregate_version,
        terms,
    )
    common = {
        "actor_id": actor.id,
        "organization_id": edition.organization_id,
        "edition_id": edition.id,
        "authorizer": policy,
        "source_channel": "test",
        "reason": "Private staffing rationale",
    }
    return common, change


def staffing_position(actor, edition):
    """Create a governed synthetic Position without an assignment or Participation."""
    _, _, bundle = create_provenance_backed_role_bundle(
        edition.organization,
        code="programme-steward",
        name="Programme steward",
        capability_codes=("workforce.view_structure",),
    )
    department = create_department_for_test(
        edition=edition, name="Programme", expected_code="programme"
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="programme-steward",
        name="Programme steward",
        description="Synthetic Programme work",
        default_headcount=4,
        default_capacity_codes=["volunteer"],
        role_bundle=bundle,
        status=PositionTemplate.Status.PUBLISHED,
        created_by=actor,
    )
    return save_position_for_test(
        position=Position(
            organization=edition.organization,
            edition=edition,
            template=template,
            department=department,
            role_bundle=bundle,
            code="programme-steward",
            title="Programme steward",
            description="Synthetic operational station",
            headcount=4,
            capacity_codes=["volunteer"],
            status=Position.Status.OPEN,
            created_by=actor,
        )
    )


def execute(world, *, change=None, key=None, overrides=None):
    return change_programme_staffing_requirement(
        **(world[0] | (overrides or {})),
        change=change or world[1],
        idempotency_key=key or uuid4(),
        correlation_id=uuid4(),
    )


def successor(world, result, *, retire=False):
    return replace(
        world[1],
        requirement_id=result.requirement_id,
        expected_requirement_version=result.resulting_requirement_version,
        expected_item_version=result.resulting_item_version,
        expectation=None
        if retire
        else replace(world[1].expectation, required_headcount=3),
        retire=retire,
    )


def test_requirement_lifecycle_retains_terms_without_unrelated_effects(
    world,
):
    excluded = (
        "participation",
        "registration",
        "accreditation",
        "communications",
        "catalog",
        "charities",
        "logistics",
    )
    baseline = {
        model: model.objects.count()
        for label in excluded
        for model in apps.get_app_config(label).get_models()
    }
    first = execute(world)
    second = execute(world, change=successor(world, first))
    terminal = execute(world, change=successor(world, second, retire=True))
    requirement = ProgrammeStaffingRequirement.objects.get(id=first.requirement_id)
    assert requirement.version == terminal.resulting_requirement_version == 3
    assert requirement.lifecycle == "retired"
    revisions = list(
        ProgrammeStaffingRevision.objects.filter(requirement=requirement).order_by(
            "sequence"
        )
    )
    assert [r.required_headcount for r in revisions] == [2, 3, 3]
    assert [r.operation for r in revisions] == [
        "staffing_create",
        "staffing_revise",
        "staffing_retire",
    ]
    assert [r.item_version for r in revisions] == [2, 3, 4]
    assert not ShiftDemand.objects.exists()
    assert baseline == {model: model.objects.count() for model in baseline}
    event = DomainEvent.objects.get(aggregate_id=world[1].item_id, aggregate_version=4)
    assert event.payload["action"] == "retire_staffing"
    assert "Private staffing rationale" not in str(event.payload)
    assert OutboxMessage.objects.filter(event=event).exists()
    with pytest.raises(ProgrammeLifecycleConflictError):
        execute(world, change=successor(world, terminal))


def test_retry_returns_historical_identifiers_after_later_revision(world):
    key = uuid4()
    first = execute(world, key=key)
    execute(world, change=successor(world, first))
    assert execute(world, key=key) == replace(first, replayed=True)
    with pytest.raises(ProgrammeIdempotencyConflictError):
        execute(world, key=key, overrides={"reason": "Different intent"})
    assert ProgrammeStaffingRevision.objects.count() == 2


@pytest.mark.parametrize(
    "field",
    [
        "expected_item_version",
        "expected_occurrence_version",
        "expected_edition_version",
    ],
)
def test_source_versions_fail_before_writes(world, field):
    with pytest.raises(ProgrammeVersionConflictError):
        execute(
            world, change=replace(world[1], **{field: getattr(world[1], field) + 1})
        )
    assert not ProgrammeStaffingRequirement.objects.exists()
    assert ProgrammeItem.objects.get(id=world[1].item_id).aggregate_version == 1


@pytest.mark.parametrize("field", ["occurrence_id", "item_id"])
def test_unknown_exact_owner_reference_is_unavailable(world, field):
    with pytest.raises(ProgrammeUnavailableError):
        execute(world, change=replace(world[1], **{field: uuid4()}))
    assert not ProgrammeStaffingRequirement.objects.exists()


def test_independent_current_profile_denies_even_with_valid_shape(world):
    common = dict(world[0])
    del common["authorizer"]
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        change_programme_staffing_requirement(
            **common, change=world[1], idempotency_key=uuid4(), correlation_id=uuid4()
        )
    assert not ProgrammeStaffingRequirement.objects.exists()


def test_locked_reauthorization_revocation_rolls_back(world):
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        execute(world, overrides={"authorizer": _AllowThenDenyProgrammeAuthorizer()})
    assert not ProgrammeStaffingRequirement.objects.exists()


def test_work_must_fit_current_edition_envelope(world):
    terms = replace(world[1].expectation, starts_at=datetime(2029, 1, 1, tzinfo=UTC))
    with pytest.raises(ValidationError, match="envelope"):
        execute(world, change=replace(world[1], expectation=terms))
    assert not ProgrammeStaffingRequirement.objects.exists()


def test_effect_failure_rolls_back_state_receipt_and_audit(world, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("Synthetic outbox unavailable")

    monkeypatch.setattr(staffing_commands, "_record_success", fail)
    with pytest.raises(RuntimeError, match="Synthetic outbox"):
        execute(world)
    assert not ProgrammeStaffingRequirement.objects.exists()
    assert ProgrammeItem.objects.get(id=world[1].item_id).aggregate_version == 1


def test_concurrent_revisions_allow_only_one_exact_version(world):
    first = execute(world)
    change = successor(world, first)
    barrier = Barrier(2)

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=20)
            try:
                execute(world, change=change)
            except ProgrammeVersionConflictError:
                return "stale"
            return "changed"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: worker(), range(2)))
    assert sorted(outcomes) == ["changed", "stale"]
    assert ProgrammeStaffingRevision.objects.count() == 2


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE programme_programmestaffingrequirement SET version = version + 1",
        "DELETE FROM programme_programmestaffingrequirement",
        "TRUNCATE programme_programmestaffingrequirement CASCADE",
        "UPDATE programme_programmestaffingrevision SET required_headcount = 9",
        "DELETE FROM programme_programmestaffingrevision",
        "TRUNCATE programme_programmestaffingrevision CASCADE",
    ],
)
def test_raw_dml_cannot_rewrite_or_erase_retained_work(world, statement):
    execute(world)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('maru.authority_provenance_test_reset', 'off', true)"
        )
        with pytest.raises(DatabaseError), transaction.atomic():
            cursor.execute(statement)
    assert (
        ProgrammeStaffingRequirement.objects.count()
        == ProgrammeStaffingRevision.objects.count()
        == 1
    )


def read_request(world):
    common, change = world
    return ProgrammeStaffingReadRequest(
        common["actor_id"],
        common["organization_id"],
        common["edition_id"],
        change.item_id,
        uuid4(),
        "test",
    )


def test_current_staffing_read_excludes_rationale_and_history_is_explicit(world):
    first = execute(world)
    request, policy = read_request(world), world[0]["authorizer"]
    with CaptureQueriesContext(connection) as queries:
        overview = load_programme_staffing_requirements(request, authorizer=policy)
    assert overview.item_version == 2
    assert len(overview.requirements) == 1
    current = overview.requirements[0]
    assert current.revision_id == first.revision_id
    assert current.expectation == world[1].expectation
    selects = [
        query["sql"]
        for query in queries
        if query["sql"].startswith("SELECT")
        and 'FROM "programme_programmestaffingrevision"' in query["sql"]
    ]
    assert len(selects) == 1
    assert '"reason"' not in selects[0]
    assert '"actor_id"' not in selects[0]
    history = load_programme_staffing_history(
        request,
        requirement_id=first.requirement_id,
        through_version=1,
        authorizer=policy,
    )
    assert history.entries[0].reason == world[0]["reason"]
    assert history.next_after_version is None


def test_fixed_history_ceiling_stays_stable_across_later_changes(world, monkeypatch):
    first = execute(world)
    second = execute(world, change=successor(world, first))
    request, policy = read_request(world), world[0]["authorizer"]
    monkeypatch.setattr(staffing_queries, "STAFFING_HISTORY_PAGE_SIZE", 1)
    page = load_programme_staffing_history(
        request,
        requirement_id=first.requirement_id,
        through_version=2,
        authorizer=policy,
    )
    assert len(page.entries) == 1
    assert page.next_after_version == 1
    execute(world, change=successor(world, second, retire=True))
    next_page = load_programme_staffing_history(
        request,
        requirement_id=first.requirement_id,
        through_version=2,
        after_version=page.next_after_version,
        authorizer=policy,
    )
    assert [entry.requirement.version for entry in next_page.entries] == [2]
    assert next_page.next_after_version is None
    assert next_page.through_version == 2


@pytest.mark.parametrize("field", ["requirements", "history"])
def test_partial_read_authority_and_revoked_policy_release_nothing(
    world, monkeypatch, field
):
    first = execute(world)
    policy = world[0]["authorizer"]
    original = policy.authorize
    monkeypatch.setattr(
        policy,
        "authorize",
        lambda **kwargs: replace(original(**kwargs), fields=frozenset()),
    )
    loader = (
        partial(
            load_programme_staffing_requirements, read_request(world), authorizer=policy
        )
        if field == "requirements"
        else partial(
            load_programme_staffing_history,
            read_request(world),
            requirement_id=first.requirement_id,
            through_version=1,
            authorizer=policy,
        )
    )
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        loader()


def test_history_rejects_foreign_requirement_and_future_or_boolean_cursors(world):
    first = execute(world)
    policy, request = world[0]["authorizer"], read_request(world)
    for values in (
        {"requirement_id": uuid4(), "through_version": 1},
        {"requirement_id": first.requirement_id, "through_version": 2},
        {"requirement_id": first.requirement_id, "through_version": True},
        {
            "requirement_id": first.requirement_id,
            "through_version": 1,
            "after_version": True,
        },
    ):
        with pytest.raises(ProgrammeQueryUnavailableError):
            load_programme_staffing_history(request, **values, authorizer=policy)


def test_staffing_readiness_detects_missing_guard_and_recovers(world):
    execute(world)
    assert programme_database_integrity_is_ready()
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE programme_programmestaffingrevision "
            "DISABLE TRIGGER programme_staffingrevision_guard"
        )
        assert not programme_database_integrity_is_ready()
        transaction.set_rollback(True)
    assert programme_database_integrity_is_ready()


@pytest.mark.usefixtures("restores_current_migration_graph")
def test_unused_staffing_schema_round_trip_preserves_existing_owner_records(world):
    item_id = world[1].item_id
    MigrationExecutor(connection).migrate([("programme", "0009_host_downgrade_fence")])
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regclass('public.programme_programmestaffingrequirement'), "
            "to_regprocedure('public.maru_guard_programme_staffing()')"
        )
        assert cursor.fetchone() == (None, None)
    assert ProgrammeItem.objects.get(id=item_id).aggregate_version == 1
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    assert programme_database_integrity_is_ready()


@pytest.mark.usefixtures("restores_current_migration_graph")
def test_retained_staffing_fences_downgrade_before_removing_any_guard(world):
    first = execute(world)
    before = MigrationRecorder(connection).applied_migrations()
    retained = ProgrammeStaffingRequirement.objects.values().get(
        id=first.requirement_id
    )
    current = MigrationExecutor(connection).loader.graph.leaf_nodes()
    with pytest.raises(RuntimeError, match="retained Programme staffing"):
        MigrationExecutor(connection).migrate(
            [("programme", "0010_staffing_requirements")]
        )
    assert ("programme", "0012_staffing_downgrade_fence") in MigrationRecorder(
        connection
    ).applied_migrations()
    assert (
        ProgrammeStaffingRequirement.objects.get(id=first.requirement_id).version == 1
    )
    after = MigrationRecorder(connection).applied_migrations()
    unused_successors = {
        ("programme", "0013_placement_decisions"),
        ("programme", "0014_placement_decision_integrity"),
        ("programme", "0015_placement_decision_downgrade_fence"),
        ("workforce", "0019_programme_shift_bindings"),
        ("workforce", "0020_programme_binding_integrity"),
        ("workforce", "0021_programme_binding_downgrade_fence"),
    }
    assert after == {
        key: value for key, value in before.items() if key not in unused_successors
    }
    # Ordinary Django reversal may remove unused successors before the older
    # populated fence. The retained staffing guards must remain exact; the
    # partially contracted graph must not claim current application readiness.
    guards = inspect_database_integrity_catalog(_STAFFING_INTEGRITY_CONTRACT)
    assert guards.source_contract_current
    assert guards.required_migrations_applied
    assert guards.relation_ownership_consistent
    assert guards.trigger_contract_current
    assert guards.function_contract_current
    assert guards.function_execute_owner_only
    assert guards.function_ownership_current
    assert not programme_database_integrity_is_ready()
    assert ProgrammeStaffingRequirement.objects.values().get(
        id=first.requirement_id
    ) == (retained)
    MigrationExecutor(connection).migrate(current)
    assert set(MigrationRecorder(connection).applied_migrations()) == set(before)
    assert ProgrammeStaffingRequirement.objects.values().get(
        id=first.requirement_id
    ) == (retained)
    assert programme_database_integrity_is_ready()


def test_staffing_reads_recheck_authority_and_require_successful_audit(
    world, monkeypatch
):
    execute(world)
    request = read_request(world)
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        load_programme_staffing_requirements(
            request, authorizer=_AllowThenDenyProgrammeAuthorizer()
        )

    def fail(**_kwargs):
        raise RuntimeError("Synthetic read audit unavailable")

    monkeypatch.setattr(programme_queries, "_append_query_audit", fail)
    with pytest.raises(RuntimeError, match="read audit unavailable"):
        load_programme_staffing_requirements(request, authorizer=world[0]["authorizer"])


def test_foreign_item_and_scope_cannot_be_used_for_staffing(world):
    other = EventEditionFactory()
    actor = AccountFactory()
    foreign, _, _ = _create(
        actor=actor, edition=other, authorizer=_TrustedProgrammeAuthorizer()
    )
    with pytest.raises(ProgrammeUnavailableError):
        execute(world, change=replace(world[1], item_id=foreign.item_id))
    with pytest.raises(ProgrammeQueryUnavailableError):
        load_programme_staffing_requirements(
            replace(read_request(world), item_id=foreign.item_id),
            authorizer=world[0]["authorizer"],
        )
    assert not ProgrammeStaffingRequirement.objects.exists()


@pytest.mark.parametrize(
    "invalid",
    [
        {"required_headcount": 0},
        {"break_minutes": 120},
        {"minimum_rest_minutes": 2881},
        {"starts_at": "2030-08-02T08:00:01Z"},
        {"title": ""},
        {"briefing": "hidden\nline"},
        {"occurrence_version": 2},
        {"position_id": str(uuid4())},
    ],
)
def test_raw_append_cannot_forge_invalid_work_terms(world, invalid):
    first = execute(world)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE programme_programmeitem "
            "SET aggregate_version = aggregate_version + 1 WHERE id = %s",
            [first.item_id],
        )
        cursor.execute(
            "UPDATE programme_programmestaffingrequirement "
            "SET version = 2, item_version = 3 WHERE id = %s",
            [first.requirement_id],
        )
        patch = {
            "id": str(uuid4()),
            "sequence": 2,
            "item_version": 3,
            "operation": "staffing_revise",
            **invalid,
        }
        with pytest.raises(DatabaseError), transaction.atomic():
            cursor.execute(
                "INSERT INTO programme_programmestaffingrevision "
                "SELECT (jsonb_populate_record("
                "NULL::programme_programmestaffingrevision, "
                "to_jsonb(r) || %s::jsonb)).* "
                "FROM programme_programmestaffingrevision r WHERE id = %s",
                [json.dumps(patch), first.revision_id],
            )
        transaction.set_rollback(True)
    assert ProgrammeItem.objects.get(id=first.item_id).aggregate_version == 2
    assert (
        ProgrammeStaffingRequirement.objects.get(id=first.requirement_id).version == 1
    )
