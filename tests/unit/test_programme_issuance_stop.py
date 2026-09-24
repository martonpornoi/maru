"""Fresh generic authority issuance cannot bypass a terminal Programme context."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from maru.authorization import services
from maru.events.programme_stop_queries import ProgrammeStopReference


def target(**changes):
    return SimpleNamespace(
        **{
            "edition_id": uuid4(),
            "organization_id": uuid4(),
            "adoption_profile_code": "programme_operations",
            **changes,
        }
    )


@pytest.mark.parametrize(
    "reference",
    [
        None,
        ProgrammeStopReference(applies=True, is_stopped=True, version=2),
        ProgrammeStopReference(applies=False, is_stopped=False, version=2),
    ],
)
def test_stopped_missing_or_moved_profile_refuses_fresh_issuance(
    monkeypatch, reference
):
    monkeypatch.setattr(
        services, "resolve_programme_stop_reference", lambda **_: reference
    )
    with pytest.raises(services.AuthorizationDenied) as failure:
        services._require_programme_issuance_open(target())
    assert failure.value.reason_code == "programme_authority_unavailable"


def test_open_exact_scope_is_freshly_observed(monkeypatch):
    resolver = MagicMock(
        return_value=ProgrammeStopReference(applies=True, is_stopped=False, version=2)
    )
    monkeypatch.setattr(services, "resolve_programme_stop_reference", resolver)
    scope = target()
    services._require_programme_issuance_open(scope)
    resolver.assert_called_once_with(
        organization_id=scope.organization_id, edition_id=scope.edition_id
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"edition_id": None},
        {"adoption_profile_code": "full_convention"},
        {"adoption_profile_code": "workforce_only"},
    ],
)
def test_shared_organization_and_existing_profiles_do_not_inherit_stop_rules(
    monkeypatch, changes
):
    resolver = MagicMock()
    monkeypatch.setattr(services, "resolve_programme_stop_reference", resolver)
    services._require_programme_issuance_open(target(**changes))
    resolver.assert_not_called()
