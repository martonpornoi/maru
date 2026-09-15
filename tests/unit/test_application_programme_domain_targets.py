"""Closed target SQL scope, complete bounds and sole canonical fresh validation."""

from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.applications import programme_domain_targets as targets
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from tests.unit import test_application_programme_person_reference_commands as existing

writer = existing.writer


@pytest.fixture
def catalog(monkeypatch):
    row = {
        "id": UUID(int=40),
        "code": "culture",
        "label": "Culture",
        "description": "Guidance",
    }
    manager = Mock()
    query = manager.filter.return_value
    query.filter.return_value = query
    query.order_by.return_value = query
    query.values.return_value = [row]
    monkeypatch.setattr(targets.ProgrammeCallTrack, "objects", manager)
    other = Mock()
    monkeypatch.setattr(targets.ProgrammeCallFormat, "objects", other)
    return manager, query, row, other


def scope(**changes):
    return {
        "organization_id": UUID(int=2),
        "edition_id": UUID(int=3),
        "call_id": UUID(int=30),
        "kind": "programme.call-track",
    } | changes


def test_catalog_query_scopes_both_target_and_owning_call(catalog):
    manager, query, _row, other = catalog
    result = targets._domain_options(**scope())
    assert result == (
        targets.ProgrammeDomainOption(UUID(int=40), "culture", "Culture", "Guidance"),
    )
    manager.filter.assert_called_once_with(
        organization_id=UUID(int=2),
        edition_id=UUID(int=3),
        call_id=UUID(int=30),
        call__organization_id=UUID(int=2),
        call__edition_id=UUID(int=3),
    )
    query.order_by.assert_called_once_with("position", "id")
    query.values.assert_called_once_with("id", "code", "label", "description")
    other.assert_not_called()


def test_format_kind_routes_only_to_the_closed_format_owner(catalog):
    manager, query, _row, other = catalog
    other.filter.return_value = query
    assert targets._domain_options(**scope(kind="programme.call-format"))
    manager.filter.assert_not_called()
    other.filter.assert_called_once()


@pytest.mark.parametrize(
    "kind", ["unknown.kind", "programme.person", "programme.call-track "]
)
def test_unknown_kind_never_touches_either_target_manager(catalog, kind):
    manager, _, _, other = catalog
    with pytest.raises(Denied):
        targets._domain_options(**scope(kind=kind))
    manager.filter.assert_not_called()
    other.filter.assert_not_called()


@pytest.mark.parametrize(
    ("kind", "maximum"), [("programme.call-track", 64), ("programme.call-format", 32)]
)
def test_complete_catalog_overflow_is_not_silently_truncated(catalog, kind, maximum):
    _manager, query, row, other = catalog
    other.filter.return_value = query
    query.values.return_value = [
        dict(row, id=UUID(int=100 + i)) for i in range(maximum)
    ]
    assert len(targets._domain_options(**scope(kind=kind))) == maximum
    query.values.return_value.append(dict(row, id=UUID(int=900)))
    with pytest.raises(Denied):
        targets._domain_options(**scope(kind=kind))


@pytest.mark.parametrize(
    "change",
    [
        {"id": UUID(int=0)},
        {"id": "not-a-uuid"},
        {"label": ""},
        {"label": "x" * 161},
        {"code": "x" * 81},
        {"description": "x" * 4001},
        {"description": None},
    ],
)
def test_malformed_owner_projection_is_not_disclosed(catalog, change):
    _, query, row, _ = catalog
    query.values.return_value = [row | change]
    with pytest.raises(Denied):
        targets._domain_options(**scope())


def test_duplicate_or_mismatched_exact_target_is_rejected(catalog):
    _, query, row, _ = catalog
    query.values.return_value = [row, row]
    with pytest.raises(Denied):
        targets._domain_target(**scope(), target_id=UUID(int=40))
    with pytest.raises(Denied):
        targets._domain_options(**scope())
    query.values.return_value = [row]
    with pytest.raises(Denied):
        targets._domain_target(**scope(), target_id=UUID(int=41))


def test_target_absence_is_neutral_without_cross_call_fallback(catalog):
    manager, query, _, _ = catalog
    query.values.return_value = []
    assert targets._domain_target(**scope(), target_id=UUID(int=40)) is None
    assert manager.filter.call_count == 1
    query.filter.assert_called_once_with(id=UUID(int=40))


@pytest.mark.parametrize(
    "value", [True, 0, "garbage", str(UUID(int=0)), str(UUID(int=40)).replace("-", "")]
)
def test_invalid_canonical_value_never_queries_a_target(catalog, value):
    manager, _, _, other = catalog
    assert not targets._valid_domain_answer(**scope(), value=value)
    manager.filter.assert_not_called()
    other.filter.assert_not_called()


def test_explicit_registered_clear_never_queries_a_target(catalog):
    manager, _, _, _ = catalog
    assert targets._valid_domain_answer(**scope(), value=None)
    assert not targets._valid_domain_answer(**scope(kind="unknown.kind"), value=None)
    manager.filter.assert_not_called()


def test_fresh_canonical_writer_validates_exact_domain_before_one_answer_append(
    writer, catalog
):
    writer.question.field_type = "domain_reference"
    writer.question.reference_kind = "programme.call-track"
    writer.proposal.call_id = UUID(int=30)
    assert existing.append() == "canonical-result"
    assert writer.answers.create.call_args.kwargs["value"] == str(UUID(int=40))
    writer.resolve_active_verified_person_reference.assert_not_called()
    assert catalog[0].filter.call_args.kwargs["call_id"] == UUID(int=30)
    writer.record_success.assert_called_once()


def test_wrong_call_target_or_unknown_kind_cannot_write(writer, catalog):
    writer.question.field_type = "domain_reference"
    writer.question.reference_kind = "programme.call-track"
    writer.proposal.call_id = UUID(int=30)
    catalog[1].values.return_value = []
    with pytest.raises(existing.commands.ApplicationsProgrammeUnavailableError):
        existing.append()
    writer.question.reference_kind = "unknown.kind"
    with pytest.raises(existing.commands.ApplicationsProgrammeUnavailableError):
        existing.append(value=None)
    writer.answers.create.assert_not_called()
    writer.record_success.assert_not_called()


def test_original_successful_replay_precedes_fresh_catalog_and_identity_validation(
    writer, catalog
):
    writer.question.field_type = "domain_reference"
    writer.question.reference_kind = "unknown.kind"
    writer.replay.return_value = "original-receipt"
    assert existing.append() == "original-receipt"
    catalog[0].filter.assert_not_called()
    catalog[3].filter.assert_not_called()
    writer.locked_proposal.assert_not_called()
    writer.answers.create.assert_not_called()
