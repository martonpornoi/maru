from uuid import uuid4

import pytest
from django.db import transaction

from maru.authorization.enforcement import (
    BulkTargetDeniedError,
    BulkTargetUnavailableError,
    freeze_bulk_targets,
)
from maru.authorization.policy import PolicyDecision
from maru.events.models import EventEdition
from tests.factories import EventEditionFactory

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _decision(*, allowed: bool, reason_code: str) -> PolicyDecision:
    return PolicyDecision(
        allowed=allowed,
        fields=frozenset(),
        obligations=frozenset(),
        reason_code=reason_code,
    )


def test_bulk_target_freezing_requires_an_explicit_transaction() -> None:
    edition = EventEditionFactory()

    with pytest.raises(RuntimeError, match="atomic transaction"):
        freeze_bulk_targets(
            trusted_queryset=EventEdition.objects.filter(
                organization=edition.organization
            ),
            target_ids=(edition.id,),
            authorize=lambda _target: _decision(
                allowed=True,
                reason_code="allowed",
            ),
        )


def test_bulk_target_freezing_is_exact_ordered_and_fail_closed() -> None:
    first = EventEditionFactory()
    second = EventEditionFactory(
        organization=first.organization,
        series=first.series,
    )
    protected = EventEditionFactory()
    trusted = EventEdition.objects.filter(organization=first.organization)

    with transaction.atomic():
        targets = freeze_bulk_targets(
            trusted_queryset=trusted,
            target_ids=(second.id, first.id),
            authorize=lambda _target: _decision(
                allowed=True,
                reason_code="allowed",
            ),
        )
        assert tuple(target.id for target in targets) == (second.id, first.id)

        with pytest.raises(BulkTargetUnavailableError):
            freeze_bulk_targets(
                trusted_queryset=trusted,
                target_ids=(first.id, protected.id),
                authorize=lambda _target: _decision(
                    allowed=True,
                    reason_code="allowed",
                ),
            )

        with pytest.raises(BulkTargetUnavailableError):
            freeze_bulk_targets(
                trusted_queryset=trusted,
                target_ids=(first.id, uuid4()),
                authorize=lambda _target: _decision(
                    allowed=True,
                    reason_code="allowed",
                ),
            )

        with pytest.raises(BulkTargetDeniedError) as denial:
            freeze_bulk_targets(
                trusted_queryset=trusted,
                target_ids=(first.id,),
                authorize=lambda _target: _decision(
                    allowed=False,
                    reason_code="permission_absent",
                ),
            )
        assert denial.value.reason_code == "permission_absent"

        with pytest.raises(ValueError, match="non-empty and unique"):
            freeze_bulk_targets(
                trusted_queryset=trusted,
                target_ids=(first.id, first.id),
                authorize=lambda _target: _decision(
                    allowed=True,
                    reason_code="allowed",
                ),
            )
