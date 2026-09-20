"""Native archive history keeps withdrawn identities separate from live output."""

import json
from dataclasses import replace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator

from maru.audit.models import AuditEvent
from maru.programme import archive_authorization
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.scheduling import exit_queries as archive
from maru.scheduling import release_queries
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.exit_serialization import serialize_scheduling_exit_owner
from maru.scheduling.planning_queries import SchedulingReadRequest
from tests.integration.test_programme_queries import _TrustedAuthorizer
from tests.integration.test_scheduling_release_publication_commands import (
    admitted as admitted,  # noqa: PLC0414 -- pytest fixture registration.
)
from tests.integration.test_scheduling_release_publication_commands import (
    approve,
    publish,
    withdraw,
)
from tests.integration.test_scheduling_release_publication_commands import (
    assessed as assessed,  # noqa: PLC0414 -- pytest fixture registration.
)
from tests.integration.test_scheduling_release_publication_commands import (
    capture_scope as capture_scope,  # noqa: PLC0414 -- pytest fixture registration.
)
from tests.integration.test_scheduling_release_publication_commands import (
    preflight_scope as preflight_scope,  # noqa: PLC0414 -- pytest fixture registration.
)
from tests.integration.test_scheduling_release_publication_commands import (
    release_scope as release_scope,  # noqa: PLC0414 -- pytest fixture registration.
)
from tests.integration.test_scheduling_release_publication_commands import (
    review_scope as review_scope,  # noqa: PLC0414 -- pytest fixture registration.
)
from tests.integration.test_scheduling_release_publication_commands import (
    world as world,  # noqa: PLC0414 -- pytest fixture registration.
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def archive_scope(review_scope, monkeypatch):
    monkeypatch.setattr(
        archive_authorization, "profile_allows_adapter", lambda *_: True
    )
    request = SchedulingReadRequest(
        review_scope.request.actor_id,
        review_scope.request.organization_id,
        review_scope.request.edition_id,
        uuid4(),
    )
    return (
        review_scope,
        request,
        {
            "authorizer": review_scope.world.policy,
            "programme_authorizer": _TrustedAuthorizer(),
        },
    )


def test_native_archive_retains_published_and_withdrawn_verified_identities(
    archive_scope,
):
    scope, request, args = archive_scope
    published = publish(scope, approve(scope))
    current = archive.load_scheduling_exit_owner(request, **args)
    assert current.pointer.active_release_id == published.object_id
    assert len(current.releases) == 1
    assert current.releases[0].release_id == published.object_id
    assert current.manifests
    assert current.day_revisions
    assert current.occurrence_revisions
    assert sum(row.version for row in current.planning.candidates) == len(
        current.manifests
    )
    withdraw(scope, published)
    withdrawn = archive.load_scheduling_exit_owner(request, **args)
    assert withdrawn.pointer.active_release_id is None
    assert withdrawn.pointer.version == 2
    assert [entry.version for entry in withdrawn.release_history] == [2, 1]
    assert withdrawn.releases == current.releases
    section = serialize_scheduling_exit_owner(withdrawn)
    document = json.loads(section.data)
    Draft202012Validator(json.loads(section.schema)).validate(document)
    assert (
        document["evidence"]["releases"][0]["artifact"]["payload"].encode()
        == withdrawn.releases[0].artifact.payload
    )
    ordinary = release_queries.load_programme_release_manifest(
        request, release_id=published.object_id, authorizer=scope.world.policy
    )
    assert ordinary.state == "withdrawn"
    assert ordinary.selections == ()
    assert (
        AuditEvent.objects.filter(
            operation="scheduling.query.exit_owner", outcome="allow"
        ).count()
        == 2
    )


def test_native_archive_corrupt_artifact_refuses_success(archive_scope, monkeypatch):
    scope, request, args = archive_scope
    publish(scope, approve(scope))
    monkeypatch.setattr(
        archive,
        "verify_canonical_release_artifact",
        Mock(side_effect=archive.ReleaseArtifactInvalidError()),
    )
    with pytest.raises(archive.SchedulingUnavailableError):
        archive.load_scheduling_exit_owner(request, **args)
    assert not AuditEvent.objects.filter(
        operation="scheduling.query.exit_owner", outcome="allow"
    ).exists()


@pytest.mark.parametrize("field", ["organization_id", "edition_id"])
def test_native_archive_exact_scope_denial(archive_scope, field):
    _scope, request, args = archive_scope
    with pytest.raises(
        (ProgrammeAuthorizationDeniedError, SchedulingAuthorizationDeniedError)
    ):
        archive.load_scheduling_exit_owner(replace(request, **{field: uuid4()}), **args)


def test_native_archive_extra_purpose_cannot_replace_scheduling_policy(archive_scope):
    scope, request, args = archive_scope
    scope.world.policy.deny_at = scope.world.policy.calls + 1
    with pytest.raises(SchedulingAuthorizationDeniedError):
        archive.load_scheduling_exit_owner(request, **args)
