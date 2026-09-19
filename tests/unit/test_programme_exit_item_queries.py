"""Exercise item composition, field ceilings and complete bounded histories."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.authorization.policy import PolicyDecision
from maru.programme import exit_item_queries as item
from maru.programme import host_queries as hosts
from maru.programme import queries
from maru.programme import staffing_queries as staffing
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.exit_core_queries import ProgrammeExitCore
from maru.programme.staffing_inputs import ProgrammeStaffingExpectation


def _requirement(version=1):
    return staffing.ProgrammeStaffingRequirementView(
        UUID(int=20),
        UUID(int=21),
        version,
        UUID(int=100 + version),
        version,
        1,
        "active",
        ProgrammeStaffingExpectation(
            UUID(int=22),
            "Preparation",
            "Stage",
            "Work",
            "Report to lead",
            datetime(2030, 8, 2, 8, tzinfo=UTC),
            datetime(2030, 8, 2, 10, tzinfo=UTC),
            2,
            15,
            30,
        ),
    )


def _staff_entry(current):
    return staffing.ProgrammeStaffingHistoryEntry(
        current,
        "create",
        UUID(int=1),
        "Restricted rationale",
        datetime(2026, 9, 19, tzinfo=UTC),
    )


@pytest.fixture
def owner(monkeypatch):
    actor, organization, edition, identifier, correlation = (
        UUID(int=i) for i in range(1, 6)
    )
    args = {
        "actor_id": actor,
        "organization_id": organization,
        "edition_id": edition,
        "item_id": identifier,
        "correlation_id": correlation,
        "reason": "Retained item export",
    }
    events = []
    scope = SimpleNamespace(
        actor_id=actor,
        organization_id=organization,
        edition_id=edition,
        decision=PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset({"audit_sensitive_read"}),
            reason_code="synthetic",
        ),
    )
    auth = Mock(side_effect=lambda **_kwargs: (events.append("authorize"), scope)[1])
    monkeypatch.setattr(item, "authorize_programme_scope", auth)
    monkeypatch.setattr(queries, "authorize_programme_scope", auth)
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    audit = Mock(side_effect=lambda _record: events.append("audit"))
    monkeypatch.setattr(queries, "append_audit", audit)
    state = hosts.ProgrammeHostStateProjection(UUID(int=10), "host", "confirmed", 1, 1)
    history = hosts.ProgrammeHostHistoryEntry(
        state, "confirm", actor, "Host rationale", datetime(2026, 9, 19, tzinfo=UTC), 1
    )
    requirement = _requirement()
    values = {
        "load_programme_host_roster": hosts.ProgrammeHostRosterSnapshot(
            1,
            (
                hosts.ProgrammeHostRosterEntry(
                    state,
                    UUID(int=11),
                    person_current=True,
                    display_label="Synthetic host",
                ),
            ),
        ),
        "load_programme_exit_core": ProgrammeExitCore(
            queries.ProgrammePrivateItemProjection(
                queries.ProgrammeItemProjection(
                    identifier, "ceremony", "organizer_core", "active", 1
                ),
                queries.ProgrammeWorkingProjection(
                    "Private title", "Private summary", 1
                ),
            ),
            (),
            (),
            (),
            (),
            (),
        ),
        "load_programme_host_dependencies": hosts.ProgrammeHostDependencySnapshot(
            identifier,
            1,
            1,
            "programme.host-dependencies@1",
            (
                hosts.ProgrammeHostAvailabilityProjection(
                    state.host_id, 1, 1, "not_shared", ()
                ),
            ),
        ),
        "load_programme_staffing_requirements": staffing.ProgrammeStaffingOverview(
            identifier, 1, (requirement,), "active"
        ),
        "load_programme_host_history": (history,),
        "load_programme_staffing_history": staffing.ProgrammeStaffingHistoryPage(
            1, (_staff_entry(requirement),), None
        ),
    }
    readers = {}
    for module, names in (
        (
            hosts,
            (
                "load_programme_host_roster",
                "load_programme_host_dependencies",
                "load_programme_host_history",
            ),
        ),
        (item.core, ("load_programme_exit_core",)),
        (
            staffing,
            ("load_programme_staffing_requirements", "load_programme_staffing_history"),
        ),
    ):
        for name in names:

            def read(*positional, name=name, **kwargs):
                events.append(name)
                if positional:
                    request = positional[0]
                    for key in (
                        "actor_id",
                        "organization_id",
                        "edition_id",
                        "item_id",
                        "correlation_id",
                    ):
                        assert getattr(request, key) == args[key]
                    assert request.source_channel == "programme-exit"
                else:
                    assert all(kwargs[key] == value for key, value in args.items())
                return values[name]

            readers[name] = Mock(side_effect=read)
            monkeypatch.setattr(module, name, readers[name])
    return SimpleNamespace(
        args=args,
        events=events,
        auth=auth,
        audit=audit,
        scope=scope,
        readers=readers,
        values=values,
        state=state,
        requirement=requirement,
    )


def test_owner_calls_lock_roster_before_core_and_recheck_all_fields(owner):
    result = item.load_programme_exit_item(**owner.args)
    assert result.roster == owner.values["load_programme_host_roster"]
    assert result.host_histories == (owner.values["load_programme_host_history"],)
    assert result.staffing_histories == (
        owner.values["load_programme_staffing_history"].entries,
    )
    assert repr(result) == "ProgrammeExitItem()"
    assert owner.events[:7] == ["authorize"] * 7
    assert owner.events[7:9] == [
        "load_programme_host_roster",
        "load_programme_exit_core",
    ]
    assert owner.events[-8:] == ["authorize"] * 7 + ["audit"]
    assert all(not call.kwargs.get("lock") for call in owner.auth.call_args_list)
    calls = owner.auth.call_args_list
    assert calls[5].kwargs["requested_fields"] == frozenset(
        {"host_roster", "host_history", "shared_host_availability"}
    )
    assert calls[6].kwargs["requested_fields"] == frozenset(
        {"staffing_requirements", "staffing_history"}
    )
    record = owner.audit.call_args.args[0]
    assert record.operation == "programme.query.exit_item"
    assert record.safe_metadata["access_purpose"] == owner.args["reason"]
    assert record.safe_metadata["target_count"] == 1


@pytest.mark.parametrize("call", range(14))
def test_every_initial_and_final_authorization_denial_releases_nothing(owner, call):
    owner.auth.side_effect = [owner.scope] * call + [ProgrammeAuthorizationDeniedError]
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        item.load_programme_exit_item(**owner.args)
    assert owner.audit.call_args.args[0].outcome == "deny"
    if call < 7:
        assert not any(reader.called for reader in owner.readers.values())


def test_audit_failure_releases_nothing(owner):
    owner.audit.side_effect = RuntimeError("synthetic audit failure")
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        item.load_programme_exit_item(**owner.args)


@pytest.mark.parametrize(
    "reader",
    [
        "load_programme_host_roster",
        "load_programme_host_dependencies",
        "load_programme_staffing_requirements",
    ],
)
def test_moving_item_version_refuses_whole_collection(owner, reader):
    owner.values[reader] = replace(owner.values[reader], item_version=2)
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        item.load_programme_exit_item(**owner.args)
    owner.audit.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_roster",
        "missing_dependency",
        "wrong_host_version",
        "duplicate_requirement",
        "wrong_scope",
        "wrong_lifecycle",
    ],
)
def test_inconsistent_sets_and_scope_refuse(owner, change):
    values = owner.values
    if change == "duplicate_roster":
        key = "load_programme_host_roster"
        values[key] = replace(values[key], entries=values[key].entries * 2)
    elif change in {"missing_dependency", "wrong_host_version"}:
        key = "load_programme_host_dependencies"
        rows = (
            ()
            if change == "missing_dependency"
            else (replace(values[key].hosts[0], host_version=2),)
        )
        values[key] = replace(values[key], hosts=rows)
    else:
        key = "load_programme_staffing_requirements"
        changes = {
            "duplicate_requirement": {"requirements": values[key].requirements * 2},
            "wrong_scope": {"item_id": UUID(int=999)},
            "wrong_lifecycle": {"item_lifecycle": "withdrawn"},
        }
        values[key] = replace(values[key], **changes[change])
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        item.load_programme_exit_item(**owner.args)


@pytest.mark.parametrize(
    "status",
    [
        "ended",
        "inactive",
        "unconfirmed",
        "not_shared",
        "outside_edition",
        "unavailable",
        "shared",
    ],
)
def test_availability_distinctions_are_preserved_without_reconstruction(owner, status):
    key = "load_programme_host_dependencies"
    owner.values[key] = replace(
        owner.values[key], hosts=(replace(owner.values[key].hosts[0], status=status),)
    )
    result = item.load_programme_exit_item(**owner.args)
    assert result.host_dependencies.hosts[0].status == status
    assert result.host_dependencies.hosts[0].periods == ()


@pytest.mark.parametrize(
    "change", ["empty", "wrong_version", "wrong_host", "wrong_state"]
)
def test_missing_or_mismatched_host_history_is_not_complete(owner, change):
    row = owner.values["load_programme_host_history"][0]
    changes = {
        "wrong_version": {"version": 2},
        "wrong_host": {"host_id": UUID(int=999)},
        "wrong_state": {"state": "removed"},
    }
    owner.values["load_programme_host_history"] = (
        ()
        if change == "empty"
        else (replace(row, relationship=replace(row.relationship, **changes[change])),)
    )
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        item.load_programme_exit_item(**owner.args)


def test_fixed_ceiling_staffing_history_reaches_second_page(owner):
    current = _requirement(51)
    entries = tuple(_staff_entry(_requirement(i)) for i in range(1, 52))
    reader = owner.readers["load_programme_staffing_history"]
    reader.side_effect = [
        staffing.ProgrammeStaffingHistoryPage(51, entries[:50], 50),
        staffing.ProgrammeStaffingHistoryPage(51, entries[50:], None),
    ]
    result = item._staffing_history(Mock(), current, authorizer=Mock())
    assert result == entries
    assert [call.kwargs["after_version"] for call in reader.call_args_list] == [0, 50]
    assert all(call.kwargs["through_version"] == 51 for call in reader.call_args_list)


@pytest.mark.parametrize(
    "change",
    [
        "empty",
        "wrong_ceiling",
        "wrong_cursor",
        "wrong_terms",
        "wrong_occurrence",
        "wrong_sequence",
    ],
)
def test_staffing_history_cannot_truncate_loop_or_substitute_current_terms(
    owner, change
):
    key = "load_programme_staffing_history"
    page = owner.values[key]
    if change in {"empty", "wrong_ceiling", "wrong_cursor"}:
        fields = {
            "empty": {"entries": ()},
            "wrong_ceiling": {"through_version": 2},
            "wrong_cursor": {"next_after_version": 1},
        }[change]
        owner.values[key] = replace(page, **fields)
    else:
        fields = {
            "wrong_terms": {"lifecycle": "retired"},
            "wrong_occurrence": {"occurrence_id": UUID(int=999)},
            "wrong_sequence": {"version": 2},
        }[change]
        owner.values[key] = replace(
            page, entries=(_staff_entry(replace(owner.requirement, **fields)),)
        )
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        item.load_programme_exit_item(**owner.args)


def test_empty_host_and_staffing_sets_are_authorized_complete_sets(owner):
    values = owner.values
    values["load_programme_host_roster"] = replace(
        values["load_programme_host_roster"], entries=()
    )
    values["load_programme_host_dependencies"] = replace(
        values["load_programme_host_dependencies"], hosts=()
    )
    values["load_programme_staffing_requirements"] = replace(
        values["load_programme_staffing_requirements"], requirements=()
    )
    result = item.load_programme_exit_item(**owner.args)
    assert result.host_histories == result.staffing_histories == ()
    owner.readers["load_programme_host_history"].assert_not_called()
    owner.readers["load_programme_staffing_history"].assert_not_called()


@pytest.mark.parametrize(
    "bound", ["MAX_HOSTS_PER_ITEM", "MAX_STAFFING_REQUIREMENTS_PER_ITEM"]
)
def test_inventory_overflow_refuses_instead_of_omitting_records(
    owner, monkeypatch, bound
):
    monkeypatch.setattr(item, bound, 0)
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        item.load_programme_exit_item(**owner.args)
    owner.audit.assert_not_called()


@pytest.mark.parametrize("version", [0, True, 1002])
def test_staffing_invalid_ceiling_refuses_before_reading(owner, version):
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        item._staffing_history(
            Mock(), replace(owner.requirement, version=version), authorizer=Mock()
        )
    owner.readers["load_programme_staffing_history"].assert_not_called()
