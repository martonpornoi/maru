"""Real exact-source assessments retain independent versions and atomic evidence."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.services import transition_edition
from maru.identity.models import Account
from maru.programme import placement_commands as commands
from maru.programme import placement_queries as queries
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.commands import (
    ProgrammeIdempotencyConflictError,
    ProgrammeLifecycleConflictError,
    ProgrammeUnavailableError,
    ProgrammeVersionConflictError,
    revise_programme_delivery,
)
from maru.programme.models import (
    ProgrammeCommandReceipt,
    ProgrammeItem,
    ProgrammePlacementDecision,
)
from maru.programme.readiness import programme_database_integrity_is_ready
from maru.programme.release_inputs import (
    ProgrammePlacementDecisionIntent,
    ProgrammePlacementSelection,
)
from maru.programme.release_inputs import ProgrammePlacementDecisionKind as Kind
from maru.programme.release_inputs import ProgrammePlacementDecisionState as State
from maru.scheduling.models import SchedulingOccurrence
from maru.workforce import programme_release_queries as workforce_sources
from tests.factories import CapabilityGrantFactory
from tests.integration.test_programme_commands import _TrustedProgrammeAuthorizer
from tests.integration.test_programme_release_sources import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_placements import (
    candidate_revision,
    member,
    moved,
    place,
)
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def assessed(world, admitted, monkeypatch):
    monkeypatch.setattr(queries, "profile_allows_adapter", lambda *_args: True)
    monkeypatch.setattr(
        workforce_sources, "profile_allows_adapter", lambda *_args: True
    )
    item = ProgrammeItem.objects.get(
        id=SchedulingOccurrence.objects.get(
            id=world.occurrence.object_id
        ).programme_item_id
    )
    policy = _TrustedProgrammeAuthorizer()
    common = {
        "actor_id": world.request.actor_id,
        "organization_id": world.request.organization_id,
        "edition_id": world.request.edition_id,
        "reason": "Synthetic exact placement assessment",
        "source_channel": "test",
    }
    revised = revise_programme_delivery(
        **common,
        item_id=item.id,
        accessibility_delivery="Keep the front aisle clear.",
        expected_version=item.aggregate_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        authorizer=policy,
    )
    CapabilityGrantFactory(
        organization_id=item.organization_id,
        edition_id=item.edition_id,
        principal_id=world.request.actor_id,
        capability_code="workforce.view_shifts",
    )
    placed = place(world)
    selection = ProgrammePlacementSelection(
        item.id,
        world.occurrence.object_id,
        placed.object_id,
        candidate_revision(placed).id,
        member(placed).placement_id,
        revised.resulting_item_version,
        placed.version,
        Kind.ACCESSIBILITY_FIT,
    )
    return SimpleNamespace(
        world=world,
        common=common,
        policy=policy,
        selection=selection,
        request=queries.ProgrammePlacementReadRequest(
            world.request.actor_id,
            item.organization_id,
            item.edition_id,
            uuid4(),
            "test",
        ),
    )


def preview(scope, kind=Kind.ACCESSIBILITY_FIT):
    return queries.preview_programme_placement_decision(
        scope.request,
        selection=replace(scope.selection, kind=kind),
        programme_authorizer=scope.policy,
        scheduling_authorizer=scope.world.policy,
    )


def apply(scope, planned=None, *, state=State.SATISFIED, retry=None, **overrides):
    planned = planned or preview(scope)
    intent = ProgrammePlacementDecisionIntent(
        **asdict(planned.selection),
        expected_decision_sequence=planned.decision_sequence,
        source_digest=planned.source_digest,
        state=state,
    )
    return commands.record_programme_placement_decision(
        **scope.common,
        intent=replace(intent, **overrides),
        idempotency_key=retry or uuid4(),
        correlation_id=uuid4(),
        programme_authorizer=scope.policy,
        scheduling_authorizer=scope.world.policy,
    )


@pytest.mark.parametrize("kind", list(Kind))
def test_decision_advances_only_its_own_stream_with_complete_atomic_evidence(
    assessed, kind
):
    planned = preview(assessed, kind)
    assert planned.decision_state == "absent"
    before = ProgrammeItem.objects.get(id=assessed.selection.item_id).aggregate_version
    result = apply(assessed, planned)
    assert result.item_version == before
    assert ProgrammeItem.objects.get(id=result.item_id).aggregate_version == before
    assert result.decision_sequence == 1
    decision = ProgrammePlacementDecision.objects.get(id=result.decision_id)
    receipt = ProgrammeCommandReceipt.objects.get(id=result.receipt_id)
    assert receipt.result_object_id == decision.id
    assert receipt.expected_version == receipt.resulting_item_version == before
    event = DomainEvent.objects.get(
        aggregate_id=decision.placement_id,
        aggregate_type=(
            "programme.accessibility_fit"
            if kind is Kind.ACCESSIBILITY_FIT
            else "programme.staffing_absence"
        ),
    )
    assert event.aggregate_version == 1
    assert "reason" not in event.payload
    assert OutboxMessage.objects.filter(event=event).exists()
    assert AuditEvent.objects.filter(id=event.causation_id).exists()
    assert preview(assessed, kind).decision_state == "satisfied"


def test_exact_retry_returns_historical_result_without_new_effects(assessed):
    planned, retry = preview(assessed), uuid4()
    result = apply(assessed, planned, retry=retry)
    before = (ProgrammePlacementDecision.objects.count(), DomainEvent.objects.count())
    assert apply(assessed, planned, retry=retry) == replace(result, replayed=True)
    assert before == (
        ProgrammePlacementDecision.objects.count(),
        DomainEvent.objects.count(),
    )
    with pytest.raises(ProgrammeIdempotencyConflictError):
        apply(assessed, planned, retry=retry, state=State.BLOCKED)


@pytest.mark.parametrize(
    "field", ["source_digest", "expected_decision_sequence", "expected_item_version"]
)
def test_stale_source_or_optimistic_version_writes_no_decision(assessed, field):
    with pytest.raises(ProgrammeVersionConflictError):
        apply(assessed, **{field: "0" * 64 if field == "source_digest" else 99})
    assert not ProgrammePlacementDecision.objects.exists()


def test_withdrawal_keeps_retained_provenance_after_candidate_changes(assessed):
    apply(assessed)
    planned = preview(assessed)
    place(
        assessed.world,
        intent=moved(assessed.world),
        version=assessed.selection.expected_candidate_version,
    )
    result = apply(assessed, planned, state=State.WITHDRAWN)
    row = ProgrammePlacementDecision.objects.get(id=result.decision_id)
    assert row.state == "withdrawn"
    assert row.sequence == 2
    assert row.source_digest == planned.source_digest
    assert row.candidate_revision_id == planned.selection.candidate_revision_id


def test_new_delivery_source_marks_existing_fit_stale(assessed):
    apply(assessed)
    revised = revise_programme_delivery(
        **assessed.common,
        item_id=assessed.selection.item_id,
        accessibility_delivery="Leave two wheelchair spaces near the front.",
        expected_version=assessed.selection.expected_item_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        authorizer=assessed.policy,
    )
    assessed.selection = replace(
        assessed.selection, expected_item_version=revised.resulting_item_version
    )
    assert preview(assessed).decision_state == "stale"


def test_last_effect_failure_rolls_back_decision_and_receipt(assessed, monkeypatch):
    before = ProgrammeCommandReceipt.objects.count()

    def fail(**_kwargs):
        raise RuntimeError("Synthetic placement effect unavailable")

    monkeypatch.setattr(commands, "_record_success", fail)
    with pytest.raises(RuntimeError, match="Synthetic placement effect unavailable"):
        apply(assessed)
    assert not ProgrammePlacementDecision.objects.exists()
    assert ProgrammeCommandReceipt.objects.count() == before


def test_current_profiles_deny_preview_and_command(assessed, monkeypatch):
    planned = preview(assessed)
    monkeypatch.setattr(queries, "profile_allows_adapter", lambda *_args: False)
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        preview(assessed)
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        apply(assessed, planned)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE programme_programmeplacementdecision SET reason = 'Changed'",
        "DELETE FROM programme_programmeplacementdecision",
        "TRUNCATE programme_programmeplacementdecision CASCADE",
    ],
)
def test_raw_dml_cannot_rewrite_or_erase_assessment(assessed, statement):
    result = apply(assessed)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('maru.authority_provenance_test_reset', 'off', true)"
        )
        with pytest.raises(DatabaseError), transaction.atomic():
            cursor.execute(statement)
    assert ProgrammePlacementDecision.objects.filter(id=result.decision_id).exists()


def test_closed_orm_writer_blocks_forged_assessment(assessed):
    with pytest.raises(ValidationError, match="registered command"):
        ProgrammePlacementDecision().save()


def test_populated_downgrade_fails_before_removing_schema_or_guards(assessed):
    result = apply(assessed)
    before = set(MigrationRecorder(connection).applied_migrations())
    with pytest.raises(RuntimeError, match="fix forward"):
        MigrationExecutor(connection).migrate(
            [("programme", "0012_staffing_downgrade_fence")]
        )
    assert set(MigrationRecorder(connection).applied_migrations()) == before
    assert ProgrammePlacementDecision.objects.filter(id=result.decision_id).exists()


@pytest.mark.usefixtures("restores_current_migration_graph")
def test_unused_placement_graph_reverses_and_reapplies_with_existing_sources(assessed):
    item_id = assessed.selection.item_id
    before = ProgrammeItem.objects.get(id=item_id).aggregate_version
    MigrationExecutor(connection).migrate(
        [("programme", "0012_staffing_downgrade_fence")]
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regclass('public.programme_programmeplacementdecision'), "
            "to_regprocedure('public.maru_guard_programme_placement_decision()')"
        )
        assert cursor.fetchone() == (None, None)
    assert ProgrammeItem.objects.get(id=item_id).aggregate_version == before
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    assert programme_database_integrity_is_ready()
    assert preview(assessed).decision_state == "absent"


@pytest.mark.parametrize(
    "patch",
    [
        {},
        {"sequence": 3},
        {"source_digest": "not a digest"},
        {"kind": "other"},
        {"state": "waived"},
        {"item_version": 999},
        {"space_selection_version": 999},
    ],
)
def test_raw_append_requires_exact_shape_and_new_reciprocal_evidence(assessed, patch):
    result = apply(assessed)
    values = {"id": str(uuid4()), "sequence": 2, **patch}
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "INSERT INTO programme_programmeplacementdecision "
            "SELECT (jsonb_populate_record(NULL::programme_programmeplacementdecision, "
            "to_jsonb(d) || %s::jsonb)).* FROM programme_programmeplacementdecision d "
            "WHERE d.id = %s",
            [json.dumps(values), result.decision_id],
        )
    assert ProgrammePlacementDecision.objects.count() == 1


def history(scope, through, **kwargs):
    return queries.load_programme_placement_decision_history(
        scope.request,
        item_id=scope.selection.item_id,
        placement_id=scope.selection.placement_id,
        kind=scope.selection.kind,
        through_sequence=through,
        authorizer=scope.policy,
        **kwargs,
    )


def test_history_keeps_fixed_ceiling_and_separate_rationale_authority(
    assessed, monkeypatch
):
    apply(assessed)
    first_page = history(assessed, 1)
    assert first_page.entries[0].reason == assessed.common["reason"]
    assert first_page.entries[0].actor_id == assessed.request.actor_id
    apply(assessed, preview(assessed), state=State.BLOCKED)
    assert history(assessed, 1) == first_page
    monkeypatch.setattr(queries, "PLACEMENT_HISTORY_PAGE_SIZE", 1)
    page = history(assessed, 2)
    assert page.next_after_sequence == 1
    final = history(assessed, 2, after_sequence=1)
    assert final.next_after_sequence is None
    assert final.entries[0].state == "blocked"
    original = assessed.policy.authorize
    monkeypatch.setattr(
        assessed.policy,
        "authorize",
        lambda **kwargs: replace(
            original(**kwargs),
            fields=frozenset({"delivery_information", "placement_decisions"}),
        ),
    )
    assert preview(assessed).decision_state == "blocked"
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        history(assessed, 1)


@pytest.mark.parametrize(
    ("through", "after"), [(0, 0), (2, 0), (1, 1), (True, 0), (1, -1), (1002, 0)]
)
def test_history_rejects_missing_or_invalid_ceiling(assessed, through, after):
    apply(assessed)
    with pytest.raises(ProgrammeUnavailableError):
        history(assessed, through, after_sequence=after)


def test_competing_assessments_cannot_both_use_the_same_sequence(assessed):
    planned = preview(assessed)
    barrier = Barrier(2)

    def attempt(_index):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return apply(assessed, planned)
        except ProgrammeVersionConflictError:
            return None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(attempt, range(2)))
    assert sum(result is not None for result in results) == 1
    assert ProgrammePlacementDecision.objects.count() == 1


def test_real_placement_schema_and_guards_match_readiness_contract(assessed):
    apply(assessed)
    assert programme_database_integrity_is_ready()


def test_ready_live_decisions_do_not_reopen_private_content_writes(assessed):
    actor = Account.objects.get(id=assessed.request.actor_id)
    CapabilityGrantFactory(
        organization_id=assessed.request.organization_id,
        edition_id=assessed.request.edition_id,
        principal_id=actor.id,
        capability_code="events.transition",
    )
    for lifecycle in ("preparing", "ready", "live"):
        transition_edition(
            organization_id=assessed.request.organization_id,
            edition_id=assessed.request.edition_id,
            to_state=lifecycle,
            actor=actor,
            reason="Synthetic operational decision boundary",
            correlation_id=uuid4(),
        )
        result = apply(assessed)
        assert result.item_version == assessed.selection.expected_item_version
        if lifecycle in ("ready", "live"):
            with pytest.raises(ProgrammeLifecycleConflictError):
                revise_programme_delivery(
                    **assessed.common,
                    item_id=assessed.selection.item_id,
                    expected_version=result.item_version,
                    accessibility_delivery="Forbidden private content rewrite",
                    idempotency_key=uuid4(),
                    correlation_id=uuid4(),
                    authorizer=assessed.policy,
                )
    transition_edition(
        organization_id=assessed.request.organization_id,
        edition_id=assessed.request.edition_id,
        to_state="closing",
        actor=actor,
        reason="Synthetic operational closure",
        correlation_id=uuid4(),
    )
    with pytest.raises(ProgrammeLifecycleConflictError):
        apply(assessed, planned=preview_before_closing(assessed))


def preview_before_closing(scope):
    # Closing still permits an authorized retained read; use original retained
    # source identity so command lifecycle, not a fresh candidate preview, is tested.
    previous = (
        ProgrammePlacementDecision.objects.filter(
            placement_id=scope.selection.placement_id,
        )
        .order_by("-sequence")
        .first()
    )
    return SimpleNamespace(
        selection=scope.selection,
        decision_sequence=previous.sequence,
        source_digest=previous.source_digest,
    )
