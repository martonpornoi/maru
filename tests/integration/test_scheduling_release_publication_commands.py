"""Atomic publication never exposes a pointer before exact verified canonical bytes."""

import hashlib
from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction

from maru.effects.models import DomainEvent
from maru.scheduling import release_publication_commands as commands
from maru.scheduling.authorization import (
    APPROVE_RELEASE,
    SchedulingAuthorizationDeniedError,
)
from maru.scheduling.command_support import SchedulingVersionConflictError
from maru.scheduling.models import (
    SchedulingRelease,
    SchedulingReleaseApproval,
    SchedulingReleaseArtifact,
    SchedulingReleasePointer,
    SchedulingReleaseWithdrawal,
)
from maru.scheduling.release_artifacts import ReleaseArtifactInvalidError
from maru.scheduling.release_inputs import (
    ReleasePublicationIntent,
    ReleaseWithdrawalIntent,
)
from tests.integration.test_scheduling_release_review_commands import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_review_commands import approve
from tests.integration.test_scheduling_release_review_commands import (
    assessed as assessed,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_review_commands import (
    capture_scope as capture_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_review_commands import (
    preflight_scope as preflight_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_review_commands import (
    release_scope as release_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_review_commands import (
    review_scope as review_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_review_commands import (
    world as world,  # noqa: PLC0414
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def request(scope):
    return replace(
        scope.review_request,
        actor_id=scope.request.actor_id,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        reason="Publish the independently reviewed synthetic timetable",
    )


def publish(scope, approval, *, prior=None, version=0, attribution=None):
    return commands.publish_programme_release(
        attribution or request(scope),
        intent=ReleasePublicationIntent(
            approval.object_id,
            prior,
            version,
            scope.release_selection.source_snapshot_digest,
        ),
        programme_authorizer=scope.policy,
        scheduling_authorizer=scope.world.policy,
    )


def withdraw(scope, release, *, version=None, attribution=None):
    return commands.withdraw_programme_release(
        attribution or request(scope),
        intent=ReleaseWithdrawalIntent(release.object_id, version or release.version),
        scheduling_authorizer=scope.world.policy,
    )


def test_release_and_withdrawal_preserve_artifact_and_monotonic_retry_history(
    review_scope,
):
    approved = approve(review_scope)
    attribution = request(review_scope)
    published = publish(review_scope, approved, attribution=attribution)
    pointer = SchedulingReleasePointer.objects.get(
        edition_id=review_scope.request.edition_id
    )
    artifact = SchedulingReleaseArtifact.objects.get(release_id=published.object_id)
    assert pointer.active_release_id == published.object_id
    assert pointer.version == published.version == 1
    assert artifact.payload
    assert len(artifact.payload) == artifact.byte_length
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT public.maru_scheduling_release_artifact_is_exact(%s)",
            [published.object_id],
        )
        assert cursor.fetchone() == (True,)
    assert publish(review_scope, approved, attribution=attribution) == replace(
        published, replayed=True
    )
    withdrawal_actor = request(review_scope)
    withdrawn = withdraw(review_scope, published, attribution=withdrawal_actor)
    pointer.refresh_from_db()
    assert pointer.active_release_id is None
    assert pointer.version == withdrawn.version == 2
    assert withdraw(review_scope, published, attribution=withdrawal_actor) == replace(
        withdrawn, replayed=True
    )
    assert (
        SchedulingRelease.objects.count()
        == SchedulingReleaseArtifact.objects.count()
        == 1
    )
    assert SchedulingReleaseWithdrawal.objects.count() == 1
    assert (
        SchedulingReleaseArtifact.objects.get(id=artifact.id).payload
        == artifact.payload
    )
    assert (
        DomainEvent.objects.filter(event_name="scheduling.release.changed.v1").count()
        == 3
    )


def test_replacement_and_post_withdrawal_publication_do_not_reset_history(review_scope):
    first = publish(review_scope, approve(review_scope))
    review_scope.review_request = replace(
        review_scope.review_request, idempotency_key=uuid4()
    )
    second = publish(
        review_scope, approve(review_scope), prior=first.object_id, version=1
    )
    second_row = SchedulingRelease.objects.get(id=second.object_id)
    assert second_row.previous_release_id == first.object_id
    assert (
        second_row.added_count,
        second_row.changed_count,
        second_row.removed_count,
    ) == (0, 0, 0)
    withdraw(review_scope, second)
    review_scope.review_request = replace(
        review_scope.review_request, idempotency_key=uuid4()
    )
    third = publish(review_scope, approve(review_scope), version=3)
    assert third.version == 4
    assert SchedulingRelease.objects.get(id=third.object_id).added_count == 1
    assert SchedulingRelease.objects.count() == 3


def test_approver_cannot_publish_same_approval(review_scope):
    approved = approve(review_scope)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        publish(
            review_scope,
            approved,
            attribution=replace(review_scope.review_request, idempotency_key=uuid4()),
        )
    assert not SchedulingReleasePointer.objects.exists()


@pytest.mark.parametrize("failure", ["artifact", "verify", "audit"])
@pytest.mark.parametrize("has_prior_release", [False, True])
def test_publication_failure_preserves_prior_release_or_initial_absence(
    review_scope, failure, has_prior_release
):
    prior = None
    if has_prior_release:
        prior = publish(review_scope, approve(review_scope))
        prior_bytes = bytes(SchedulingReleaseArtifact.objects.get().payload)
        review_scope.review_request = replace(
            review_scope.review_request, idempotency_key=uuid4()
        )
    approved = approve(review_scope)
    target = {
        "artifact": (
            "maru.scheduling.release_publication_commands."
            "prepare_canonical_release_artifact"
        ),
        "verify": (
            "maru.scheduling.release_publication_commands."
            "verify_canonical_release_artifact"
        ),
        "audit": "maru.audit.mutation_evidence.append_audit",
    }[failure]
    with (
        patch(target, side_effect=RuntimeError("Synthetic publication failure")),
        pytest.raises(RuntimeError, match="Synthetic publication failure"),
    ):
        publish(
            review_scope,
            approved,
            prior=prior.object_id if prior else None,
            version=1 if prior else 0,
        )
    assert SchedulingReleaseApproval.objects.count() == (2 if prior else 1)
    if prior:
        assert SchedulingRelease.objects.get().id == prior.object_id
        assert bytes(SchedulingReleaseArtifact.objects.get().payload) == prior_bytes
        pointer = SchedulingReleasePointer.objects.get()
        assert pointer.active_release_id == prior.object_id
        assert pointer.version == 1
    else:
        assert not SchedulingRelease.objects.exists()
        assert not SchedulingReleaseArtifact.objects.exists()
        assert not SchedulingReleasePointer.objects.exists()


def test_database_rejects_missing_artifact_before_pointer_can_be_written(review_scope):
    approved = approve(review_scope)
    with (
        patch.object(SchedulingReleaseArtifact.objects, "create"),
        pytest.raises(IntegrityError, match="verified exact artifact"),
    ):
        publish(review_scope, approved)
    assert not SchedulingReleasePointer.objects.exists()
    assert not SchedulingRelease.objects.exists()


def test_semantic_verifier_rejects_changed_bytes_even_with_preparation_result(
    review_scope,
):
    approved = approve(review_scope)
    original = commands.prepare_canonical_release_artifact

    def wrong(**arguments):
        artifact = original(**arguments)
        return replace(artifact, payload=artifact.payload + b" ")

    with (
        patch.object(commands, "prepare_canonical_release_artifact", wrong),
        pytest.raises(ReleaseArtifactInvalidError),
    ):
        publish(review_scope, approved)
    assert not SchedulingRelease.objects.exists()


def test_stale_pointer_cannot_replace_or_withdraw_current_release(review_scope):
    first = publish(review_scope, approve(review_scope))
    review_scope.review_request = replace(
        review_scope.review_request, idempotency_key=uuid4()
    )
    second_approval = approve(review_scope)
    with pytest.raises(SchedulingVersionConflictError):
        publish(review_scope, second_approval)
    with pytest.raises(SchedulingVersionConflictError):
        withdraw(review_scope, first, version=2)
    assert SchedulingRelease.objects.count() == 1
    assert SchedulingReleasePointer.objects.get().active_release_id == first.object_id


def test_pointer_cannot_be_cleared_by_raw_dml_without_withdrawal(review_scope):
    first = publish(review_scope, approve(review_scope))
    with (
        pytest.raises(IntegrityError, match="deliberate withdrawal"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE public.scheduling_schedulingreleasepointer "
            "SET active_release_id = NULL, version = 2 WHERE active_release_id = %s",
            [first.object_id],
        )
    assert SchedulingReleasePointer.objects.get().active_release_id == first.object_id


def test_publisher_authority_does_not_substitute_for_revoked_approver_authority(
    review_scope,
):
    approved = approve(review_scope)
    original = review_scope.world.policy.authorize

    def revoked(**arguments):
        decision = original(**arguments)
        if (
            arguments["principal_id"] == review_scope.review_request.actor_id
            and arguments["capability_code"] == APPROVE_RELEASE
        ):
            return replace(decision, allowed=False)
        return decision

    with (
        patch.object(review_scope.world.policy, "authorize", revoked),
        pytest.raises(SchedulingAuthorizationDeniedError),
    ):
        publish(review_scope, approved)
    assert not SchedulingRelease.objects.exists()


def test_database_semantic_check_rejects_changed_bytes_with_recomputed_checksum(
    review_scope,
):
    approved = approve(review_scope)
    original = commands.prepare_canonical_release_artifact

    def tampered(**arguments):
        artifact = original(**arguments)
        payload = artifact.payload.replace(
            str(approved.object_id).encode(), str(uuid4()).encode()
        )
        return replace(
            artifact,
            payload=payload,
            byte_length=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    with (
        patch.object(commands, "prepare_canonical_release_artifact", tampered),
        patch.object(commands, "verify_canonical_release_artifact"),
        pytest.raises(IntegrityError, match="verified exact artifact"),
    ):
        publish(review_scope, approved)
    assert not SchedulingRelease.objects.exists()
    assert not SchedulingReleaseArtifact.objects.exists()
    assert not SchedulingReleasePointer.objects.exists()
