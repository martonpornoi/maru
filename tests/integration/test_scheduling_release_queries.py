"""Checked manifests respect exact history, native disclosure and read authority."""

from dataclasses import asdict, replace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from maru.audit.models import AuditEvent
from maru.programme.models import ProgrammeItem
from maru.programme.public_copy_commands import withdraw_programme_public_rendition
from maru.scheduling import planning_queries
from maru.scheduling import release_queries as queries
from maru.scheduling.authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_HISTORY,
    VIEW_PLANNING,
    SchedulingAuthorizationDeniedError,
)
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.models import (
    SchedulingReleaseArtifact,
    SchedulingReleaseDependencyChange,
)
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.scheduling.release_artifacts import ReleaseArtifactInvalidError
from tests.integration.test_scheduling_release_publication_commands import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_publication_commands import (
    approve,
    publish,
    withdraw,
)
from tests.integration.test_scheduling_release_publication_commands import (
    assessed as assessed,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_publication_commands import (
    capture_scope as capture_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_publication_commands import (
    preflight_scope as preflight_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_publication_commands import (
    release_scope as release_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_publication_commands import (
    review_scope as review_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_publication_commands import (
    world as world,  # noqa: PLC0414
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def load(scope, *, request=None, **overrides):
    return queries.load_programme_release_manifest(
        request
        or SchedulingReadRequest(
            scope.request.actor_id,
            scope.request.organization_id,
            scope.request.edition_id,
            uuid4(),
        ),
        **({"authorizer": scope.world.policy} | overrides),
    )


def test_current_manifest_is_complete_audited_and_minimized(review_scope):
    assert load(review_scope).state == "absent"
    published = publish(review_scope, approve(review_scope))
    manifest = load(review_scope)
    assert manifest.state == "available"
    assert manifest.release_id == published.object_id
    assert manifest.is_active
    assert manifest.pointer_version == 1
    assert len(manifest.selections) == 1
    assert set(asdict(manifest)) == {
        "state",
        "pointer_version",
        "release_id",
        "is_active",
        "selections",
    }
    assert (
        AuditEvent.objects.filter(
            operation="scheduling.query.release_manifest",
            capability_code=VIEW_PLANNING,
            outcome="allow",
        ).count()
        == 2
    )


def test_historical_manifest_uses_independent_history_authority(review_scope):
    first = publish(review_scope, approve(review_scope))
    review_scope.review_request = replace(
        review_scope.review_request, idempotency_key=uuid4()
    )
    second = publish(
        review_scope, approve(review_scope), prior=first.object_id, version=1
    )
    historical = load(review_scope, release_id=first.object_id)
    assert historical.state == "available"
    assert not historical.is_active
    assert historical.pointer_version == 2
    assert load(review_scope).release_id == second.object_id
    assert AuditEvent.objects.filter(
        operation="scheduling.query.release_manifest",
        capability_code=VIEW_HISTORY,
        outcome="allow",
    ).exists()


def test_whole_withdrawal_never_returns_retained_selections(review_scope):
    published = publish(review_scope, approve(review_scope))
    withdraw(review_scope, published)
    for options in ({}, {"release_id": published.object_id}):
        result = load(review_scope, **options)
        assert result.state == "withdrawn"
        assert result.selections == ()
        assert not result.is_active
        assert result.pointer_version == 2
    assert SchedulingReleaseArtifact.objects.filter(
        release_id=published.object_id
    ).exists()


def test_native_copy_withdrawal_invalidates_current_and_historical_manifest(
    review_scope,
):
    published = publish(review_scope, approve(review_scope))
    original = load(review_scope)
    selected = original.selections[0]
    item = ProgrammeItem.objects.get(id=review_scope.selection.item_id)
    withdraw_programme_public_rendition(
        actor_id=review_scope.request.actor_id,
        organization_id=review_scope.request.organization_id,
        edition_id=review_scope.request.edition_id,
        item_id=item.id,
        rendition_id=selected.public_rendition_id,
        expected_version=item.aggregate_version,
        reason="Withdraw the exact synthetic released copy",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=review_scope.policy,
    )
    for options in ({}, {"release_id": published.object_id}):
        result = load(review_scope, **options)
        assert result.state == "invalidated"
        assert result.selections == ()
        assert result.is_active  # Invalidation is not pointer replacement.


def test_manifest_fails_closed_if_required_artifact_verification_fails(review_scope):
    publish(review_scope, approve(review_scope))
    with (
        patch.object(
            queries,
            "verify_canonical_release_artifact",
            side_effect=ReleaseArtifactInvalidError,
        ),
        pytest.raises(SchedulingUnavailableError),
    ):
        load(review_scope)
    assert not AuditEvent.objects.filter(
        operation="scheduling.query.release_manifest", outcome="allow"
    ).exists()


def test_release_read_denies_before_loading_private_reference(review_scope):
    with (
        patch.object(queries, "_manifest") as loader,
        pytest.raises(SchedulingAuthorizationDeniedError),
    ):
        load(
            review_scope,
            release_id="not-an-identifier",
            authorizer=DEFAULT_SCHEDULING_AUTHORIZER,
        )
    loader.assert_not_called()


@pytest.mark.parametrize("field", ["organization_id", "edition_id"])
def test_release_read_denies_foreign_scope_before_manifest_load(review_scope, field):
    request = SchedulingReadRequest(
        review_scope.request.actor_id,
        review_scope.request.organization_id,
        review_scope.request.edition_id,
        uuid4(),
    )
    with (
        patch.object(queries, "_manifest") as loader,
        pytest.raises(SchedulingAuthorizationDeniedError),
    ):
        load(review_scope, request=replace(request, **{field: uuid4()}))
    loader.assert_not_called()


def test_failed_read_audit_releases_no_manifest(review_scope):
    with (
        patch.object(
            planning_queries,
            "append_audit",
            side_effect=RuntimeError("audit unavailable"),
        ),
        pytest.raises(RuntimeError, match="audit unavailable"),
    ):
        load(review_scope)


def test_absent_historical_release_is_uniformly_unavailable(review_scope):
    with pytest.raises(SchedulingUnavailableError):
        load(review_scope, release_id=uuid4())


def test_release_manifest_field_denial_precedes_reference_collection(review_scope):
    original = review_scope.world.policy.authorize

    def deny_field(**kwargs):
        return replace(original(**kwargs), fields=frozenset())

    with (
        patch.object(review_scope.world.policy, "authorize", deny_field),
        patch.object(queries, "_manifest") as loader,
        pytest.raises(SchedulingAuthorizationDeniedError),
    ):
        load(review_scope)
    loader.assert_not_called()


def test_final_read_reauthorization_withholds_an_already_collected_manifest(
    review_scope,
):
    policy = review_scope.world.policy
    policy.deny_at = policy.calls + 2
    with pytest.raises(SchedulingAuthorizationDeniedError):
        load(review_scope)
    assert not AuditEvent.objects.filter(
        operation="scheduling.query.release_manifest", outcome="allow"
    ).exists()
    assert AuditEvent.objects.filter(
        operation="scheduling.query.release_manifest", outcome="deny"
    ).exists()


def test_dependency_generations_and_ranges_share_one_complete_statement(review_scope):
    publish(review_scope, approve(review_scope))
    with CaptureQueriesContext(connection) as captured:
        assert load(review_scope).state == "available"
    statements = [
        row["sql"]
        for row in captured
        if 'FROM "scheduling_schedulingreleaseapprovaldependency"' in row["sql"]
    ]
    assert len(statements) == 1
    assert "COUNT(" in statements[0]
    assert "MIN(" in statements[0]
    assert "MAX(" in statements[0]


def test_checked_manifest_rejects_dependency_overflow(review_scope):
    publish(review_scope, approve(review_scope))
    with (
        patch.object(queries, "MAX_RELEASE_DEPENDENCY_USES", 1),
        pytest.raises(SchedulingUnavailableError),
    ):
        load(review_scope)


def test_missing_journal_read_is_unavailable_not_a_still_approved_manifest(
    review_scope,
):
    publish(review_scope, approve(review_scope))
    selected = load(review_scope).selections[0]
    item = ProgrammeItem.objects.get(id=review_scope.selection.item_id)
    withdraw_programme_public_rendition(
        actor_id=review_scope.request.actor_id,
        organization_id=item.organization_id,
        edition_id=item.edition_id,
        item_id=item.id,
        rendition_id=selected.public_rendition_id,
        expected_version=item.aggregate_version,
        reason="Synthetic missing-journal read after native withdrawal",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=review_scope.policy,
    )
    assert load(review_scope).state == "invalidated"
    missing = SchedulingReleaseDependencyChange.objects.none()
    # Fault only the read, not protected history or native mutation evidence.
    with (
        patch.object(
            SchedulingReleaseDependencyChange.objects, "filter", return_value=missing
        ),
        pytest.raises(SchedulingUnavailableError),
    ):
        load(review_scope)
