"""Minimized owner-source contract for future accountable setup."""

from dataclasses import fields
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from maru.organizations import programme_setup_references as source
from maru.organizations.representation_catalog import EXECUTIVE_BOARD, MARU_OPERATORS


def query_row(manager, row):
    values = manager.filter.return_value.order_by.return_value.values
    values.return_value.first.return_value = row


@pytest.fixture
def world(monkeypatch):
    organization = {
        "id": UUID(int=1),
        "name": "Maru synthetic organizers",
        "lifecycle": "draft",
        "default_language_codes": ["en"],
        "default_time_zone": "UTC",
        "representation__id": None,
        "representation__code": None,
        "representation__name": None,
        "representation__aggregate_version": None,
        "representation__state": None,
    }
    series = {"id": UUID(int=2), "name": "Maru synthetic series", "profile_version": 1}
    organizations = MagicMock()
    query_row(organizations, organization)
    all_series = MagicMock()
    query_row(all_series, series)
    monkeypatch.setattr(source.Organization, "objects", organizations)
    monkeypatch.setattr(source.ConventionSeries, "objects", all_series)
    return organization, series, organizations, all_series


def load(**changes):
    return source.resolve_programme_setup_foundation(
        organization_id=UUID(int=1), **changes
    )


def represent(organization, definition=MARU_OPERATORS, *, active=False):
    organization.update(
        {
            "lifecycle": "active" if active else "draft",
            "representation__id": UUID(int=3),
            "representation__code": definition.code,
            "representation__name": definition.name,
            "representation__aggregate_version": 1,
            "representation__state": "active" if active else "provisioning",
        }
    )


def test_draft_reference_is_minimized_and_does_not_discover_a_series(world):
    _organization, _series, organizations, all_series = world
    result = load()
    assert result.organization_id == UUID(int=1)
    assert result.organization_name == "Maru synthetic organizers"
    assert result.default_language_codes == ("en",)
    assert result.representation_id is None
    assert result.series_id is None
    assert len(result.fingerprint) == 64
    organizations.filter.assert_called_once_with(
        id=UUID(int=1), lifecycle__in=("draft", "active")
    )
    all_series.filter.assert_not_called()
    organizations.filter.return_value.order_by.return_value.values.assert_called_once_with(
        "id",
        "name",
        "lifecycle",
        "default_language_codes",
        "default_time_zone",
        "representation__id",
        "representation__code",
        "representation__name",
        "representation__aggregate_version",
        "representation__state",
    )
    assert {field.name for field in fields(result)} == {
        "organization_id",
        "organization_name",
        "organization_lifecycle",
        "default_language_codes",
        "default_time_zone",
        "representation_id",
        "representation_code",
        "representation_version",
        "representation_state",
        "series_id",
        "series_name",
        "series_version",
        "fingerprint",
    }


def test_series_reference_binds_exact_parent_active_state_and_version(world):
    _organization, _series, _organizations, all_series = world
    result = load(series_id=UUID(int=2))
    assert result.series_id == UUID(int=2)
    assert result.series_name == "Maru synthetic series"
    assert result.series_version == 1
    all_series.filter.assert_called_once_with(
        id=UUID(int=2), organization_id=UUID(int=1), is_active=True
    )
    assert result.fingerprint != load().fingerprint


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("definition", [EXECUTIVE_BOARD, MARU_OPERATORS])
def test_existing_truthful_representation_is_reused_without_upgrade(
    world, definition, active
):
    organization, *_ = world
    represent(organization, definition, active=active)
    result = load()
    assert result.representation_id == UUID(int=3)
    assert result.representation_code == definition.code
    assert result.representation_state == ("active" if active else "provisioning")
    assert result.representation_version == 1


@pytest.mark.parametrize("field", ["organization_id", "series_id"])
@pytest.mark.parametrize(
    "value", [False, 1, "00000000-0000-0000-0000-000000000001", UUID(int=0)]
)
def test_invalid_scope_fails_before_any_owner_query(world, field, value):
    _organization, _series, organizations, all_series = world
    values = {"organization_id": UUID(int=1), field: value}
    assert source.resolve_programme_setup_foundation(**values) is None
    organizations.filter.assert_not_called()
    all_series.filter.assert_not_called()


def test_unavailable_organization_does_not_query_the_selected_series(world):
    _organization, _series, organizations, all_series = world
    query_row(organizations, None)
    assert load(series_id=UUID(int=2)) is None
    all_series.filter.assert_not_called()


def test_foreign_inactive_or_missing_series_returns_no_partial_foundation(world):
    _organization, _series, _organizations, all_series = world
    query_row(all_series, None)
    assert load(series_id=UUID(int=2)) is None
    all_series.filter.assert_called_once_with(
        id=UUID(int=2), organization_id=UUID(int=1), is_active=True
    )


def test_active_organization_without_representation_is_unavailable(world):
    organization, _series, _organizations, all_series = world
    organization["lifecycle"] = "active"
    assert load(series_id=UUID(int=2)) is None
    all_series.filter.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("representation__code", "unregistered"),
        ("representation__name", "Invented constitutional office"),
        ("representation__state", "suspended"),
        ("representation__state", "active"),
    ],
)
def test_incoherent_representation_returns_no_partial_or_guessed_state(
    world, field, value
):
    organization, _series, _organizations, all_series = world
    represent(organization)
    organization[field] = value
    assert load(series_id=UUID(int=2)) is None
    all_series.filter.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "Another synthetic organization"),
        ("default_language_codes", ["en", "hu"]),
        ("default_time_zone", "Europe/Budapest"),
        ("representation__aggregate_version", 2),
        ("representation__id", UUID(int=4)),
    ],
)
def test_each_setup_relevant_organization_fact_changes_the_snapshot(
    world, field, value
):
    organization, *_ = world
    represent(organization)
    original = load().fingerprint
    organization[field] = value
    assert load().fingerprint != original


def test_representation_kind_and_lifecycle_changes_change_the_snapshot(world):
    organization, *_ = world
    original = load().fingerprint
    represent(organization)
    provisioning = load().fingerprint
    represent(organization, active=True)
    active = load().fingerprint
    represent(organization, EXECUTIVE_BOARD, active=True)
    assert len({original, provisioning, active, load().fingerprint}) == 4


@pytest.mark.parametrize(
    ("field", "value"), [("name", "Another synthetic series"), ("profile_version", 2)]
)
def test_series_facts_change_the_original_source_snapshot(world, field, value):
    _organization, series, *_ = world
    original = load(series_id=UUID(int=2)).fingerprint
    series[field] = value
    assert load(series_id=UUID(int=2)).fingerprint != original


def test_reference_does_not_share_a_mutable_language_list_with_the_source(world):
    organization, *_ = world
    result = load()
    organization["default_language_codes"].append("hu")
    assert result.default_language_codes == ("en",)
    assert load().fingerprint != result.fingerprint
