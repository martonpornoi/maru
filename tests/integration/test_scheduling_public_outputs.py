"""Public output uses genuine admission and exact copy, without private layers."""

from dataclasses import asdict, replace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent, OutboxMessage
from maru.programme import output_queries as programme_outputs
from maru.programme.commands import approve_programme_public_rendition
from maru.programme.models import (
    ProgrammeItem,
    ProgrammePublicRendition,
    ProgrammeWorkingRevision,
)
from maru.programme.public_copy_commands import withdraw_programme_public_rendition
from maru.programme.queries import ProgrammeQueryUnavailableError
from maru.scheduling import output_queries as outputs
from maru.scheduling import public_release_references as references
from maru.scheduling import release_queries
from maru.scheduling.adoption import SCHEDULING_PUBLIC_RELEASE_ADAPTER
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.release_artifacts import ReleaseArtifactInvalidError
from maru.venues import programme_output_queries as room_outputs
from maru.venues.models import EditionSpaceSelection
from maru.venues.scheduling_queries import VenueSchedulingSourceUnavailableError
from tests.integration.test_scheduling_release_queries import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import approve, publish, withdraw
from tests.integration.test_scheduling_release_queries import (
    assessed as assessed,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import (
    capture_scope as capture_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import (
    preflight_scope as preflight_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import (
    release_scope as release_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import (
    review_scope as review_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_queries import (
    world as world,  # noqa: PLC0414
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def scope_arguments(scope):
    return {
        "organization_id": scope.request.organization_id,
        "edition_id": scope.request.edition_id,
    }


@pytest.fixture
def public_scope(review_scope, monkeypatch):
    # Only the new dormant public adapter is admitted, never a planner policy.
    monkeypatch.setattr(
        references,
        "profile_allows_adapter",
        lambda _code, _version, adapter: adapter == SCHEDULING_PUBLIC_RELEASE_ADAPTER,
    )
    return review_scope


def load(scope):
    return outputs.load_public_programme_timetable(**scope_arguments(scope))


def end_copy(scope, rendition_id):
    item = ProgrammeItem.objects.get(id=scope.selection.item_id)
    return withdraw_programme_public_rendition(
        **scope.common,
        item_id=item.id,
        rendition_id=rendition_id,
        expected_version=item.aggregate_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        authorizer=scope.policy,
    )


@pytest.mark.parametrize("output_format", ["html", "print", "json", "calendar"])
def test_actual_http_adapter_rechecks_native_withdrawal_in_every_format(
    public_scope, settings, client, output_format
):
    settings.ROOT_URLCONF = "maru.scheduling.output_urls"
    published = publish(public_scope, approve(public_scope))
    url = (
        f"/programme/{public_scope.request.organization_id}/"
        f"{public_scope.request.edition_id}/timetable/?format={output_format}"
    )
    before = client.get(url)
    assert before.status_code == 200
    assert b"Synthetic public opening" in before.content
    assert str(published.object_id).encode() in before.content
    assert "no-store" in before["Cache-Control"]
    withdraw(public_scope, published)
    after = client.get(url)
    assert after.status_code == (409 if output_format == "calendar" else 200)
    assert b"Synthetic public opening" not in after.content
    assert "no-store" in after["Cache-Control"]
    assert after["X-Content-Type-Options"] == "nosniff"


def test_public_output_is_complete_minimized_and_has_no_visitor_or_attendee_effects(
    public_scope,
):
    published = publish(public_scope, approve(public_scope))
    before = (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )
    with CaptureQueriesContext(connection) as captured:
        result = load(public_scope)
    assert result.state == "available"
    assert result.release_id == published.object_id
    assert result.pointer_version == 1
    assert result.published_at <= result.checked_at
    assert len(result.entries) == 1
    (entry,) = result.entries
    assert entry.copy.title == "Synthetic public opening"
    assert entry.starts_at == public_scope.world.placement.envelope.effective_starts_at
    assert entry.ends_at == public_scope.world.placement.envelope.effective_ends_at
    space = EditionSpaceSelection.objects.get(id=entry.room.space_id)
    assert entry.room.room_name == space.local_name
    assert entry.room.space_version == space.aggregate_version
    assert set(asdict(entry)) == {
        "occurrence_id",
        "copy",
        "room",
        "day_id",
        "day_starts_at",
        "day_ends_at",
        "starts_at",
        "ends_at",
    }
    assert set(asdict(entry.copy)) == {
        "rendition_id",
        "title",
        "summary",
        "content_note",
    }
    assert before == (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )
    statements = "\n".join(row["sql"] for row in captured)
    for excluded in (
        'FROM "registration_',
        'FROM "participation_',
        'FROM "payments_',
        'FROM "programme_programmehost',
        'FROM "programme_programmeworkingrevision"',
        'FROM "programme_programmedeliveryrevision"',
        'FROM "workforce_shift',
    ):
        assert excluded not in statements
    copy_selects = [
        row["sql"]
        for row in captured
        if 'FROM "programme_programmepublicrendition"' in row["sql"]
    ]
    assert len(copy_selects) == 1
    for private in (
        "review_reason",
        "reviewed_by_id",
        "reviewed_at",
        "source_working_revision_id",
    ):
        assert private not in copy_selects[0]
    room_selects = [
        row["sql"]
        for row in captured
        if 'FROM "venues_editionspaceselection"' in row["sql"]
    ]
    assert len(room_selects) == 1
    for private in (
        "opening_restrictions",
        "responsible_department_id",
        "public_contact_override",
    ):
        assert private not in room_selects[0]


def test_new_reviewed_copy_never_silently_replaces_exact_released_copy(public_scope):
    publish(public_scope, approve(public_scope))
    before = load(public_scope)
    item = ProgrammeItem.objects.get(id=public_scope.selection.item_id)
    working = ProgrammeWorkingRevision.objects.filter(item=item).latest("sequence")
    latest = approve_programme_public_rendition(
        **public_scope.common,
        item_id=item.id,
        source_working_revision_id=working.id,
        public_title="Different later reviewed copy",
        expected_version=item.aggregate_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        authorizer=public_scope.policy,
    )
    after = load(public_scope)
    assert after.entries == before.entries
    assert after.entries[0].copy.rendition_id != latest.result_object_id
    end_copy(public_scope, before.entries[0].copy.rendition_id)
    assert load(public_scope).state == "invalidated"
    assert load(public_scope).entries == ()
    assert ProgrammePublicRendition.objects.filter(id=latest.result_object_id).exists()


def test_absent_and_withdrawn_outputs_have_no_normal_rows(public_scope):
    assert load(public_scope).state == "absent"
    assert load(public_scope).entries == ()
    released = publish(public_scope, approve(public_scope))
    withdraw(public_scope, released)
    result = load(public_scope)
    assert result.state == "withdrawn"
    assert result.pointer_version == 2
    assert result.release_id is result.published_at is None
    assert result.entries == ()


def test_unadopted_public_output_denies_before_manifest_and_owner_reads(review_scope):
    with (
        patch.object(references, "_manifest") as manifest,
        patch.object(outputs, "load_released_programme_copy") as copy,
        pytest.raises(SchedulingAuthorizationDeniedError),
    ):
        load(review_scope)
    manifest.assert_not_called()
    copy.assert_not_called()


@pytest.mark.parametrize("field", ["organization_id", "edition_id"])
def test_public_scope_must_be_exact_before_release_discovery(public_scope, field):
    with (
        patch.object(references, "_manifest") as manifest,
        pytest.raises(SchedulingAuthorizationDeniedError),
    ):
        outputs.load_public_programme_timetable(
            **(scope_arguments(public_scope) | {field: uuid4()})
        )
    manifest.assert_not_called()


@pytest.mark.parametrize("value", [None, "not-a-uuid", 1, True])
def test_public_scope_rejects_malformed_identifiers_before_lookup(value):
    with patch.object(references, "_admit") as admit, pytest.raises(ValidationError):
        outputs.load_public_programme_timetable(
            organization_id=value, edition_id=uuid4()
        )
    admit.assert_not_called()


@pytest.mark.parametrize(
    ("loader", "error"),
    [
        (
            programme_outputs.load_released_programme_copy,
            ProgrammeQueryUnavailableError,
        ),
        (
            room_outputs.load_released_room_wayfinding,
            VenueSchedulingSourceUnavailableError,
        ),
    ],
)
def test_owner_reads_independently_reject_unreleased_and_wrong_release_sources(
    public_scope, loader, error
):
    arguments = scope_arguments(public_scope) | {"expected_release_id": uuid4()}
    with pytest.raises(error):
        loader(**arguments)
    publish(public_scope, approve(public_scope))
    with pytest.raises(error):
        loader(**arguments)


def test_missing_canonical_evidence_never_falls_back_to_owner_content(public_scope):
    publish(public_scope, approve(public_scope))
    with (
        patch.object(
            release_queries,
            "verify_canonical_release_artifact",
            side_effect=ReleaseArtifactInvalidError,
        ),
        patch.object(outputs, "load_released_programme_copy") as owner,
        pytest.raises(SchedulingUnavailableError),
    ):
        load(public_scope)
    owner.assert_not_called()


@pytest.mark.parametrize(
    "owner", ["load_released_programme_copy", "load_released_room_wayfinding"]
)
def test_missing_owner_result_is_unavailable_not_partial_timetable(public_scope, owner):
    publish(public_scope, approve(public_scope))
    with (
        patch.object(outputs, owner, return_value=()),
        pytest.raises(SchedulingUnavailableError),
    ):
        load(public_scope)


def test_public_projection_rechecks_release_after_owner_reads(public_scope):
    publish(public_scope, approve(public_scope))
    original = references.load_public_release_reference(**scope_arguments(public_scope))
    changed = replace(original, manifest=replace(original.manifest, pointer_version=2))
    with (
        patch.object(
            outputs, "load_public_release_reference", side_effect=(original, changed)
        ),
        pytest.raises(SchedulingUnavailableError),
    ):
        load(public_scope)


def test_public_reference_rechecks_profile_and_enforces_complete_geometry(public_scope):
    publish(public_scope, approve(public_scope))
    with (
        patch.object(
            references, "profile_allows_adapter", side_effect=(True, True, False)
        ),
        pytest.raises(SchedulingAuthorizationDeniedError),
    ):
        references.load_public_release_reference(**scope_arguments(public_scope))
    with (
        patch.object(references, "MAX_OCCURRENCES", 0),
        pytest.raises(SchedulingUnavailableError),
    ):
        load(public_scope)
