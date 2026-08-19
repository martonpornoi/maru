from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

from maru.identity.models import Account
from maru.logistics import services


def _actor() -> Account:
    return Account(
        id=uuid4(),
        email="logistics-scope-operator@example.test",
        is_active=True,
    )


def test_catalog_context_uses_exact_edition_authority_for_allocated_records() -> None:
    actor = _actor()
    organization_id = uuid4()
    edition_id = uuid4()
    at = datetime(2026, 8, 9, 12, tzinfo=UTC)
    expected = (actor, object(), object(), object())

    with (
        patch(
            "maru.logistics.services._edition_context",
            return_value=expected,
        ) as edition_context,
        patch("maru.logistics.services._organization_context") as org_context,
    ):
        result = services._catalog_context(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            at=at,
        )

    assert result == expected
    edition_context.assert_called_once_with(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=services.CATALOG_MANAGE_CAPABILITY,
        at=at,
    )
    org_context.assert_not_called()


def test_catalog_context_uses_organization_authority_for_global_records() -> None:
    actor = _actor()
    organization_id = uuid4()
    at = datetime(2026, 8, 9, 12, tzinfo=UTC)
    organization = object()
    decision = object()

    with (
        patch("maru.logistics.services._edition_context") as edition_context,
        patch(
            "maru.logistics.services._organization_context",
            return_value=(actor, organization, decision),
        ) as org_context,
    ):
        result = services._catalog_context(
            actor=actor,
            organization_id=organization_id,
            edition_id=None,
            at=at,
        )

    assert result == (actor, organization, None, decision)
    org_context.assert_called_once_with(
        actor=actor,
        organization_id=organization_id,
        capability_code=services.CATALOG_MANAGE_CAPABILITY,
        at=at,
    )
    edition_context.assert_not_called()
