from collections.abc import Callable
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.db.models import F

from maru.events.models import EditionCreationReceipt, EventEdition
from maru.organizations.models import ConventionSeries
from tests.factories import (
    ConventionSeriesFactory,
    EventEditionFactory,
    OrganizationFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _assert_integrity_error(
    message: str,
    mutation: Callable[[], object],
) -> None:
    with transaction.atomic(), pytest.raises(IntegrityError, match=message):
        mutation()


def test_series_profile_guard_requires_exact_version_increment() -> None:
    series = ConventionSeriesFactory()

    _assert_integrity_error(
        "series profile change must increment profile version",
        lambda: ConventionSeries.objects.filter(pk=series.pk).update(
            name="Unversioned brand change"
        ),
    )

    assert (
        ConventionSeries.objects.filter(pk=series.pk).update(
            name="Versioned brand change",
            profile_version=F("profile_version") + 1,
        )
        == 1
    )
    series.refresh_from_db()
    assert series.name == "Versioned brand change"
    assert series.profile_version == 2


def test_series_guard_rejects_reparenting_and_stable_slug_changes() -> None:
    series = ConventionSeriesFactory()

    _assert_integrity_error(
        "convention series ownership and stable slug are immutable",
        lambda: ConventionSeries.objects.filter(pk=series.pk).update(
            organization=OrganizationFactory()
        ),
    )
    _assert_integrity_error(
        "convention series ownership and stable slug are immutable",
        lambda: ConventionSeries.objects.filter(pk=series.pk).update(
            slug="rewritten-series-slug"
        ),
    )


def test_series_guard_rejects_version_only_updates() -> None:
    series = ConventionSeriesFactory()

    _assert_integrity_error(
        "series profile version changes only with profile facts",
        lambda: ConventionSeries.objects.filter(pk=series.pk).update(
            profile_version=F("profile_version") + 1
        ),
    )


@pytest.mark.parametrize("stable_field", ["organization", "series", "slug"])
def test_edition_guard_rejects_stable_scope_or_slug_changes(
    stable_field: str,
) -> None:
    edition = EventEditionFactory()
    replacements = {
        "organization": OrganizationFactory(),
        "series": ConventionSeriesFactory(organization=edition.organization),
        "slug": "rewritten-edition-slug",
    }

    _assert_integrity_error(
        "edition ownership and stable slug are immutable",
        lambda: EventEdition.objects.filter(pk=edition.pk).update(
            **{stable_field: replacements[stable_field]}
        ),
    )


def test_edition_guard_rejects_version_only_updates() -> None:
    edition = EventEditionFactory()

    _assert_integrity_error(
        "aggregate version changes only with edition facts",
        lambda: EventEdition.objects.filter(pk=edition.pk).update(
            aggregate_version=F("aggregate_version") + 1
        ),
    )


def test_edition_guard_rejects_combined_profile_and_lifecycle_command() -> None:
    edition = EventEditionFactory()

    _assert_integrity_error(
        "edition profile and lifecycle require separate commands",
        lambda: EventEdition.objects.filter(pk=edition.pk).update(
            name="Combined rewrite",
            lifecycle=EventEdition.Lifecycle.PREPARING,
            lifecycle_version=F("lifecycle_version") + 1,
            aggregate_version=F("aggregate_version") + 1,
        ),
    )


def test_edition_profile_guard_allows_one_versioned_profile_command() -> None:
    edition = EventEditionFactory()

    assert (
        EventEdition.objects.filter(pk=edition.pk).update(
            name="Versioned edition name",
            aggregate_version=F("aggregate_version") + 1,
        )
        == 1
    )
    edition.refresh_from_db()
    assert edition.name == "Versioned edition name"
    assert edition.aggregate_version == 2


def _creation_receipt(edition: EventEdition) -> EditionCreationReceipt:
    return EditionCreationReceipt.objects.create(
        edition=edition,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        actor_id=uuid4(),
        idempotency_key=uuid4(),
        request_digest="a" * 64,
    )


def test_edition_creation_receipt_guard_rejects_raw_update_and_delete() -> None:
    receipt = _creation_receipt(EventEditionFactory())

    _assert_integrity_error(
        "edition creation receipts are append-only",
        lambda: EditionCreationReceipt.objects.filter(pk=receipt.pk).update(
            request_digest="b" * 64
        ),
    )
    _assert_integrity_error(
        "edition creation receipts are append-only",
        lambda: EditionCreationReceipt.objects.filter(pk=receipt.pk).delete(),
    )


def test_edition_creation_receipt_guard_rejects_invalid_digest() -> None:
    edition = EventEditionFactory()
    receipt = EditionCreationReceipt(
        edition=edition,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        actor_id=uuid4(),
        idempotency_key=uuid4(),
        request_digest="A" * 64,
    )

    _assert_integrity_error(
        "edition creation receipt digest must be lowercase SHA-256",
        lambda: EditionCreationReceipt.objects.bulk_create([receipt]),
    )


@pytest.mark.parametrize("mismatched_field", ["organization_id", "series_id"])
def test_edition_creation_receipt_guard_rejects_scope_mismatch(
    mismatched_field: str,
) -> None:
    edition = EventEditionFactory()
    mismatched_scope = {
        "organization_id": OrganizationFactory().id,
        "series_id": ConventionSeriesFactory(organization=edition.organization).id,
    }
    receipt = EditionCreationReceipt(
        edition=edition,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        actor_id=uuid4(),
        idempotency_key=uuid4(),
        request_digest="a" * 64,
    )
    setattr(receipt, mismatched_field, mismatched_scope[mismatched_field])

    _assert_integrity_error(
        "edition creation receipt scope does not match",
        lambda: EditionCreationReceipt.objects.bulk_create([receipt]),
    )
