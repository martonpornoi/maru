"""Bounded metadata hashing cannot turn an incomplete page into stop evidence."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from maru.events import programme_stop_inventory as inventory

NOW = datetime(2030, 9, 1, tzinfo=UTC)


def _source(**changes):
    return replace(
        inventory.ProgrammeStopMetadataSource(
            "proposals",
            ("id", "updated_at", "state", "aggregate_version"),
            ((UUID(int=1), NOW, "draft", 1), (UUID(int=2), NOW, "submitted", 2)),
            "state",
        ),
        **changes,
    )


def _build(**changes):
    return inventory.build_programme_stop_inventory(
        **{
            "owner": "applications",
            "organization_id": UUID(int=10),
            "edition_id": UUID(int=11),
            "sources": (_source(),),
            **changes,
        }
    )


def test_source_identifiers_never_escape_the_minimized_counts():
    result = _build()
    assert result.owner == "applications"
    assert result.collections == (
        inventory.ProgrammeStopCollectionCount(
            "proposals",
            2,
            (("draft", 1), ("submitted", 1)),
        ),
    )
    assert str(UUID(int=1)) not in repr(result)
    assert result == _build()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("owner", "unknown"),
        ("owner", []),
        ("organization_id", "wrong"),
        ("edition_id", UUID(int=0)),
        ("sources", []),
        ("sources", ()),
        ("sources", (object(),)),
    ],
)
def test_invalid_envelope_fails_closed(field, value):
    with pytest.raises(inventory.ProgrammeStopInventoryUnavailableError):
        _build(**{field: value})


@pytest.mark.parametrize(
    "changes",
    [
        {"code": "Private free text"},
        {"code": ""},
        {"fields": []},
        {"fields": ("version", "id")},
        {"fields": ("id", "id")},
        {"fields": ("id", [])},
        {"fields": ("id", 1)},
        {"state_field": "absent"},
        {"rows": []},
        {"rows": ((UUID(int=0), NOW, "draft", 1),)},
        {"rows": ((UUID(int=1), NOW, "private reason", 1),)},
        {"rows": ((UUID(int=1), NOW, "draft", {}),)},
        {"rows": ((UUID(int=1),),)},
        {"rows": ((UUID(int=1), NOW.replace(tzinfo=None), "draft", 1),)},
        {"rows": ((UUID(int=1), NOW, "draft", "x" * 129),)},
    ],
)
def test_malformed_source_is_not_partially_counted(changes):
    with pytest.raises(inventory.ProgrammeStopInventoryUnavailableError):
        _build(sources=(_source(**changes),))


def test_duplicate_or_unsorted_row_identity_is_not_double_counted():
    for rows in ((_source().rows[0],) * 2, tuple(reversed(_source().rows))):
        with pytest.raises(inventory.ProgrammeStopInventoryUnavailableError):
            _build(sources=(_source(rows=rows),))
    with pytest.raises(inventory.ProgrammeStopInventoryUnavailableError):
        _build(sources=(_source(), _source()))


@pytest.mark.parametrize(
    "limit",
    ["MAX_STOP_SOURCE_ROWS", "MAX_STOP_SOURCE_BYTES", "MAX_STOP_METADATA_FIELDS"],
)
def test_each_resource_limit_withholds_the_complete_result(monkeypatch, limit):
    monkeypatch.setattr(inventory, limit, 1)
    with pytest.raises(inventory.ProgrammeStopInventoryUnavailableError):
        _build()


def test_inventory_and_state_bounds_are_checked(monkeypatch):
    monkeypatch.setattr(inventory, "MAX_STOP_COLLECTIONS", 1)
    with pytest.raises(inventory.ProgrammeStopInventoryUnavailableError):
        _build(sources=(_source(), _source(code="other")))
    monkeypatch.setattr(inventory, "MAX_STOP_METADATA_STATES", 1)
    with pytest.raises(inventory.ProgrammeStopInventoryUnavailableError):
        _build()


def test_fingerprint_binds_owner_scope_version_state_and_column_meaning():
    original = _build()
    for changes in (
        {"owner": "programme"},
        {"organization_id": uuid4()},
        {"edition_id": uuid4()},
        {"sources": (_source(state_field=None),)},
        {"sources": (_source(rows=(_source().rows[0],)),)},
        {"sources": (_source(rows=((UUID(int=1), NOW, "draft", 2),)),)},
    ):
        assert _build(**changes).source_fingerprint != original.source_fingerprint


def test_empty_known_collection_is_complete_not_unavailable():
    result = _build(sources=(_source(rows=()),))
    assert result.collections[0].total == 0
    assert result.collections[0].states == ()


def test_streaming_failure_does_not_read_later_collections(monkeypatch):
    visited = []

    def sources():
        visited.append("first")
        yield _source()
        visited.append("second")
        yield _source(code="other")

    monkeypatch.setattr(inventory, "MAX_STOP_SOURCE_BYTES", 1)
    with pytest.raises(inventory.ProgrammeStopInventoryUnavailableError):
        _build(sources=sources())
    assert visited == ["first"]


def test_stream_and_tuple_have_identical_complete_evidence():
    assert _build(sources=iter((_source(),))) == _build()


def test_non_iterable_sources_fail_without_a_partial_result():
    with pytest.raises(inventory.ProgrammeStopInventoryUnavailableError):
        _build(sources=None)
