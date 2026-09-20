"""Keep complete Shift-link history separate from private worker records."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.workforce import programme_exit_queries as archive


@pytest.fixture
def source(monkeypatch):
    args = {
        name: UUID(int=i)
        for i, name in enumerate(
            ("actor_id", "organization_id", "edition_id", "correlation_id"), start=1
        )
    }
    binding = SimpleNamespace(binding_id=UUID(int=5), version=3)
    inventory = [(binding.binding_id, UUID(int=6), binding.version)]
    query = Mock()
    query.return_value.order_by.return_value.values_list.side_effect = lambda *_: (
        inventory
    )
    monkeypatch.setattr(archive.ProgrammeShiftBinding.objects, "filter", query)
    page_entries = tuple(
        SimpleNamespace(
            binding=SimpleNamespace(binding_id=binding.binding_id, version=i)
        )
        for i in (1, 2, 3)
    )
    page = SimpleNamespace(
        through_version=3, entries=page_entries, next_after_version=None
    )
    methods = {
        "purpose": ("authorize_programme_archive_scope", Mock()),
        "programme": ("authorize_programme_scope", Mock()),
        "workforce": (
            "authorize_programme_staffing_adapter",
            Mock(
                return_value=SimpleNamespace(
                    reason_code="allowed", obligations=frozenset()
                )
            ),
        ),
        "parent": ("lock_programme_staffing_scope", Mock()),
        "current": ("load_programme_bindings", Mock(return_value=(binding,))),
        "history": ("load_programme_binding_history", Mock(return_value=page)),
        "audit": ("append_audit", Mock()),
    }
    for name, method in methods.values():
        monkeypatch.setattr(archive, name, method)
    return SimpleNamespace(
        read=archive.load_programme_exit_bindings.__wrapped__,
        args=args,
        binding=binding,
        inventory=inventory,
        query=query,
        page=page,
        **{key: method for key, (_, method) in methods.items()},
    )


def test_complete_history_exact_scope_and_all_three_authorities(source):
    result = source.read(**source.args)
    assert result[0].item_id == source.inventory[0][1]
    assert result[0].current == source.binding
    assert [row.binding.version for row in result[0].history] == [1, 2, 3]
    assert (
        source.purpose.call_count
        == source.programme.call_count
        == source.workforce.call_count
        == 3
    )
    assert source.programme.call_args.kwargs["requested_fields"] == frozenset(
        {"staffing_requirements", "staffing_history"}
    )
    assert source.query.call_args.kwargs == {
        "organization_id": source.args["organization_id"],
        "edition_id": source.args["edition_id"],
    }
    assert (
        source.audit.call_args.args[0].operation
        == "workforce.programme_binding.exit_owner"
    )
    assert str(source.binding.binding_id) not in repr(result)


def test_complete_paging_uses_original_fixed_ceiling(source):
    source.history.side_effect = [
        SimpleNamespace(
            through_version=3, entries=source.page.entries[:2], next_after_version=2
        ),
        SimpleNamespace(
            through_version=3, entries=source.page.entries[2:], next_after_version=None
        ),
    ]
    assert len(source.read(**source.args)[0].history) == 3
    assert source.history.call_args.kwargs["after_version"] == 2
    assert source.history.call_args.kwargs["through_version"] == 3


def test_empty_owner_is_authorized_and_audited_without_item_probe(source):
    source.inventory.clear()
    assert source.read(**source.args) == ()
    source.current.assert_not_called()
    source.audit.assert_called_once()
    assert source.workforce.call_count == 3


@pytest.mark.parametrize(
    "boundary",
    ["purpose", "programme", "workforce", "parent", "current", "history", "audit"],
)
def test_any_required_boundary_failure_refuses(source, boundary):
    getattr(source, boundary).side_effect = RuntimeError("synthetic boundary failure")
    with pytest.raises(RuntimeError, match="synthetic boundary failure"):
        source.read(**source.args)


@pytest.mark.parametrize("bound", ["MAX_EXIT_BINDINGS", "MAX_EXIT_BINDING_REVISIONS"])
def test_no_truncation_at_owner_limits(source, monkeypatch, bound):
    monkeypatch.setattr(archive, bound, 0)
    with pytest.raises(archive.ProgrammeStaffingUnavailableError):
        source.read(**source.args)
    source.audit.assert_not_called()


def test_missing_current_binding_is_not_empty_success(source):
    source.current.return_value = ()
    with pytest.raises(archive.ProgrammeStaffingUnavailableError):
        source.read(**source.args)


def test_changed_final_current_source_refuses(source):
    source.current.side_effect = [(source.binding,), ()]
    with pytest.raises(archive.ProgrammeStaffingUnavailableError):
        source.read(**source.args)


def test_changed_final_inventory_refuses(source):
    source.query.return_value.order_by.return_value.values_list.side_effect = [
        source.inventory,
        [],
    ]
    with pytest.raises(archive.ProgrammeStaffingUnavailableError):
        source.read(**source.args)


@pytest.mark.parametrize(
    "change",
    [
        {"through_version": 4},
        {"entries": ()},
        {"next_after_version": 3},
        {
            "entries": (
                SimpleNamespace(
                    binding=SimpleNamespace(binding_id=UUID(int=5), version=2)
                ),
            )
        },
        {
            "entries": (
                SimpleNamespace(
                    binding=SimpleNamespace(binding_id=UUID(int=99), version=1)
                ),
            )
        },
    ],
)
def test_moving_gapped_foreign_or_incomplete_history_refuses(source, change):
    source.history.return_value = SimpleNamespace(**{**vars(source.page), **change})
    with pytest.raises(archive.ProgrammeStaffingUnavailableError):
        source.read(**source.args)


def test_latest_history_must_match_current_binding(source):
    source.page.entries[-1].binding.changed = True
    with pytest.raises(archive.ProgrammeStaffingUnavailableError):
        source.read(**source.args)
