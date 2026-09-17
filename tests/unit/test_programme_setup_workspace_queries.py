"""Database-free setup projection boundaries, not native transaction acceptance."""

from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError

from maru.events import programme_setup_queries as query
from maru.events.programme_setup_inputs import ProgrammeSetupMode as Mode
from maru.events.queries import EditionRouteIdentity
from maru.identity.models import Account
from maru.organizations import programme_setup_references as owner


def foundation():
    return owner.ProgrammeSetupFoundationReference(
        UUID(int=2),
        "Synthetic organizers",
        "draft",
        ("en",),
        "UTC",
        UUID(int=7),
        "maru_operators",
        1,
        "provisioning",
        UUID(int=3),
        "Synthetic convention",
        1,
        "a" * 64,
    )


@pytest.fixture
def world(monkeypatch):
    actor = Account(
        id=UUID(int=1), account_kind=Account.Kind.PLATFORM_ADMINISTRATOR, is_active=True
    )
    reference = foundation()
    choices = (
        owner.ProgrammeFoundationChoice(
            UUID(int=2), "Synthetic organizers", "synthetic"
        ),
    )
    mocks = {}
    for name, value in {
        "adoption_profile": SimpleNamespace(key=("programme_operations", 1)),
        "current_platform_administrator_is_available": True,
        "programme_setup_organization_choices": choices,
        "programme_setup_series_choices": (),
        "resolve_programme_setup_foundation": reference,
        "resolve_edition_route_identity": EditionRouteIdentity(
            "synthetic", "con", "2030"
        ),
        "resolve_current_department_label_reference": SimpleNamespace(
            label="Programme"
        ),
        "append_audit": None,
    }.items():
        mocks[name] = Mock(return_value=value)
        monkeypatch.setattr(query, name, mocks[name])
    receipts = MagicMock()
    receipts.filter.return_value.first.return_value = SimpleNamespace(
        id=UUID(int=6),
        department_id=UUID(int=5),
        representation_id=UUID(int=7),
        mode=Mode.NEW_FOUNDATION,
    )
    monkeypatch.setattr(query.ProgrammeAdoptionSetupReceipt, "objects", receipts)
    editions = MagicMock()
    editions.filter.return_value.first.return_value = SimpleNamespace(
        id=UUID(int=4),
        name="Synthetic 2030",
        starts_on=date(2030, 9, 1),
        ends_on=date(2030, 9, 3),
        time_zone="UTC",
    )
    monkeypatch.setattr(query.EventEdition, "objects", editions)
    return SimpleNamespace(
        actor=actor,
        reference=reference,
        choices=choices,
        mocks=mocks,
        receipts=receipts,
        editions=editions,
    )


def load(world, **kwargs):
    return query.load_programme_setup_choices(
        actor=world.actor, correlation_id=UUID(int=9), **kwargs
    )


def receipt(world, **kwargs):
    values = {
        "actor": world.actor,
        "correlation_id": UUID(int=9),
        "organization_id": UUID(int=2),
        "series_id": UUID(int=3),
        "edition_id": UUID(int=4),
        "receipt_id": UUID(int=6),
    }
    return query.load_programme_setup_receipt(**{**values, **kwargs})


def test_index_is_complete_bounded_and_audited_without_selected_source(world):
    assert load(world) == query.ProgrammeSetupChoices(organizations=world.choices)
    world.mocks["resolve_programme_setup_foundation"].assert_not_called()
    world.mocks["programme_setup_series_choices"].assert_not_called()
    audit = world.mocks["append_audit"].call_args.args[0]
    assert audit.principal_id == world.actor.id
    assert audit.organization_id is None
    assert audit.target_id is None
    assert audit.obligations == ("audit_sensitive_read",)


def test_new_mode_reads_no_existing_foundation_inventory(world):
    assert load(world, mode=Mode.NEW_FOUNDATION) == query.ProgrammeSetupChoices()
    world.mocks["programme_setup_organization_choices"].assert_not_called()
    world.mocks["resolve_programme_setup_foundation"].assert_not_called()


@pytest.mark.parametrize("mode", [Mode.EXISTING_ORGANIZATION, Mode.EXISTING_SERIES])
def test_selected_scope_never_reads_a_cross_tenant_directory(world, mode):
    selected_series = UUID(int=3) if mode == Mode.EXISTING_SERIES else None
    result = load(
        world, mode=mode, organization_id=UUID(int=2), series_id=selected_series
    )
    assert result.foundation is world.reference
    world.mocks["resolve_programme_setup_foundation"].assert_called_once_with(
        organization_id=UUID(int=2), series_id=selected_series
    )
    world.mocks["programme_setup_organization_choices"].assert_not_called()
    if selected_series:
        world.mocks["programme_setup_series_choices"].assert_not_called()
    else:
        world.mocks["programme_setup_series_choices"].assert_called_once_with(
            organization_id=UUID(int=2)
        )


@pytest.mark.parametrize(
    "fault", ["profile", "version", "inactive", "person", "current"]
)
def test_admission_denies_before_owner_queries(world, fault):
    if fault == "profile":
        world.mocks["adoption_profile"].return_value = None
    elif fault == "version":
        world.mocks["adoption_profile"].return_value = SimpleNamespace(
            key=("programme_operations", 2)
        )
    elif fault == "inactive":
        world.actor.is_active = False
    elif fault == "person":
        world.actor.account_kind = Account.Kind.PERSON
    else:
        world.mocks["current_platform_administrator_is_available"].return_value = False
    with pytest.raises(PermissionDenied):
        load(world)
    world.mocks["programme_setup_organization_choices"].assert_not_called()
    world.mocks["append_audit"].assert_not_called()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"organization_id": UUID(int=2)},
        {"mode": Mode.NEW_FOUNDATION, "series_id": UUID(int=3)},
        {"mode": "invalid"},
        {"mode": Mode.EXISTING_ORGANIZATION},
        {"mode": Mode.EXISTING_ORGANIZATION, "organization_id": UUID(int=0)},
        {
            "mode": Mode.EXISTING_ORGANIZATION,
            "organization_id": UUID(int=2),
            "series_id": UUID(int=3),
        },
        {"mode": Mode.EXISTING_SERIES, "organization_id": UUID(int=2)},
    ],
)
def test_invalid_stage_cannot_guess_or_resolve_scope(world, kwargs):
    with pytest.raises(PermissionDenied):
        load(world, **kwargs)
    world.mocks["resolve_programme_setup_foundation"].assert_not_called()


@pytest.mark.parametrize("selected", [False, True])
def test_overflow_releases_no_partial_projection_or_success_audit(world, selected):
    name = (
        "programme_setup_series_choices"
        if selected
        else "programme_setup_organization_choices"
    )
    world.mocks[name].return_value = None
    kwargs = (
        {"mode": Mode.EXISTING_ORGANIZATION, "organization_id": UUID(int=2)}
        if selected
        else {}
    )
    with pytest.raises(ValidationError, match="no partial"):
        load(world, **kwargs)
    world.mocks["append_audit"].assert_not_called()


def test_unavailable_selected_foundation_cannot_disclose_series(world):
    world.mocks["resolve_programme_setup_foundation"].return_value = None
    with pytest.raises(PermissionDenied):
        load(world, mode=Mode.EXISTING_ORGANIZATION, organization_id=UUID(int=2))
    world.mocks["programme_setup_series_choices"].assert_not_called()


def test_revocation_before_disclosure_suppresses_projection(world):
    world.mocks["current_platform_administrator_is_available"].side_effect = [
        True,
        False,
    ]
    with pytest.raises(PermissionDenied):
        load(world)
    world.mocks["append_audit"].assert_not_called()


def test_audit_failure_cannot_release_projection(world):
    world.mocks["append_audit"].side_effect = DatabaseError("private dependency")
    with pytest.raises(DatabaseError):
        load(world)


def test_receipt_pins_actual_original_actor_and_complete_scope(world):
    result = receipt(world)
    world.receipts.filter.assert_called_once_with(
        id=UUID(int=6),
        actor_id=world.actor.id,
        organization_id=UUID(int=2),
        series_id=UUID(int=3),
        edition_id=UUID(int=4),
    )
    assert result.department_name == "Programme"
    assert result.foundation.representation_state == "provisioning"
    assert not hasattr(result, "idempotency_key")
    assert not hasattr(result, "operational_access")
    assert world.mocks["append_audit"].call_args.args[0].target_id == UUID(int=6)


def test_foreign_or_missing_receipt_has_no_owner_label_lookup(world):
    world.receipts.filter.return_value.first.return_value = None
    with pytest.raises(PermissionDenied):
        receipt(world)
    world.editions.filter.assert_not_called()
    world.mocks["resolve_programme_setup_foundation"].assert_not_called()


def test_receipt_cannot_invent_creation_facts_for_unknown_original_mode(world):
    world.receipts.filter.return_value.first.return_value.mode = "unknown"
    with pytest.raises(ValidationError):
        receipt(world)
    world.editions.filter.assert_not_called()


@pytest.mark.parametrize("fault", ["foundation", "route", "edition", "representation"])
def test_incoherent_receipt_owner_sources_release_nothing(world, fault):
    if fault == "edition":
        world.editions.filter.return_value.first.return_value = None
    elif fault == "representation":
        world.mocks["resolve_programme_setup_foundation"].return_value = replace(
            world.reference, representation_id=UUID(int=88)
        )
    else:
        world.mocks[
            {
                "foundation": "resolve_programme_setup_foundation",
                "route": "resolve_edition_route_identity",
            }[fault]
        ].return_value = None
    with pytest.raises(ValidationError):
        receipt(world)
    world.mocks["append_audit"].assert_not_called()


def test_retired_department_is_not_replaced_with_another_one(world):
    world.mocks["resolve_current_department_label_reference"].return_value = None
    assert receipt(world).department_name == "Original Department currently unavailable"


@pytest.mark.parametrize("series", [False, True])
@pytest.mark.parametrize("count", [0, 100, 101])
def test_owner_choices_are_complete_or_unavailable_with_fixed_ceiling(
    monkeypatch, series, count
):
    manager = MagicMock()
    projection = (
        manager.filter.return_value.order_by.return_value.values_list.return_value
    )
    projection.__getitem__.return_value = [
        (UUID(int=i + 1), "Synthetic", f"synthetic-{i}") for i in range(count)
    ]
    monkeypatch.setattr(
        owner.ConventionSeries if series else owner.Organization, "objects", manager
    )
    result = (
        owner.programme_setup_series_choices(organization_id=UUID(int=2))
        if series
        else owner.programme_setup_organization_choices()
    )
    projection.__getitem__.assert_called_once_with(slice(None, 101))
    if count > 100:
        assert result is None
    else:
        assert len(result) == count
    if series:
        manager.filter.assert_called_once_with(
            organization_id=UUID(int=2), is_active=True
        )
    else:
        condition = str(manager.filter.call_args.args[0])
        assert "representation__code" in condition
        assert "representation__name" in condition
        assert "provisioning" in condition
        assert "active" in condition


def test_current_profiles_deny_real_loader_before_database():
    actor = Account(account_kind=Account.Kind.PLATFORM_ADMINISTRATOR, is_active=True)
    with pytest.raises(PermissionDenied):
        query.load_programme_setup_choices(actor=actor, correlation_id=UUID(int=9))
