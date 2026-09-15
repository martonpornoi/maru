"""Venue entry references are complete, scoped and name-free until exact lookup."""

from unittest.mock import MagicMock
from uuid import UUID

import pytest
from django.db import DatabaseError

from maru.venues import operator_entry_references as refs


@pytest.fixture
def query(monkeypatch):
    model = MagicMock()
    rows = model.objects.filter.return_value
    rows.filter.return_value = rows
    rows.order_by.return_value = rows
    source = (UUID(int=3), 2, UUID(int=4), 7, UUID(int=5))
    rows.values_list.return_value.__getitem__.return_value = (source,)
    rows.values_list.return_value.first.return_value = (*source, "Main Stage", "Hotel")
    rows.count.return_value = 1
    monkeypatch.setattr(refs, "EditionSpaceSelection", model)
    return model, rows, source


def test_complete_reference_selects_only_opaque_source_facts(query):
    model, rows, source = query
    result = refs.resolve_operator_room_set_reference(
        organization_id=UUID(int=1), edition_id=UUID(int=2)
    )
    assert result.rooms == (refs.OperatorRoomCandidate(*source),)
    assert rows.values_list.call_args.args == refs._SOURCE_FIELDS
    assert not {"local_name", "venue_selection__local_name"}.intersection(
        rows.values_list.call_args.args
    )
    assert rows.values_list.return_value.__getitem__.call_args.args == (
        slice(None, 257),
    )
    assert model.objects.filter.call_args.kwargs["organization_id"] == UUID(int=1)
    assert model.objects.filter.call_args.kwargs["edition_id"] == UUID(int=2)
    assert (
        model.objects.filter.call_args.kwargs[
            "responsible_department__retired_at__isnull"
        ]
        is True
    )
    assert rows.filter.call_args.kwargs == {
        "venue_selection__organization_id": UUID(int=1),
        "venue_selection__edition_id": UUID(int=2),
        "responsible_department__organization_id": UUID(int=1),
        "responsible_department__edition_id": UUID(int=2),
    }


@pytest.mark.parametrize("failure", ["overflow", "incoherent", "database"])
def test_reference_does_not_turn_incomplete_source_into_empty_choices(query, failure):
    _model, rows, source = query
    if failure == "overflow":
        rows.values_list.return_value.__getitem__.return_value = (source,) * 257
    elif failure == "incoherent":
        rows.count.return_value = 2
    else:
        rows.values_list.side_effect = DatabaseError
    if failure == "database":
        with pytest.raises(DatabaseError):
            refs.resolve_operator_room_set_reference(
                organization_id=UUID(int=1), edition_id=UUID(int=2)
            )
    else:
        assert (
            refs.resolve_operator_room_set_reference(
                organization_id=UUID(int=1), edition_id=UUID(int=2)
            )
            is None
        )


def test_exact_choice_reads_only_minimal_wayfinding(query):
    _model, rows, source = query
    result = refs.resolve_operator_room_choice_reference(
        organization_id=UUID(int=1), edition_id=UUID(int=2), space_id=UUID(int=3)
    )
    assert result == refs.OperatorRoomChoiceReference(
        refs.OperatorRoomCandidate(*source), "Main Stage", "Hotel"
    )
    assert rows.filter.call_args.kwargs == {"id": UUID(int=3)}
    assert rows.values_list.call_args.args == (
        *refs._SOURCE_FIELDS,
        "local_name",
        "venue_selection__local_name",
    )


def test_zero_scope_never_dispatches_owner_query(query):
    model, _rows, _source = query
    model.objects.filter.reset_mock()
    assert (
        refs.resolve_operator_room_set_reference(
            organization_id=UUID(int=0), edition_id=UUID(int=2)
        )
        is None
    )
    assert (
        refs.resolve_operator_room_choice_reference(
            organization_id=UUID(int=1), edition_id=UUID(int=2), space_id=UUID(int=0)
        )
        is None
    )
    model.objects.filter.assert_not_called()
