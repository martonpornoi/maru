"""Owner-composition failures are cheap to exercise without rebuilding a database."""

from contextlib import nullcontext
from dataclasses import replace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from maru.scheduling import operator_output_queries as queries
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.operator_scope import OperatorReadRequest
from tests.unit.test_programme_operator_rendering import (
    full_sheet as full_sheet,  # noqa: PLC0414
)
from tests.unit.test_programme_operator_rendering import (
    sheet as sheet,  # noqa: PLC0414
)


@pytest.fixture
def owners(monkeypatch, full_sheet):
    monkeypatch.setattr(
        queries, "operator_read", lambda *_args, **_kwargs: nullcontext()
    )
    monkeypatch.setattr(queries.timezone, "now", lambda: full_sheet.checked_at)
    sources = {
        "load_operator_release_reference": full_sheet.reference,
        "load_operator_programme_copy": tuple(row.copy for row in full_sheet.entries),
        "load_operator_wayfinding": tuple(row.room for row in full_sheet.entries),
        "load_operator_delivery_instructions": tuple(
            row.delivery for row in full_sheet.entries
        ),
        "load_operator_staffing": full_sheet.staffing,
    }
    mocks = {name: MagicMock(return_value=value) for name, value in sources.items()}
    for name, mock in mocks.items():
        monkeypatch.setattr(queries, name, mock)
    return mocks


def request_for(sheet):
    return OperatorReadRequest(
        uuid4(),
        sheet.organization_id,
        sheet.edition_id,
        uuid4(),
        sheet.kind,
        sheet.target_id,
    )


def test_complete_composition_rechecks_every_requested_owner(full_sheet, owners):
    request = request_for(full_sheet)
    result = queries.load_operator_run_sheet(request, layers=full_sheet.layers)
    assert result == full_sheet
    for mock in owners.values():
        assert mock.call_count == 2
    for call in owners["load_operator_delivery_instructions"].call_args_list:
        assert call.args == (request,)
        assert call.kwargs["fields"] == frozenset(
            {"technical", "accessibility", "media"}
        )


def test_default_composition_never_calls_optional_content_queries(full_sheet, owners):
    result = queries.load_operator_run_sheet(request_for(full_sheet))
    assert result.layers == frozenset()
    assert result.staffing is None
    assert result.entries[0].delivery is None
    owners["load_operator_staffing"].assert_not_called()
    owners["load_operator_delivery_instructions"].assert_not_called()


def test_empty_approved_scope_still_requests_and_rechecks_all_selected_fields(
    full_sheet, owners
):
    owners["load_operator_release_reference"].return_value = replace(
        full_sheet.reference, occurrences=()
    )
    for source in (
        "load_operator_programme_copy",
        "load_operator_wayfinding",
        "load_operator_delivery_instructions",
    ):
        owners[source].return_value = ()
    owners["load_operator_staffing"].return_value = replace(
        full_sheet.staffing, links=(), demands=()
    )
    result = queries.load_operator_run_sheet(
        request_for(full_sheet), layers=full_sheet.layers
    )
    assert result.entries == ()
    assert result.staffing is not None
    assert result.staffing.demands == ()
    for mock in owners.values():
        assert mock.call_count == 2


@pytest.mark.parametrize(
    "source",
    [
        "load_operator_programme_copy",
        "load_operator_wayfinding",
        "load_operator_delivery_instructions",
        "load_operator_staffing",
    ],
)
def test_late_owner_denial_never_returns_an_earlier_success(full_sheet, owners, source):
    owners[source].side_effect = [
        owners[source].return_value,
        SchedulingAuthorizationDeniedError,
    ]
    with pytest.raises(SchedulingAuthorizationDeniedError):
        queries.load_operator_run_sheet(
            request_for(full_sheet), layers=full_sheet.layers
        )


@pytest.mark.parametrize(
    "source",
    [
        "load_operator_programme_copy",
        "load_operator_wayfinding",
        "load_operator_delivery_instructions",
        "load_operator_staffing",
    ],
)
def test_requested_owner_cannot_disappear_as_none(full_sheet, owners, source):
    owners[source].return_value = None
    with pytest.raises(SchedulingUnavailableError):
        queries.load_operator_run_sheet(
            request_for(full_sheet), layers=full_sheet.layers
        )


@pytest.mark.parametrize(
    ("source", "change"),
    [
        (
            "load_operator_programme_copy",
            lambda value: (replace(value[0], summary="Changed reviewed copy"),),
        ),
        (
            "load_operator_wayfinding",
            lambda value: (
                replace(value[0], venue_version=value[0].venue_version + 1),
            ),
        ),
        (
            "load_operator_delivery_instructions",
            lambda value: (replace(value[0], version=value[0].version + 1),),
        ),
        ("load_operator_staffing", lambda value: replace(value, demands=())),
        (
            "load_operator_release_reference",
            lambda value: replace(value, pointer_version=value.pointer_version + 1),
        ),
    ],
)
def test_late_source_movement_withholds_the_whole_composition(
    full_sheet, owners, source, change
):
    value = owners[source].return_value
    owners[source].side_effect = [value, change(value)]
    with pytest.raises(SchedulingUnavailableError):
        queries.load_operator_run_sheet(
            request_for(full_sheet), layers=full_sheet.layers
        )


@pytest.mark.parametrize(
    "source",
    [
        "load_operator_programme_copy",
        "load_operator_wayfinding",
        "load_operator_delivery_instructions",
    ],
)
@pytest.mark.parametrize("fault", ["missing", "duplicate", "wrong_type"])
def test_incomplete_or_untyped_owner_results_are_never_a_complete_run_sheet(
    full_sheet, owners, source, fault
):
    value = owners[source].return_value
    owners[source].return_value = (
        () if fault == "missing" else value * 2 if fault == "duplicate" else (object(),)
    )
    with pytest.raises(SchedulingUnavailableError):
        queries.load_operator_run_sheet(
            request_for(full_sheet), layers=full_sheet.layers
        )


@pytest.mark.parametrize("layers", [{"staffing"}, frozenset({"roster"})])
def test_unknown_layer_requests_fail_before_owner_content_is_loaded(
    full_sheet, owners, layers
):
    with pytest.raises(SchedulingAuthorizationDeniedError):
        queries.load_operator_run_sheet(request_for(full_sheet), layers=layers)
    for mock in owners.values():
        mock.assert_not_called()
