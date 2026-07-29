from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from maru.events.models import EditionLifecycleTransition, EventEdition
from maru.events.services import transition_edition
from maru.participation.models import Participation, ParticipationCapacity
from maru.participation.services import snapshot_participations_for_archive
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    ParticipationCapacityFactory,
    ParticipationFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _archive(edition: EventEdition) -> EventEdition:
    actor = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="events.transition",
    )
    transitions = (
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.READY,
        EventEdition.Lifecycle.LIVE,
        EventEdition.Lifecycle.CLOSING,
        EventEdition.Lifecycle.ARCHIVED,
    )
    for state in transitions:
        edition = transition_edition(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            to_state=state,
            actor=actor,
            reason=f"Advance to {state}.",
            correlation_id=uuid4(),
        )
    return edition


def test_valid_lifecycle_records_every_transition() -> None:
    edition = EventEditionFactory()

    archived = _archive(edition)

    assert archived.lifecycle == EventEdition.Lifecycle.ARCHIVED
    assert archived.lifecycle_version == 5
    assert list(
        EditionLifecycleTransition.objects.filter(edition=edition).values_list(
            "from_state",
            "to_state",
        )
    ) == [
        ("draft", "preparing"),
        ("preparing", "ready"),
        ("ready", "live"),
        ("live", "closing"),
        ("closing", "archived"),
    ]


def test_transition_requires_reason_and_valid_path() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="events.transition",
    )

    with pytest.raises(ValidationError, match="reason"):
        transition_edition(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            to_state=EventEdition.Lifecycle.PREPARING,
            actor=actor,
            reason=" ",
            correlation_id=uuid4(),
        )

    with pytest.raises(ValidationError, match="Cannot transition"):
        transition_edition(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            to_state=EventEdition.Lifecycle.LIVE,
            actor=actor,
            reason="Skip readiness.",
            correlation_id=uuid4(),
        )


def test_database_rejects_invalid_raw_lifecycle_or_version_change() -> None:
    edition = EventEditionFactory()

    with transaction.atomic(), pytest.raises(IntegrityError):
        EventEdition.objects.filter(pk=edition.pk).update(
            lifecycle=EventEdition.Lifecycle.LIVE,
            lifecycle_version=1,
        )
    with transaction.atomic(), pytest.raises(IntegrityError):
        EventEdition.objects.filter(pk=edition.pk).update(lifecycle_version=1)


def test_lifecycle_transition_history_is_append_only() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="events.transition",
    )
    transition_edition(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        to_state=EventEdition.Lifecycle.PREPARING,
        actor=actor,
        reason="Begin preparation.",
        correlation_id=uuid4(),
    )
    transition = EditionLifecycleTransition.objects.get(edition=edition)

    transition.reason = "rewritten"
    with pytest.raises(ValidationError, match="append-only"):
        transition.save()
    with transaction.atomic(), pytest.raises(IntegrityError):
        EditionLifecycleTransition.objects.filter(pk=transition.pk).update(
            reason="raw rewrite"
        )


def test_archived_edition_rejects_model_and_bulk_mutation() -> None:
    edition = _archive(EventEditionFactory())

    edition.name = "Silently rewritten"
    with pytest.raises(ValidationError, match="correction workflow"):
        edition.save()

    with transaction.atomic(), pytest.raises(IntegrityError):
        EventEdition.objects.filter(pk=edition.pk).update(name="Raw rewrite")


def test_archived_participation_and_capacity_are_immutable() -> None:
    participation = ParticipationFactory()
    capacity = ParticipationCapacityFactory(participation=participation)
    _archive(participation.edition)

    participation.status = Participation.Status.COMPLETED
    with pytest.raises(ValidationError, match="correction workflow"):
        participation.save()

    with transaction.atomic(), pytest.raises(IntegrityError):
        Participation.objects.filter(pk=participation.pk).update(status="completed")

    with transaction.atomic(), pytest.raises(IntegrityError):
        ParticipationCapacity.objects.filter(pk=capacity.pk).update(
            label_snapshot="Changed"
        )


def test_archive_finalizes_labels_as_they_exist_at_close() -> None:
    participation = ParticipationFactory()
    edition = participation.edition
    series = edition.series
    edition.name = "Final Edition Name"
    edition.save()
    series.name = "Final Series Name"
    series.save()

    _archive(edition)
    participation.refresh_from_db()
    assert participation.edition_name_snapshot == "Final Edition Name"
    assert participation.series_name_snapshot == "Final Series Name"

    series.name = "Future Series Name"
    series.save()
    participation.refresh_from_db()
    assert participation.series_name_snapshot == "Final Series Name"


def test_archive_snapshot_command_requires_closing_state() -> None:
    participation = ParticipationFactory()

    with pytest.raises(ValidationError, match="only while closing"):
        snapshot_participations_for_archive(edition_id=participation.edition_id)
