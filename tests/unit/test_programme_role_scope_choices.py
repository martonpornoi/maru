"""Database-free complete-scope discovery and disclosure-boundary regressions."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError

from maru.authorization import programme_role_scope_choices as query
from maru.authorization.catalog import ScopeLevel
from maru.authorization.policy import AuthorizedScopeProjection
from maru.authorization.programme_role_inputs import ProgrammeRoleScope
from maru.authorization.services import AuthorizationDenied
from maru.identity.models import Account
from maru.workforce.queries import CurrentDepartmentSetReference

ORG, EDITION, ACTOR, DEPARTMENT, ROOM = (UUID(int=i) for i in range(1, 6))
CONTEXT = ProgrammeRoleScope(ORG, EDITION, ScopeLevel.EDITION)
PERSON = Account(
    id=ACTOR, is_active=True, email_verified_at=datetime(2026, 9, 18, tzinfo=UTC)
)
PROJECTION = AuthorizedScopeProjection(
    ORG,
    EDITION,
    None,
    None,
    frozenset({"authorization.manage_roles"}),
    frozenset({"authorization.manage_roles"}),
    (),
    (),
)


def denied():
    return AuthorizationDenied("Unavailable", reason_code="test")


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(query.transaction, "atomic", nullcontext)
    mocks = {}
    for name, result in {
        "_require_profile": None,
        "_require_integrity": None,
        "_lock_scope": object(),
        "_lock_people": {ACTOR: PERSON},
        "lock_retired_department_authority_boundaries": None,
        "_require_current_controller": None,
        "append_audit": None,
        "project_active_authority_scopes": (PROJECTION,),
        "resolve_current_department_set_reference": CurrentDepartmentSetReference(
            ORG, EDITION, (DEPARTMENT,)
        ),
    }.items():
        mocks[name] = Mock(return_value=result)
        monkeypatch.setattr(query, name, mocks[name])
    mocks["_resolve_scope"] = Mock(side_effect=lambda scope: scope)
    mocks["page_access_scope_label"] = Mock(
        side_effect=lambda scope: (
            f"Synthetic {scope.level.value} {scope.department_id or ''}"
        )
    )
    for name in ("_resolve_scope", "page_access_scope_label"):
        monkeypatch.setattr(query, name, mocks[name])
    manager = Mock()
    selected = Mock()
    selected.__getitem__ = Mock(return_value=[(DEPARTMENT, ROOM)])
    manager.filter.return_value.order_by.return_value.values_list.return_value = (
        selected
    )
    monkeypatch.setattr(query.ScopedResourceBinding, "objects", manager)
    return SimpleNamespace(mocks=mocks, rooms=selected, manager=manager)


def read(**changes):
    return query.load_programme_role_scope_choices(
        **{
            "actor": PERSON,
            "organization_id": ORG,
            "edition_id": EDITION,
            "correlation_id": uuid4(),
            **changes,
        }
    )


def test_current_profile_denies_before_database():
    with pytest.raises(AuthorizationDenied):
        read()
    assert not query.can_enter_programme_role_scopes(
        actor=PERSON, organization_id=ORG, edition_id=EDITION
    )


def test_complete_exact_inventory_is_bounded_scoped_and_audited(world):
    result = read()
    assert [value.scope.level for value in result.choices] == [
        ScopeLevel.ORGANIZATION,
        ScopeLevel.EDITION,
        ScopeLevel.DEPARTMENT,
        ScopeLevel.RESOURCE,
    ]
    assert all(value.label for value in result.choices)
    assert result.choices[-1].scope.resource_kind == "venue.edition_space"
    assert result.choices[-1].purpose == "Selected room access"
    world.manager.filter.assert_called_with(
        organization_id=ORG,
        edition_id=EDITION,
        department_id__in=(DEPARTMENT,),
        resource_kind="venue.edition_space",
    )
    world.rooms.__getitem__.assert_called_with(slice(None, 257))
    audit = world.mocks["append_audit"].call_args.args[0]
    assert audit.operation == "authorization.programme_role.scopes.read"
    assert audit.safe_metadata == {"target_count": 4}
    assert audit.retention_class == "security-extended"
    assert audit.principal_id == ACTOR
    assert audit.organization_id == ORG
    assert audit.event_edition_id == EDITION


@pytest.mark.parametrize(
    "level",
    [
        ScopeLevel.ORGANIZATION,
        ScopeLevel.EDITION,
        ScopeLevel.DEPARTMENT,
        ScopeLevel.RESOURCE,
    ],
)
def test_narrow_controller_never_reads_denied_scope_labels(world, level):

    def admit(actor, target):
        if target.level != level:
            raise denied()

    world.mocks["_require_current_controller"].side_effect = admit
    result = read()
    assert [value.scope.level for value in result.choices] == [level]
    assert all(
        call.args[0].level in {level, ScopeLevel.EDITION}
        for call in world.mocks["page_access_scope_label"].call_args_list
    )


def test_no_scope_is_neutral_denial_without_labels_or_success_audit(world):
    world.mocks["_require_current_controller"].side_effect = denied()
    with pytest.raises(AuthorizationDenied):
        read()
    world.mocks["page_access_scope_label"].assert_not_called()
    world.mocks["append_audit"].assert_not_called()


@pytest.mark.parametrize(
    "reference",
    [
        None,
        object(),
        CurrentDepartmentSetReference(uuid4(), EDITION, ()),
        CurrentDepartmentSetReference(ORG, uuid4(), ()),
        CurrentDepartmentSetReference(ORG, EDITION, [DEPARTMENT]),
        CurrentDepartmentSetReference(ORG, EDITION, (DEPARTMENT, DEPARTMENT)),
        CurrentDepartmentSetReference(ORG, EDITION, (UUID(int=0),)),
        CurrentDepartmentSetReference(ORG, EDITION, ("department",)),
        CurrentDepartmentSetReference(
            ORG, EDITION, tuple(UUID(int=100 + i) for i in range(257))
        ),
    ],
)
def test_incomplete_or_wrong_owner_department_reference_never_reads_labels(
    world, reference
):
    world.mocks["resolve_current_department_set_reference"].return_value = reference
    with pytest.raises(ValidationError) as error:
        read()
    assert error.value.code == "programme_role_scope_inventory_unavailable"
    world.manager.filter.assert_not_called()
    world.mocks["page_access_scope_label"].assert_not_called()


@pytest.mark.parametrize(
    "rooms",
    [
        [(uuid4(), ROOM)],
        [(DEPARTMENT, UUID(int=0))],
        [(DEPARTMENT, "room")],
        [(DEPARTMENT, ROOM), (DEPARTMENT, ROOM)],
        [(DEPARTMENT, UUID(int=100 + i)) for i in range(257)],
    ],
)
def test_overflow_or_malformed_room_inventory_never_returns_partial_list(world, rooms):
    world.rooms.__getitem__.return_value = rooms
    with pytest.raises(ValidationError):
        read()
    world.mocks["page_access_scope_label"].assert_not_called()
    world.mocks["append_audit"].assert_not_called()


def test_empty_narrow_inventory_retains_authorized_broad_scopes(world):
    world.mocks[
        "resolve_current_department_set_reference"
    ].return_value = CurrentDepartmentSetReference(ORG, EDITION, ())
    world.rooms.__getitem__.return_value = []
    assert len(read().choices) == 2


def test_exact_bounds_remain_complete_and_department_order_is_stable(world):
    ids = tuple(UUID(int=100 + i) for i in range(256))
    world.mocks[
        "resolve_current_department_set_reference"
    ].return_value = CurrentDepartmentSetReference(ORG, EDITION, tuple(reversed(ids)))
    world.rooms.__getitem__.return_value = [
        (ids[i], UUID(int=1000 + i)) for i in range(256)
    ]
    result = read()
    assert len(result.choices) == 514
    assert tuple(value.scope.department_id for value in result.choices[2:258]) == ids


@pytest.mark.parametrize(
    "changes",
    [
        {"actor": object()},
        {"actor": Account(id=UUID(int=0))},
        {"actor": Account(id=ACTOR, is_active=False)},
        {"actor": Account(id=ACTOR, is_active=True, email_verified_at=None)},
        {
            "actor": Account(
                id=ACTOR,
                is_active=True,
                email_verified_at=PERSON.email_verified_at,
                account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
            )
        },
        {"organization_id": UUID(int=0)},
        {"edition_id": "edition"},
    ],
)
def test_bad_actor_or_scope_denies_before_owner_locks(world, changes):
    with pytest.raises(AuthorizationDenied):
        read(**changes)
    world.mocks["_lock_scope"].assert_not_called()
    world.manager.filter.assert_not_called()


@pytest.mark.parametrize(
    "changes", [{"correlation_id": UUID(int=0)}, {"source_channel": "unsafe channel"}]
)
def test_invalid_audit_context_cannot_release_names(world, changes):
    with pytest.raises(ValidationError):
        read(**changes)
    world.mocks["_lock_scope"].assert_not_called()


@pytest.mark.parametrize(
    "failure", ["_require_integrity", "_lock_scope", "_lock_people"]
)
def test_foundation_person_or_integrity_failure_precedes_names(world, failure):
    world.mocks[failure].side_effect = denied()
    with pytest.raises(AuthorizationDenied):
        read()
    world.mocks["page_access_scope_label"].assert_not_called()


def test_changed_source_or_final_revocation_cannot_return_old_catalog(world):
    world.mocks["_require_current_controller"].side_effect = [None] * 4 + [denied()] * 4
    with pytest.raises(AuthorizationDenied):
        read()
    world.mocks["append_audit"].assert_not_called()


def test_changed_labels_are_not_returned(world):
    world.mocks["page_access_scope_label"].side_effect = [str(i) for i in range(10)]
    with pytest.raises(ValidationError) as error:
        read()
    assert error.value.code == "programme_role_scope_source_changed"
    world.mocks["append_audit"].assert_not_called()


def test_failed_audit_never_returns_catalog(world):
    world.mocks["append_audit"].side_effect = DatabaseError("failed")
    with pytest.raises(DatabaseError):
        read()


def test_metadata_only_entry_reads_no_names_and_adds_no_activity_audit(world):
    assert query.can_enter_programme_role_scopes(
        actor=PERSON, organization_id=ORG, edition_id=EDITION
    )
    world.mocks["page_access_scope_label"].assert_not_called()
    world.mocks["append_audit"].assert_not_called()
    assert world.mocks["_require_current_controller"].call_count == 8


@pytest.mark.parametrize(
    "error", [denied(), ValidationError("failed"), DatabaseError("failed")]
)
def test_optional_entry_fails_closed(world, error):
    world.mocks["_require_integrity"].side_effect = error
    assert not query.can_enter_programme_role_scopes(
        actor=PERSON, organization_id=ORG, edition_id=EDITION
    )


@pytest.mark.parametrize(
    "projections",
    [
        (),
        (replace(PROJECTION, organization_id=uuid4()),),
        (replace(PROJECTION, edition_id=uuid4()),),
        (
            replace(
                PROJECTION, capability_codes=frozenset({"workforce.view_structure"})
            ),
        ),
    ],
)
def test_unrelated_authority_cannot_probe_owner_existence_or_overflow(
    world, projections
):
    world.mocks["project_active_authority_scopes"].return_value = projections
    world.mocks[
        "resolve_current_department_set_reference"
    ].side_effect = AssertionError("Forbidden inventory probe")
    world.mocks["_require_integrity"].side_effect = AssertionError(
        "Forbidden readiness probe"
    )
    with pytest.raises(AuthorizationDenied):
        read()
    world.mocks["_lock_scope"].assert_not_called()
    world.manager.filter.assert_not_called()


@pytest.mark.parametrize(
    "projection",
    [
        replace(PROJECTION, edition_id=None),
        replace(PROJECTION, department_id=DEPARTMENT),
        replace(PROJECTION, department_id=DEPARTMENT, resource_binding_id=ROOM),
    ],
)
def test_name_free_preflight_does_not_require_broad_edition_authority(
    world, projection
):
    world.mocks["project_active_authority_scopes"].return_value = (projection,)
    assert read().choices
    assert world.mocks["_require_current_controller"].call_count == 8
