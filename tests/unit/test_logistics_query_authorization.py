"""Non-disclosing route-scope authorization for Logistics queries."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from maru.identity.models import Account
from maru.logistics import queries
from maru.logistics.services import (
    CATALOG_MANAGE_CAPABILITY,
    MANIFEST_MANAGE_CAPABILITY,
    MANIFEST_VIEW_CAPABILITY,
    OFFER_REVIEW_CAPABILITY,
    RESTRICTED_CONTACT_CAPABILITY,
    SELF_OFFER_CAPABILITY,
    WORKSPACE_VIEW_CAPABILITY,
    LogisticsAuthorizationDeniedError,
)


def _actor(*, active: bool = True, kind: str = Account.Kind.PERSON) -> Account:
    return Account(
        id=uuid4(),
        email="logistics-query-actor@example.test",
        is_active=active,
        account_kind=kind,
    )


def _decision(*, allowed: bool) -> SimpleNamespace:
    return SimpleNamespace(allowed=allowed, reason_code="synthetic", obligations=())


def _existing_queryset(*, exists: bool) -> MagicMock:
    queryset = MagicMock()
    queryset.filter.return_value = queryset
    queryset.only.return_value = queryset
    queryset.exists.return_value = exists
    return queryset


@pytest.mark.parametrize(
    "actor",
    [
        Account(id=None, email="unsaved@example.test", is_active=True),
        _actor(active=False),
        _actor(kind=Account.Kind.PLATFORM_ADMINISTRATOR),
    ],
)
def test_route_authorization_rejects_inactive_or_nonparticipating_accounts(
    actor: Account,
) -> None:
    with pytest.raises(LogisticsAuthorizationDeniedError):
        queries.authorize_logistics_api_scope(
            actor=actor,
            organization_id=uuid4(),
            capability_code=WORKSPACE_VIEW_CAPABILITY,
        )


def test_exact_decision_helpers_fail_closed_for_missing_or_denied_targets() -> None:
    actor = _actor()
    with (
        patch("maru.logistics.queries.resolve_edition_target", return_value=None),
        pytest.raises(LogisticsAuthorizationDeniedError),
    ):
        queries._require_edition_decision(
            actor=actor,
            organization_id=uuid4(),
            edition_id=uuid4(),
            capability=WORKSPACE_VIEW_CAPABILITY,
        )

    with (
        patch("maru.logistics.queries.resolve_edition_target", return_value=object()),
        patch("maru.logistics.queries.decide", return_value=_decision(allowed=False)),
        pytest.raises(LogisticsAuthorizationDeniedError),
    ):
        queries._require_edition_decision(
            actor=actor,
            organization_id=uuid4(),
            edition_id=uuid4(),
            capability=WORKSPACE_VIEW_CAPABILITY,
        )

    allowed = _decision(allowed=True)
    with (
        patch("maru.logistics.queries.resolve_edition_target", return_value=object()),
        patch("maru.logistics.queries.decide", return_value=allowed),
    ):
        assert (
            queries._require_edition_decision(
                actor=actor,
                organization_id=uuid4(),
                edition_id=uuid4(),
                capability=WORKSPACE_VIEW_CAPABILITY,
            )
            is allowed
        )

    with (
        patch("maru.logistics.queries.resolve_self_target", return_value=None),
        pytest.raises(LogisticsAuthorizationDeniedError),
    ):
        queries._require_self_decision(
            actor=actor, organization_id=uuid4(), edition_id=uuid4()
        )

    with (
        patch("maru.logistics.queries.resolve_self_target", return_value=object()),
        patch("maru.logistics.queries.decide", return_value=_decision(allowed=False)),
        pytest.raises(LogisticsAuthorizationDeniedError),
    ):
        queries._require_self_decision(
            actor=actor, organization_id=uuid4(), edition_id=uuid4()
        )


def test_route_scope_rejects_ambiguous_exact_resources_and_orphan_line() -> None:
    actor = _actor()
    for kwargs in (
        {"manifest_id": uuid4(), "offer_id": uuid4()},
        {"manifest_line_id": uuid4()},
    ):
        with pytest.raises(LogisticsAuthorizationDeniedError):
            queries.authorize_logistics_api_scope(
                actor=actor,
                organization_id=uuid4(),
                edition_id=uuid4(),
                capability_code=MANIFEST_MANAGE_CAPABILITY,
                **kwargs,
            )


def test_self_offer_open_scope_requires_exact_capability_edition_and_lifecycle() -> (
    None
):
    actor = _actor()
    organization_id = uuid4()
    edition_id = uuid4()
    for capability, selected_edition in (
        (WORKSPACE_VIEW_CAPABILITY, edition_id),
        (SELF_OFFER_CAPABILITY, None),
    ):
        with pytest.raises(LogisticsAuthorizationDeniedError):
            queries.authorize_logistics_api_scope(
                actor=actor,
                organization_id=organization_id,
                edition_id=selected_edition,
                capability_code=capability,
                require_self_offer_open=True,
            )

    closed = _existing_queryset(exists=False)
    with (
        patch(
            "maru.logistics.queries.EventEdition.objects.filter", return_value=closed
        ),
        pytest.raises(LogisticsAuthorizationDeniedError),
    ):
        queries.authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=SELF_OFFER_CAPABILITY,
            require_self_offer_open=True,
        )


def test_manifest_scope_requires_exact_route_line_and_manifest_decision() -> None:
    actor = _actor()
    organization_id = uuid4()
    edition_id = uuid4()
    manifest_id = uuid4()
    line_id = uuid4()
    for capability, selected_edition in (
        (CATALOG_MANAGE_CAPABILITY, edition_id),
        (MANIFEST_MANAGE_CAPABILITY, None),
    ):
        with pytest.raises(LogisticsAuthorizationDeniedError):
            queries.authorize_logistics_api_scope(
                actor=actor,
                organization_id=organization_id,
                edition_id=selected_edition,
                manifest_id=manifest_id,
                capability_code=capability,
            )

    missing_line = _existing_queryset(exists=False)
    with (
        patch(
            "maru.logistics.queries.resolve_logistics_manifest_target",
            return_value=object(),
        ),
        patch(
            "maru.logistics.queries.LogisticsManifestLine.objects.filter",
            return_value=missing_line,
        ),
        pytest.raises(LogisticsAuthorizationDeniedError),
    ):
        queries.authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            manifest_id=manifest_id,
            manifest_line_id=line_id,
            capability_code=MANIFEST_VIEW_CAPABILITY,
        )

    present_line = _existing_queryset(exists=True)
    with (
        patch(
            "maru.logistics.queries.resolve_logistics_manifest_target",
            return_value=object(),
        ),
        patch(
            "maru.logistics.queries.LogisticsManifestLine.objects.filter",
            return_value=present_line,
        ),
        patch("maru.logistics.queries.decide", return_value=_decision(allowed=True)),
    ):
        queries.authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            manifest_id=manifest_id,
            manifest_line_id=line_id,
            capability_code=MANIFEST_MANAGE_CAPABILITY,
        )


def test_key_offer_and_contact_scopes_are_bound_to_exact_records() -> None:
    actor = _actor()
    organization_id = uuid4()
    edition_id = uuid4()
    missing = _existing_queryset(exists=False)
    present = _existing_queryset(exists=True)

    for capability, selected_edition in (
        (WORKSPACE_VIEW_CAPABILITY, None),
        (CATALOG_MANAGE_CAPABILITY, edition_id),
    ):
        with pytest.raises(LogisticsAuthorizationDeniedError):
            queries.authorize_logistics_api_scope(
                actor=actor,
                organization_id=organization_id,
                edition_id=selected_edition,
                key_id=uuid4(),
                capability_code=capability,
            )
    with (
        patch(
            "maru.logistics.queries.PhysicalKey.objects.filter", return_value=missing
        ),
        pytest.raises(LogisticsAuthorizationDeniedError),
    ):
        queries.authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            key_id=uuid4(),
            capability_code=CATALOG_MANAGE_CAPABILITY,
        )
    with (
        patch(
            "maru.logistics.queries.PhysicalKey.objects.filter", return_value=present
        ),
        patch(
            "maru.logistics.queries.resolve_organization_target", return_value=object()
        ),
        patch("maru.logistics.queries.decide", return_value=_decision(allowed=True)),
    ):
        queries.authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            key_id=uuid4(),
            capability_code=CATALOG_MANAGE_CAPABILITY,
        )

    with pytest.raises(LogisticsAuthorizationDeniedError):
        queries.authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            offer_id=uuid4(),
            capability_code=OFFER_REVIEW_CAPABILITY,
        )
    with (
        patch(
            "maru.logistics.queries.EquipmentOffer.objects.filter", return_value=missing
        ),
        pytest.raises(LogisticsAuthorizationDeniedError),
    ):
        queries.authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            offer_id=uuid4(),
            capability_code=OFFER_REVIEW_CAPABILITY,
        )

    with (
        patch(
            "maru.logistics.queries.EquipmentOffer.objects.filter", return_value=present
        ),
        patch(
            "maru.logistics.queries.resolve_self_target", return_value=object()
        ) as self_target,
        patch("maru.logistics.queries.resolve_edition_target", return_value=object()),
        patch("maru.logistics.queries.decide", return_value=_decision(allowed=True)),
    ):
        queries.authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            offer_id=uuid4(),
            capability_code=SELF_OFFER_CAPABILITY,
        )
        assert self_target.called
        queries.authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            offer_id=uuid4(),
            capability_code=OFFER_REVIEW_CAPABILITY,
        )

    for capability, selected_edition in (
        (RESTRICTED_CONTACT_CAPABILITY, None),
        (WORKSPACE_VIEW_CAPABILITY, edition_id),
    ):
        with pytest.raises(LogisticsAuthorizationDeniedError):
            queries.authorize_logistics_api_scope(
                actor=actor,
                organization_id=organization_id,
                edition_id=selected_edition,
                address_id=uuid4(),
                capability_code=capability,
            )
    with (
        patch(
            "maru.logistics.queries.RestrictedLogisticsAddress.objects.filter",
            return_value=missing,
        ),
        pytest.raises(LogisticsAuthorizationDeniedError),
    ):
        queries.authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            address_id=uuid4(),
            capability_code=RESTRICTED_CONTACT_CAPABILITY,
        )


def test_generic_scope_resolution_and_policy_decision_fail_closed() -> None:
    actor = _actor()
    organization_id = uuid4()
    edition_id = uuid4()
    with (
        patch("maru.logistics.queries.resolve_self_target", return_value=None),
        pytest.raises(LogisticsAuthorizationDeniedError),
    ):
        queries.authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=SELF_OFFER_CAPABILITY,
        )

    for edition, resolver in (
        (edition_id, "resolve_edition_target"),
        (None, "resolve_organization_target"),
    ):
        with (
            patch(f"maru.logistics.queries.{resolver}", return_value=object()),
            patch(
                "maru.logistics.queries.decide", return_value=_decision(allowed=False)
            ),
            pytest.raises(LogisticsAuthorizationDeniedError),
        ):
            queries.authorize_logistics_api_scope(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition,
                capability_code=WORKSPACE_VIEW_CAPABILITY,
            )

        with (
            patch(f"maru.logistics.queries.{resolver}", return_value=object()),
            patch(
                "maru.logistics.queries.decide", return_value=_decision(allowed=True)
            ),
        ):
            queries.authorize_logistics_api_scope(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition,
                capability_code=WORKSPACE_VIEW_CAPABILITY,
            )


def test_owned_offer_history_cannot_override_exact_self_policy() -> None:
    actor = _actor()
    with (
        patch(
            "maru.logistics.queries.authorize_logistics_api_scope",
            side_effect=LogisticsAuthorizationDeniedError,
        ),
        patch(
            "maru.logistics.queries.EquipmentOffer.objects.filter",
        ) as offers,
        pytest.raises(LogisticsAuthorizationDeniedError),
    ):
        queries.authorize_self_offer_history_api_scope(
            actor=actor, organization_id=uuid4(), edition_id=uuid4()
        )
    offers.assert_not_called()

    with patch("maru.logistics.queries.authorize_logistics_api_scope") as authorize:
        queries.authorize_self_offer_history_api_scope(
            actor=actor, organization_id=uuid4(), edition_id=uuid4()
        )
    authorize.assert_called_once()
