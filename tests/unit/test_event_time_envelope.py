"""Pure coverage of exact edition bounds and ambiguous local-midnight rejection."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.events.queries import resolve_edition_time_envelope_reference


def resolve(monkeypatch, row, *, error=None):
    query = MagicMock()
    query.filter.return_value = query
    query.select_for_update.return_value = query
    query.values_list.return_value = query
    query.first.return_value = row
    if error is not None:
        query.filter.side_effect = error
    monkeypatch.setattr("maru.events.queries.EventEdition.objects.all", lambda: query)
    organization_id, edition_id = uuid4(), uuid4()
    result = resolve_edition_time_envelope_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        lock=True,
    )
    query.filter.assert_called_once_with(
        id=edition_id,
        organization_id=organization_id,
        series__organization_id=organization_id,
    )
    query.select_for_update.assert_called_once_with(of=("self",))
    return result


def test_edition_bounds_follow_local_dates_and_the_dst_day(monkeypatch):
    result = resolve(
        monkeypatch, (7, date(2026, 3, 29), date(2026, 3, 29), "Europe/Budapest")
    )
    assert result is not None
    assert result.version == 7
    assert result.starts_at == datetime(2026, 3, 28, 23, tzinfo=UTC)
    assert result.ends_at - result.starts_at == timedelta(hours=23)
    assert set(result.__dataclass_fields__) == {
        "edition_id",
        "organization_id",
        "version",
        "starts_at",
        "ends_at",
    }


@pytest.mark.parametrize(
    "row",
    [
        None,
        (0, date(2026, 3, 29), date(2026, 3, 29), "UTC"),
        (1, date(2026, 3, 30), date(2026, 3, 29), "UTC"),
        (1, date(2026, 3, 29), date(2026, 3, 29), "not/a-zone"),
        (1, date(9999, 12, 30), date(9999, 12, 31), "UTC"),
        (1, date(2018, 8, 12), date(2018, 8, 12), "America/Santiago"),
        (1, date(2026, 10, 25), date(2026, 10, 25), "Atlantic/Azores"),
    ],
)
def test_invalid_or_ambiguous_edition_envelope_is_unavailable(monkeypatch, row):
    assert resolve(monkeypatch, row) is None


def test_invalid_scope_types_do_not_escape_as_an_owner_model_error(monkeypatch):
    assert (
        resolve(monkeypatch, None, error=ValidationError("Synthetic bad scope")) is None
    )
