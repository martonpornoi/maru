"""Actual boundary decisions with substituted read dependencies, never native proof."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError

from maru.authorization.provenance import ControlHorizonMode
from maru.authorization.services import AuthorizationDenied
from maru.identity.models import Account
from maru.workforce import programme_starter_boundary as boundary
from maru.workforce.programme_starter_inputs import ProgrammeStarterScope

SCOPE = ProgrammeStarterScope(UUID(int=1), UUID(int=2), UUID(int=3))


@pytest.mark.parametrize("fault", ["profile", "definition", "catalog", "capability"])
def test_exact_profile_and_fixed_meaning_required(monkeypatch, fault):
    monkeypatch.setattr(
        boundary,
        "adoption_profile",
        lambda *_: None if fault == "profile" else object(),
    )
    monkeypatch.setattr(
        boundary, "profile_allows_catalog_entry", lambda *_: fault != "catalog"
    )
    monkeypatch.setattr(
        boundary, "profile_allows_capabilities", lambda *_: fault != "capability"
    )
    if fault == "definition":
        monkeypatch.setattr(
            boundary,
            "PROGRAMME_STARTER_DEFINITION",
            replace(boundary.PROGRAMME_STARTER_DEFINITION, default_headcount=2),
        )
    with pytest.raises(AuthorizationDenied):
        boundary._require_profile()


@pytest.mark.parametrize(
    "fault", [None, "organization", "edition", "profile", "version", "series"]
)
def test_exact_owner_chain_and_profile_are_resolved(monkeypatch, fault):
    organization = object()
    edition = SimpleNamespace(
        adoption_profile_code="full_convention"
        if fault == "profile"
        else "programme_operations",
        adoption_profile_version=2 if fault == "version" else 1,
    )
    org = MagicMock(return_value=None if fault == "organization" else organization)
    ed = MagicMock(return_value=None if fault == "edition" else edition)
    series = MagicMock(
        return_value=UUID(int=99) if fault == "series" else SCOPE.series_id
    )
    monkeypatch.setattr(boundary, "resolve_organization_target", org)
    monkeypatch.setattr(boundary, "resolve_edition_target", ed)
    monkeypatch.setattr(boundary, "resolve_edition_series_identity", series)
    if fault is not None:
        with pytest.raises(AuthorizationDenied):
            boundary._resolve_scope(SCOPE)
    else:
        assert boundary._resolve_scope(SCOPE) == (organization, edition)
        org.assert_called_once_with(organization_id=SCOPE.organization_id)
        ed.assert_called_once_with(
            organization_id=SCOPE.organization_id, edition_id=SCOPE.edition_id
        )
        series.assert_called_once_with(
            organization_id=SCOPE.organization_id, edition_id=SCOPE.edition_id
        )


@pytest.mark.parametrize(
    "fault",
    [None, "inactive", "unverified", "platform", "organization", "edition", "source"],
)
def test_ordinary_person_needs_both_capabilities_and_real_control_source(
    monkeypatch, fault
):
    actor = Account(
        id=UUID(int=4),
        is_active=fault != "inactive",
        account_kind="platform_administrator" if fault == "platform" else "person",
        email_verified_at=None
        if fault == "unverified"
        else datetime(2030, 1, 1, tzinfo=UTC),
    )
    targets = (object(), object())
    policy = MagicMock(
        side_effect=lambda **kw: SimpleNamespace(
            allowed=kw["resource"]
            is not (
                targets[0]
                if fault == "organization"
                else targets[1]
                if fault == "edition"
                else None
            )
        )
    )
    source = MagicMock(return_value=None if fault == "source" else object())
    monkeypatch.setattr(boundary, "decide", policy)
    monkeypatch.setattr(boundary, "select_authorized_control_source", source)
    if fault is not None:
        with pytest.raises(AuthorizationDenied):
            boundary._require_controller(actor, targets)
    else:
        boundary._require_controller(actor, targets)
        assert source.call_args.kwargs["target"] is targets[0]
        assert (
            source.call_args.kwargs["horizon_mode"] is ControlHorizonMode.POINT_IN_TIME
        )
        assert [call.kwargs["capability_code"] for call in policy.call_args_list] == [
            "authorization.manage_roles",
            "workforce.manage_structure",
        ]


@pytest.mark.parametrize(
    "fault", [None, "missing", "stale", "inactive", "representation"]
)
def test_scope_locks_foundation_before_workforce_and_re_resolves(monkeypatch, fault):
    foundation = SimpleNamespace(
        fingerprint="a" * 64,
        organization_lifecycle="suspended" if fault == "inactive" else "active",
        representation_state="provisioning" if fault == "representation" else "active",
    )
    order = []
    monkeypatch.setattr(
        boundary,
        "resolve_programme_setup_foundation",
        lambda **_: None if fault == "missing" else foundation,
    )
    lock = MagicMock(
        side_effect=lambda **_: (
            order.append("foundation"),
            None if fault == "stale" else foundation,
        )[1]
    )
    monkeypatch.setattr(boundary, "lock_programme_setup_foundation", lock)
    monkeypatch.setattr(
        boundary,
        "lock_workforce_edition_write_scope",
        lambda **_: order.append("workforce"),
    )
    monkeypatch.setattr(boundary, "_resolve_scope", lambda _: order.append("resolve"))
    if fault is not None:
        with pytest.raises(AuthorizationDenied):
            boundary._lock_scope(SCOPE)
        assert "workforce" not in order
    else:
        assert boundary._lock_scope(SCOPE) is foundation
        assert order == ["foundation", "workforce", "resolve"]
        lock.assert_called_once_with(
            organization_id=SCOPE.organization_id,
            series_id=SCOPE.series_id,
            expected_fingerprint="a" * 64,
        )


@pytest.mark.parametrize("available", [False, None])
def test_creation_requires_planning_phase(monkeypatch, available):
    monkeypatch.setattr(
        boundary,
        "resolve_private_planning_edition_reference",
        lambda **_: (
            None
            if available is None
            else SimpleNamespace(accepts_private_planning_writes=available)
        ),
    )
    with pytest.raises(ValidationError, match="planning phase"):
        boundary._require_planning(SCOPE)


def test_integrity_is_real_owner_readiness_not_profile_admission(monkeypatch):
    monkeypatch.setattr(
        boundary, "programme_starter_database_integrity_is_ready", lambda: False
    )
    with pytest.raises(ValidationError, match="integrity"):
        boundary._require_integrity()
