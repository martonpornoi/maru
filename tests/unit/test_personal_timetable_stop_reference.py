"""Current personal context excludes stopped Programme without erasing history."""

from unittest.mock import MagicMock
from uuid import UUID

import pytest

from maru.events import personal_timetable_queries as queries


@pytest.mark.parametrize(
    ("resolver", "row"),
    [
        (queries.resolve_personal_timetable_edition_label, ("Synthetic edition", 4)),
        (
            queries.resolve_personal_timetable_edition_choice,
            (
                UUID(int=1),
                UUID(int=2),
                UUID(int=3),
                "Synthetic edition",
                "synthetic",
                4,
            ),
        ),
    ],
)
@pytest.mark.parametrize("available", [False, True])
def test_terminal_exclusion_is_exact_and_part_of_the_owner_query(
    monkeypatch, resolver, row, available
):
    query = MagicMock()
    query.exclude.return_value = query
    query.values_list.return_value = query
    query.first.return_value = row if available else None
    scope_filter = MagicMock(return_value=query)
    monkeypatch.setattr(queries.EventEdition.objects, "filter", scope_filter)
    result = resolver(organization_id=UUID(int=1), edition_id=UUID(int=2))
    scope_filter.assert_called_once_with(
        id=UUID(int=2), organization_id=UUID(int=1), series__organization_id=UUID(int=1)
    )
    query.exclude.assert_called_once_with(
        adoption_profile_code="programme_operations",
        adoption_profile_version=1,
        lifecycle__in=("archived", "cancelled"),
    )
    if available:
        assert result.name == "Synthetic edition"
        assert result.version == 4
    else:
        assert result is None
