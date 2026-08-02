from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from maru.workforce.models import (
    Department,
    EditionStructureCommandReceipt,
    EditionStructureControl,
)
from tests.factories import AccountFactory, EventEditionFactory
from tests.workforce_helpers import create_department_for_test

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _control() -> EditionStructureControl:
    edition = EventEditionFactory()
    create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
    )
    return EditionStructureControl.objects.get(edition=edition)


def test_structure_control_enforces_positive_exact_edition_scope() -> None:
    edition = EventEditionFactory()
    other = EventEditionFactory()

    with pytest.raises(ValidationError, match="edition scope"):
        EditionStructureControl(
            organization=other.organization,
            edition=edition,
            origin=EditionStructureControl.Origin.MANUAL,
            aggregate_version=1,
        ).full_clean()

    with pytest.raises(
        ValidationError,
        match=r"greater than or equal to 0|Constraint",
    ):
        EditionStructureControl(
            organization=edition.organization,
            edition=edition,
            origin=EditionStructureControl.Origin.MANUAL,
            aggregate_version=0,
        ).full_clean()


def test_command_receipt_is_exact_bounded_and_append_only() -> None:
    control = _control()
    actor = AccountFactory()
    receipt = EditionStructureCommandReceipt.objects.get(
        structure=control,
        action=EditionStructureCommandReceipt.Action.DEPARTMENT_CREATED,
    )
    department_id = receipt.affected_department_ids[0]
    receipt.full_clean()

    receipt.reason = "Mutation is forbidden."
    with pytest.raises(ValidationError, match="immutable"):
        receipt.save()
    with pytest.raises(ValidationError, match="immutable"):
        receipt.delete()

    invalid = EditionStructureCommandReceipt(
        structure=control,
        organization=control.organization,
        edition=control.edition,
        action=EditionStructureCommandReceipt.Action.DEPARTMENT_UPDATED,
        resulting_version=1,
        actor=actor,
        reason="Update a Department.",
        correlation_id=uuid4(),
        source_channel="admin_web",
        affected_department_ids=[department_id, uuid4()],
    )
    with pytest.raises(ValidationError, match="affected Department count"):
        invalid.clean()


def test_template_receipt_shape_is_minimized() -> None:
    template_control = _control()
    actor = AccountFactory()
    template = EditionStructureCommandReceipt(
        structure=template_control,
        organization=template_control.organization,
        edition=template_control.edition,
        action=EditionStructureCommandReceipt.Action.TEMPLATE_APPLIED,
        resulting_version=1,
        actor=actor,
        reason="Apply the built-in convention structure.",
        correlation_id=uuid4(),
        source_channel="admin_web",
        changed_fields=["template"],
        affected_department_ids=[uuid4() for _ in range(22)],
        retry_key=uuid4(),
        request_digest="b" * 64,
        template_code="awoostria-v1",
        template_version=1,
        template_digest="c" * 64,
    )
    template.clean()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"retry_key": uuid4()}, "retry evidence"),
        ({"request_digest": "d" * 64}, "retry evidence"),
        ({"template_code": "awoostria-reference"}, "Template provenance"),
        ({"template_version": 1}, "Template provenance"),
        ({"template_digest": "e" * 64}, "Template provenance"),
    ],
)
def test_noneligible_receipts_reject_partial_retry_or_template_evidence(
    overrides: dict[str, object],
    message: str,
) -> None:
    control = _control()
    values: dict[str, object] = {
        "structure": control,
        "organization": control.organization,
        "edition": control.edition,
        "action": EditionStructureCommandReceipt.Action.DEPARTMENT_UPDATED,
        "resulting_version": 1,
        "actor": AccountFactory(),
        "reason": "Update the Department structure.",
        "correlation_id": uuid4(),
        "source_channel": "admin_web",
        "changed_fields": ["name"],
        "affected_department_ids": [uuid4()],
    }
    values.update(overrides)

    with pytest.raises(ValidationError, match=message):
        EditionStructureCommandReceipt(**values).clean()


@pytest.mark.parametrize(
    "overrides",
    [
        {"retry_key": None},
        {"request_digest": ""},
        {"template_code": ""},
        {"template_version": None},
        {"template_version": 0},
        {"template_digest": ""},
    ],
)
def test_template_receipts_require_complete_positive_provenance(
    overrides: dict[str, object],
) -> None:
    control = _control()
    values: dict[str, object] = {
        "structure": control,
        "organization": control.organization,
        "edition": control.edition,
        "action": EditionStructureCommandReceipt.Action.TEMPLATE_APPLIED,
        "resulting_version": 1,
        "actor": AccountFactory(),
        "reason": "Apply the reference Department structure.",
        "correlation_id": uuid4(),
        "source_channel": "admin_web",
        "changed_fields": ["departments"],
        "affected_department_ids": [uuid4() for _ in range(22)],
        "retry_key": uuid4(),
        "request_digest": "f" * 64,
        "template_code": "awoostria-reference",
        "template_version": 1,
        "template_digest": "a" * 64,
    }
    values.update(overrides)

    with pytest.raises(ValidationError, match=r"Template provenance|retry evidence"):
        EditionStructureCommandReceipt(**values).clean()


def test_department_structure_metadata_and_display_order_are_guarded() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    department = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
        display_order=65_535,
    )

    invalid_retirement = Department(
        organization=edition.organization,
        edition=edition,
        code="registration",
        name="Registration",
        retired_by=actor,
    )
    with pytest.raises(ValidationError, match="Constraint"):
        invalid_retirement.full_clean()

    department.display_order = 65_536
    with pytest.raises(ValidationError, match="less than or equal"):
        department.full_clean()

    with pytest.raises(IntegrityError), transaction.atomic():
        Department.objects.filter(pk=department.pk).update(
            last_changed_in_structure_version=0
        )

    legacy_department = Department(
        organization=edition.organization,
        edition=edition,
        code="legacy-operations",
        name="Legacy Operations",
        last_changed_in_structure_version=2,
    )
    legacy_department.full_clean()
    assert legacy_department.created_in_structure_version is None
