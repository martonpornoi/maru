"""Real dormant review commands retain exact native sources and immutable evidence."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction

from maru.audit.models import AuditEvent, AuditNativeMutationWitness
from maru.effects.models import DomainEvent, OutboxMessage
from maru.programme.release_inputs import ProgrammePlacementDecisionKind
from maru.scheduling import release_review_commands as commands
from maru.scheduling.authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    SchedulingAuthorizationDeniedError,
)
from maru.scheduling.command_support import (
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.scheduling.inputs import SchedulingCommandRequest
from maru.scheduling.models import (
    SchedulingRelease,
    SchedulingReleaseApproval,
    SchedulingReleaseApprovalDependency,
    SchedulingReleaseDependencyKey,
    SchedulingReleaseWarningAcknowledgement,
)
from maru.scheduling.release_inputs import ReleaseApprovalIntent, ReleaseWarningIntent
from tests.factories import AccountFactory, CapabilityGrantFactory
from tests.integration.test_programme_placement_decisions import apply, preview
from tests.integration.test_scheduling_evaluations import availability
from tests.integration.test_scheduling_release_capture import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_capture import (
    assessed as assessed,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_capture import (
    capture_scope as capture_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_capture import (
    preflight_scope as preflight_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_capture import (
    release_scope as release_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_capture import (
    world as world,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_preflight import load

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def review_scope(capture_scope):
    return reviewable_scope(capture_scope)


def reviewable_scope(capture_scope):
    reviewer = AccountFactory()
    CapabilityGrantFactory(
        organization_id=capture_scope.request.organization_id,
        edition_id=capture_scope.request.edition_id,
        principal=reviewer,
        capability_code="workforce.view_shifts",
    )
    capture_scope.review_request = SchedulingCommandRequest(
        reviewer.id,
        capture_scope.request.organization_id,
        capture_scope.request.edition_id,
        uuid4(),
        uuid4(),
        "Independently review the synthetic timetable",
        "test",
    )
    return capture_scope


def approve(scope, *, request=None, intent=None, **overrides):
    return commands.approve_programme_release(
        request or scope.review_request,
        intent=intent or ReleaseApprovalIntent(scope.release_selection),
        **(
            {
                "programme_authorizer": scope.policy,
                "scheduling_authorizer": scope.world.policy,
            }
            | overrides
        ),
    )


def test_approval_commits_complete_review_receipt_audit_and_dormant_event(review_scope):
    result = approve(review_scope)
    approval = SchedulingReleaseApproval.objects.get(id=result.object_id)
    assert approval.actor_id == review_scope.review_request.actor_id
    assert approval.command_receipt_id == result.receipt_id
    assert approval.placements.count() == approval.placement_count == 1
    assert approval.dependencies.count() == approval.dependency_count > 10
    assert approval.warning_ids == []
    event = DomainEvent.objects.get(
        event_name="scheduling.release.changed.v1",
        aggregate_version=result.control_version,
    )
    audit = AuditEvent.objects.get(id=event.causation_id)
    assert audit.operation == "scheduling.command.release_approve"
    assert audit.target_id == approval.id
    assert AuditNativeMutationWitness.objects.filter(audit_event_id=audit.id).exists()
    assert OutboxMessage.objects.filter(event_id=event.id).count() == 1
    assert not SchedulingRelease.objects.exists()
    replay = approve(review_scope)
    assert replay == replace(result, replayed=True)
    assert SchedulingReleaseApproval.objects.count() == 1
    assert DomainEvent.objects.filter(event_name=event.event_name).count() == 1


def test_retry_reauthorizes_without_rewriting_retained_approval(review_scope):
    approve(review_scope)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        approve(review_scope, scheduling_authorizer=DEFAULT_SCHEDULING_AUTHORIZER)
    assert SchedulingReleaseApproval.objects.count() == 1


def test_planner_cannot_approve_own_retained_work(review_scope):
    with pytest.raises(SchedulingAuthorizationDeniedError):
        approve(
            review_scope,
            request=replace(
                review_scope.review_request, actor_id=review_scope.request.actor_id
            ),
        )
    assert not SchedulingReleaseApproval.objects.exists()
    assert not SchedulingReleaseDependencyKey.objects.exists()


def test_database_independence_is_not_a_caller_authorship_assertion(review_scope):
    with (
        patch.object(
            commands,
            "_load_release_authorship",
            return_value=SimpleNamespace(author_ids=frozenset()),
        ),
        pytest.raises(IntegrityError, match="independent current manifest"),
    ):
        approve(
            review_scope,
            request=replace(
                review_scope.review_request, actor_id=review_scope.request.actor_id
            ),
        )
    assert not SchedulingReleaseApproval.objects.exists()


@pytest.mark.parametrize("broken", ["omit", "generation"])
def test_database_rejects_partial_or_invented_generation_capture(review_scope, broken):
    original = commands._capture_release_generations

    def incomplete(sources):
        captured = original(sources)
        if broken == "omit":
            return captured[:-1]
        return (
            replace(captured[0], generation=captured[0].generation + 1),
            *captured[1:],
        )

    with (
        patch.object(commands, "_capture_release_generations", incomplete),
        pytest.raises(IntegrityError, match="complete current native dependencies"),
    ):
        approve(review_scope)
    assert not SchedulingReleaseApproval.objects.exists()
    assert not SchedulingReleaseDependencyKey.objects.exists()
    assert not DomainEvent.objects.filter(
        event_name="scheduling.release.changed.v1"
    ).exists()


def test_stale_snapshot_cannot_create_approval(review_scope):
    with pytest.raises(SchedulingUnavailableError):
        approve(
            review_scope,
            intent=ReleaseApprovalIntent(
                replace(review_scope.release_selection, source_snapshot_digest="0" * 64)
            ),
        )
    assert not SchedulingReleaseApproval.objects.exists()


def test_late_audit_failure_rolls_back_review_and_tracking(review_scope):
    with (
        patch.object(
            commands,
            "_capture_release_generations",
            wraps=commands._capture_release_generations,
        ) as captured,
        patch(
            "maru.audit.mutation_evidence.append_audit",
            side_effect=RuntimeError("Synthetic audit failure"),
        ),
        pytest.raises(RuntimeError, match="Synthetic audit failure"),
    ):
        approve(review_scope)
    captured.assert_called_once()
    assert not SchedulingReleaseApproval.objects.exists()
    assert not SchedulingReleaseDependencyKey.objects.exists()


def test_committed_approval_cannot_gain_a_later_dependency(review_scope):
    result = approve(review_scope)
    count = SchedulingReleaseApprovalDependency.objects.count()
    with (  # noqa: PT012 - prove the attempted insert before deferred commit rejection.
        pytest.raises(IntegrityError, match="exact new native command"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "INSERT INTO public.scheduling_schedulingreleaseapprovaldependency "
            "(id, created_at, updated_at, organization_id, edition_id, approval_id, "
            "dependency_id, approval_placement_id, captured_generation, horizon, "
            "operational_ends_at) "
            "SELECT %s, now(), now(), row.organization_id, row.edition_id, "
            "row.approval_id, row.dependency_id, row.approval_placement_id, "
            "row.captured_generation, 'disclosure', NULL "
            "FROM public.scheduling_schedulingreleaseapprovaldependency row "
            "JOIN public.scheduling_schedulingreleasedependencykey dependency "
            "ON dependency.id = row.dependency_id "
            "WHERE row.approval_id = %s AND row.horizon = 'operational' "
            "AND dependency.kind = 'identity_account' LIMIT 1",
            [uuid4(), result.object_id],
        )
        assert cursor.rowcount == 1
    assert SchedulingReleaseApprovalDependency.objects.count() == count


def test_exact_warning_must_be_acknowledged_before_independent_approval(review_scope):
    changed = availability(review_scope.world, preference=True)
    review_scope.selection = replace(
        review_scope.selection, expected_item_version=changed.resulting_item_version
    )
    assert load(review_scope).eligibility.stale_checks == ("staffing",)
    apply(
        review_scope,
        preview(review_scope, ProgrammePlacementDecisionKind.STAFFING_NOT_REQUIRED),
    )
    preflight = load(review_scope)
    assert not preflight.eligibility.stale_checks, preflight.eligibility
    assert not preflight.eligibility.blocked_checks, preflight.eligibility
    review_scope.release_selection = replace(
        review_scope.release_selection, source_snapshot_digest=preflight.snapshot_digest
    )
    (warning,) = preflight.findings
    assert warning.severity == "warning"
    with pytest.raises(SchedulingVersionConflictError):
        approve(review_scope)
    acknowledgement = commands.acknowledge_programme_release_warning(
        review_scope.review_request,
        intent=ReleaseWarningIntent(
            review_scope.release_selection, warning.fingerprint
        ),
        programme_authorizer=review_scope.policy,
        scheduling_authorizer=review_scope.world.policy,
    )
    retained = SchedulingReleaseWarningAcknowledgement.objects.get(
        id=acknowledgement.object_id
    )
    assert retained.reason == review_scope.review_request.reason
    approved = approve(
        review_scope,
        request=replace(review_scope.review_request, idempotency_key=uuid4()),
        intent=ReleaseApprovalIntent(
            review_scope.release_selection, (acknowledgement.object_id,)
        ),
    )
    assert SchedulingReleaseApproval.objects.get(id=approved.object_id).warning_ids == [
        acknowledgement.object_id
    ]


def test_unrelated_warning_identifier_never_substitutes_for_evidence(review_scope):
    with pytest.raises(SchedulingVersionConflictError):
        approve(
            review_scope,
            intent=ReleaseApprovalIntent(review_scope.release_selection, (uuid4(),)),
        )
    assert not SchedulingReleaseApproval.objects.exists()


@pytest.mark.parametrize("field", ["organization_id", "edition_id"])
def test_foreign_request_never_loads_release_sources(review_scope, field):
    with (
        patch.object(commands, "_load_release_sources") as sources,
        pytest.raises(SchedulingAuthorizationDeniedError),
    ):
        approve(
            review_scope,
            request=replace(review_scope.review_request, **{field: uuid4()}),
        )
    sources.assert_not_called()


def test_blocked_current_source_cannot_be_approved(review_scope):
    availability(review_scope.world, state="withdrawn")
    current = load(review_scope)
    assert not current.eligibility.eligible_for_review
    with pytest.raises(SchedulingVersionConflictError):
        approve(
            review_scope,
            intent=ReleaseApprovalIntent(
                replace(
                    review_scope.release_selection,
                    source_snapshot_digest=current.snapshot_digest,
                )
            ),
        )
    assert not SchedulingReleaseApproval.objects.exists()
