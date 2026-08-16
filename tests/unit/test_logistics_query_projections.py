"""Logistics projection helper invariants and fail-closed query edges."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.utils import timezone

from maru.identity.models import Account
from maru.logistics import queries
from maru.logistics.models import LogisticsEvent, RestrictedLogisticsAddress
from maru.logistics.services import (
    LogisticsAuthorizationDeniedError,
    LogisticsResourceUnavailableError,
)


def _actor(*, kind: str = Account.Kind.PERSON) -> Account:
    return Account(
        id=uuid4(),
        email="projection-query@example.test",
        is_active=True,
        account_kind=kind,
    )


def _state(**overrides):
    values = {
        "asset_id": None,
        "asset": None,
        "stock_lot_id": None,
        "stock_lot": None,
        "physical_key_id": None,
        "physical_key": None,
        "node_id": None,
        "node": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("field", "kind"),
    [
        ("node_id", LogisticsEvent.SubjectKind.NODE),
        ("asset_id", LogisticsEvent.SubjectKind.ASSET),
        ("stock_lot_id", LogisticsEvent.SubjectKind.STOCK_LOT),
        ("physical_key_id", LogisticsEvent.SubjectKind.KEY),
    ],
)
def test_manifest_line_subject_id_accepts_exactly_one_typed_reference(
    field: str, kind: str
) -> None:
    subject_id = uuid4()
    values = {
        "node_id": None,
        "asset_id": None,
        "stock_lot_id": None,
        "physical_key_id": None,
        field: subject_id,
    }
    assert queries._line_subject_id(SimpleNamespace(**values)) == subject_id
    assert kind in LogisticsEvent.SubjectKind.values

    with pytest.raises(LogisticsResourceUnavailableError):
        queries._line_subject_id(
            SimpleNamespace(
                node_id=None,
                asset_id=None,
                stock_lot_id=None,
                physical_key_id=None,
            )
        )


@pytest.mark.parametrize(
    ("kind", "relation"),
    [
        (LogisticsEvent.SubjectKind.NODE, "node"),
        (LogisticsEvent.SubjectKind.ASSET, "asset"),
        (LogisticsEvent.SubjectKind.STOCK_LOT, "stock_lot"),
        (LogisticsEvent.SubjectKind.KEY, "physical_key"),
    ],
)
def test_manifest_line_state_uses_typed_subject_projection(
    kind: str, relation: str
) -> None:
    subject = SimpleNamespace(current_state=None)
    line = SimpleNamespace(
        subject_kind=kind,
        node=None,
        asset=None,
        stock_lot=None,
        physical_key=None,
    )
    setattr(line, relation, subject)
    assert queries._line_current_state(line) == (0, "unreceived")

    subject.current_state = SimpleNamespace(event_sequence=3, state="stored")
    assert queries._line_current_state(line) == (3, "stored")
    setattr(line, relation, None)
    with pytest.raises(LogisticsResourceUnavailableError):
        queries._line_current_state(line)

    line.subject_kind = "unsupported"
    with pytest.raises(LogisticsResourceUnavailableError):
        queries._line_current_state(line)


@pytest.mark.parametrize(
    ("id_field", "relation", "kind", "label_field"),
    [
        ("asset_id", "asset", LogisticsEvent.SubjectKind.ASSET, "name"),
        (
            "stock_lot_id",
            "stock_lot",
            LogisticsEvent.SubjectKind.STOCK_LOT,
            "name",
        ),
        (
            "physical_key_id",
            "physical_key",
            LogisticsEvent.SubjectKind.KEY,
            "label",
        ),
        ("node_id", "node", LogisticsEvent.SubjectKind.NODE, "name"),
    ],
)
def test_current_state_subject_projection_is_typed_and_non_disclosing(
    id_field: str,
    relation: str,
    kind: str,
    label_field: str,
) -> None:
    subject_id = uuid4()
    related = SimpleNamespace(**{label_field: "Tracked subject"})
    state = _state(**{id_field: subject_id, relation: related})
    assert queries._state_subject(state) == (kind, subject_id, "Tracked subject")

    setattr(state, relation, None)
    with pytest.raises(LogisticsResourceUnavailableError):
        queries._state_subject(state)

    with pytest.raises(LogisticsResourceUnavailableError):
        queries._state_subject(_state())


def test_personal_index_and_self_offer_history_require_an_active_person() -> None:
    with pytest.raises(LogisticsAuthorizationDeniedError):
        queries.authorize_personal_logistics_index_scope(
            actor=_actor(kind=Account.Kind.PLATFORM_ADMINISTRATOR)
        )

    actor = _actor()
    missing = MagicMock()
    missing.exists.return_value = False
    with (
        patch(
            "maru.logistics.queries._require_self_decision",
            side_effect=LogisticsAuthorizationDeniedError,
        ),
        patch(
            "maru.logistics.queries.EquipmentOffer.objects.filter",
            return_value=missing,
        ),
        pytest.raises(LogisticsAuthorizationDeniedError),
    ):
        queries.list_self_offers(
            actor=actor,
            organization_id=uuid4(),
            edition_id=uuid4(),
        )

    existing = MagicMock()
    existing.exists.return_value = True
    projected = MagicMock()
    projected.__getitem__.return_value = ()
    ordered = existing.select_related.return_value.prefetch_related.return_value
    ordered.order_by.return_value = projected
    with (
        patch(
            "maru.logistics.queries._require_self_decision",
            side_effect=LogisticsAuthorizationDeniedError,
        ),
        patch(
            "maru.logistics.queries.EquipmentOffer.objects.filter",
            return_value=existing,
        ),
    ):
        assert (
            queries.list_self_offers(
                actor=actor,
                organization_id=uuid4(),
                edition_id=uuid4(),
            )
            == ()
        )


def test_offer_submission_availability_fails_closed_for_state_or_policy() -> None:
    actor = _actor()
    edition_scope = MagicMock()
    edition_scope.exists.return_value = False
    with patch(
        "maru.logistics.queries.EventEdition.objects.filter",
        return_value=edition_scope,
    ):
        assert not queries.can_submit_equipment_offer(
            actor=actor,
            organization_id=uuid4(),
            edition_id=uuid4(),
        )

    edition_scope.exists.return_value = True
    with (
        patch(
            "maru.logistics.queries.EventEdition.objects.filter",
            return_value=edition_scope,
        ),
        patch(
            "maru.logistics.queries._require_self_decision",
            side_effect=LogisticsAuthorizationDeniedError,
        ),
    ):
        assert not queries.can_submit_equipment_offer(
            actor=actor,
            organization_id=uuid4(),
            edition_id=uuid4(),
        )


@pytest.mark.parametrize(
    ("id_field", "kind"),
    [
        ("asset_id", LogisticsEvent.SubjectKind.ASSET),
        ("stock_lot_id", LogisticsEvent.SubjectKind.STOCK_LOT),
        ("physical_key_id", LogisticsEvent.SubjectKind.KEY),
        ("node_id", LogisticsEvent.SubjectKind.NODE),
    ],
)
def test_return_subject_and_state_filter_support_every_tracked_kind(
    id_field: str, kind: str
) -> None:
    subject_id = uuid4()
    values = {
        "asset_id": None,
        "stock_lot_id": None,
        "physical_key_id": None,
        "node_id": None,
        id_field: subject_id,
    }
    assert queries._return_subject(SimpleNamespace(**values)) == (kind, subject_id)
    assert queries._subject_state_filter(kind, subject_id).children == [
        (id_field, subject_id)
    ]

    with pytest.raises(LogisticsResourceUnavailableError):
        queries._return_subject(
            SimpleNamespace(
                asset_id=None,
                stock_lot_id=None,
                physical_key_id=None,
                node_id=None,
            )
        )
    with pytest.raises(LogisticsResourceUnavailableError):
        queries._subject_state_filter("unsupported", subject_id)


def test_return_projection_distinguishes_returned_overdue_and_missing_provider() -> (
    None
):
    now = timezone.now()
    subject_id = uuid4()
    agreement = SimpleNamespace(
        id=uuid4(),
        kind="loan",
        asset_id=subject_id,
        stock_lot_id=None,
        physical_key_id=None,
        node_id=None,
        provider_account_id=uuid4(),
        provider_id=None,
        starts_at=now - timedelta(days=2),
        return_due_at=now - timedelta(days=1),
    )
    state_query = MagicMock()
    state_query.select_related.return_value.first.return_value = SimpleNamespace(
        last_event=SimpleNamespace(
            event_type=LogisticsEvent.EventType.RETURN,
            occurred_at=now - timedelta(hours=1),
        )
    )
    with patch(
        "maru.logistics.queries.LogisticsCurrentState.objects.filter",
        return_value=state_query,
    ):
        returned = queries._return_projection(agreement, evaluated_at=now)
    assert returned.returned
    assert not returned.overdue
    assert returned.provider_kind == "account"

    state_query.select_related.return_value.first.return_value = None
    agreement.provider_account_id = None
    agreement.provider_id = uuid4()
    with patch(
        "maru.logistics.queries.LogisticsCurrentState.objects.filter",
        return_value=state_query,
    ):
        overdue = queries._return_projection(agreement, evaluated_at=now)
    assert not overdue.returned
    assert overdue.overdue
    assert overdue.provider_kind == "party"

    agreement.provider_id = None
    with (
        patch(
            "maru.logistics.queries.LogisticsCurrentState.objects.filter",
            return_value=state_query,
        ),
        pytest.raises(LogisticsResourceUnavailableError),
    ):
        queries._return_projection(agreement, evaluated_at=now)


def test_manifest_and_contact_queries_hide_missing_exact_resources() -> None:
    actor = _actor()
    manifest_query = MagicMock()
    manifest_query.filter.return_value.first.return_value = None
    with (
        patch("maru.logistics.queries.authorize_logistics_api_scope"),
        patch("maru.logistics.queries._manifest_queryset", return_value=manifest_query),
        pytest.raises(LogisticsResourceUnavailableError),
    ):
        queries.manifest_for_workspace(
            actor=actor,
            organization_id=uuid4(),
            edition_id=uuid4(),
            manifest_id=uuid4(),
        )

    with pytest.raises(LogisticsResourceUnavailableError):
        queries.read_restricted_logistics_contact(
            actor=actor,
            organization_id=uuid4(),
            edition_id=uuid4(),
            address_id=uuid4(),
            purpose="unsupported",
            access_purpose="pickup_coordination",
        )
    with pytest.raises(LogisticsResourceUnavailableError):
        queries.prepare_restricted_contact_request(
            actor=actor,
            organization_id=uuid4(),
            edition_id=uuid4(),
            address_id=uuid4(),
            purpose=RestrictedLogisticsAddress.Purpose.PICKUP,
            access_purpose="unsupported",
        )

    address_query = MagicMock()
    address_query.filter.return_value.first.return_value = None
    with (
        patch("maru.logistics.queries._require_edition_decision"),
        patch(
            "maru.logistics.queries.RestrictedLogisticsAddress.objects.filter",
            return_value=address_query,
        ),
        pytest.raises(LogisticsResourceUnavailableError),
    ):
        queries.read_restricted_logistics_contact(
            actor=actor,
            organization_id=uuid4(),
            edition_id=uuid4(),
            address_id=uuid4(),
            purpose=RestrictedLogisticsAddress.Purpose.PICKUP,
            access_purpose="pickup_coordination",
        )

    request_query = MagicMock()
    request_query.filter.return_value.only.return_value.exists.return_value = False
    with (
        patch("maru.logistics.queries._require_edition_decision"),
        patch(
            "maru.logistics.queries.RestrictedLogisticsAddress.objects.filter",
            return_value=request_query,
        ),
        pytest.raises(LogisticsResourceUnavailableError),
    ):
        queries.prepare_restricted_contact_request(
            actor=actor,
            organization_id=uuid4(),
            edition_id=uuid4(),
            address_id=uuid4(),
            purpose=RestrictedLogisticsAddress.Purpose.PICKUP,
            access_purpose="pickup_coordination",
        )
