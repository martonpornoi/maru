"""Rendered home guidance remains scoped, actionable and honest on failure."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.test import RequestFactory

from maru.core import home_guidance
from maru.events.adoption import adoption_profile
from maru.identity.models import Account
from maru.workforce.home_guidance import WorkforceSetupGuidance
from maru.workforce.operating_home import WorkforceHomeGuidance
from maru.workforce.structure_snapshot import StructureSnapshotChangedError

NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)


def _setup(*args, **kwargs):
    return WorkforceHomeGuidance(WorkforceSetupGuidance(*args, **kwargs))


def _request():
    request = RequestFactory().get("/admin/")
    request.user = Account(
        id=UUID(int=7), email="synthetic@example.invalid", is_active=True
    )
    request.correlation_id = str(UUID(int=8))
    return request


def _edition():
    return SimpleNamespace(
        id=UUID(int=1),
        organization_id=UUID(int=2),
        time_zone="Europe/Budapest",
        slug="edition",
        organization=SimpleNamespace(slug="organizer"),
        series=SimpleNamespace(slug="series"),
    )


@pytest.mark.parametrize("zone", ["Europe/Budapest", "Pacific/Auckland"])
def test_setup_check_time_uses_the_already_admitted_edition_zone(monkeypatch, zone):
    edition = _edition()
    edition.time_zone = zone
    monkeypatch.setattr(
        home_guidance,
        "load_workforce_home_guidance",
        lambda **_kwargs: _setup("published", NOW),
    )
    result = home_guidance.project_home_guidance(
        _request(), edition, adoption_profile("workforce_only", 1)
    )
    assert result.time_zone == zone


def test_invalid_setup_display_zone_stays_unavailable_without_a_target(monkeypatch):
    edition = _edition()
    edition.time_zone = "invalid-zone"
    monkeypatch.setattr(
        home_guidance,
        "load_workforce_home_guidance",
        lambda **_kwargs: _setup("published", NOW),
    )
    result = home_guidance.project_home_guidance(
        _request(), edition, adoption_profile("workforce_only", 1)
    )
    assert result.state == "Unavailable"
    assert result.action_url == ""


@pytest.mark.parametrize(
    ("step", "state", "label", "suffix"),
    [
        ("departments", "Ready", "Open team structure", "/structure/"),
        ("positions", "Ready", "Open Positions", "/structure/positions/"),
        (
            "opportunities",
            "Ready",
            "Review this Position",
            f"/structure/positions/{UUID(int=9)}/",
        ),
        ("published", "Published", "Review Positions", "/structure/positions/"),
        ("review", "Review", "Review Positions", "/structure/positions/"),
        ("read_only", "Read only", "Review team structure", "/structure/"),
    ],
)
def test_guidance_links_to_exact_existing_owner_route(
    monkeypatch, step, state, label, suffix
):
    owner = Mock(
        return_value=_setup(step, NOW, can_manage=True, position_id=UUID(int=9))
    )
    monkeypatch.setattr(home_guidance, "load_workforce_home_guidance", owner)
    item = home_guidance.project_home_guidance(
        _request(), _edition(), adoption_profile("workforce_only", 1)
    )
    assert item.state == state
    assert item.action_label == label
    assert item.action_url.startswith(
        "/admin/platform/organizations/organizer/series/series/editions/edition/"
    )
    assert item.action_url.endswith(suffix)
    assert item.checked_at == NOW
    assert "ready for the convention" not in item.explanation.lower()
    assert owner.call_args.kwargs["organization_id"] == UUID(int=2)


@pytest.mark.parametrize("step", ["departments", "positions", "opportunities"])
def test_viewer_gets_waiting_and_read_only_continuation(monkeypatch, step):
    monkeypatch.setattr(
        home_guidance,
        "load_workforce_home_guidance",
        lambda **_kw: _setup(step, NOW, position_id=UUID(int=9)),
    )
    item = home_guidance.project_home_guidance(
        _request(), _edition(), adoption_profile("workforce_only", 1)
    )
    assert item.state == "Waiting"
    assert item.action_label == "Review team structure"
    assert item.action_url.endswith("/structure/")
    assert str(UUID(int=9)) not in item.action_url


@pytest.mark.parametrize(
    "code", ["full_convention", "announcements_only", "guidance_only"]
)
def test_unadopted_provider_is_not_invoked(monkeypatch, code):
    owner = Mock(side_effect=AssertionError("Unadopted owner queried"))
    monkeypatch.setattr(home_guidance, "load_workforce_home_guidance", owner)
    assert (
        home_guidance.project_home_guidance(
            _request(), _edition(), adoption_profile(code, 1)
        )
        is None
    )
    owner.assert_not_called()


@pytest.mark.parametrize("missing", ["edition", "profile", "active"])
def test_missing_context_or_inactive_account_does_not_query_owner(monkeypatch, missing):
    owner = Mock()
    monkeypatch.setattr(home_guidance, "load_workforce_home_guidance", owner)
    request = _request()
    request.user.is_active = missing != "active"
    item = home_guidance.project_home_guidance(
        request,
        None if missing == "edition" else _edition(),
        None if missing == "profile" else adoption_profile("workforce_only", 1),
    )
    assert item is None
    owner.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        DatabaseError("private detail"),
        StructureSnapshotChangedError("private detail"),
        RuntimeError("private audit detail"),
    ],
)
def test_dependency_failure_exposes_only_generic_unavailable_guidance(
    monkeypatch, error
):
    monkeypatch.setattr(
        home_guidance, "load_workforce_home_guidance", Mock(side_effect=error)
    )
    item = home_guidance.project_home_guidance(
        _request(), _edition(), adoption_profile("workforce_only", 1)
    )
    assert item.state == "Unavailable"
    assert not item.action_url
    assert item.checked_at is None
    assert "private" not in item.explanation


def test_denial_is_omitted_and_not_misreported_as_ready(monkeypatch):
    monkeypatch.setattr(
        home_guidance,
        "load_workforce_home_guidance",
        Mock(side_effect=PermissionDenied),
    )
    assert (
        home_guidance.project_home_guidance(
            _request(), _edition(), adoption_profile("workforce_only", 1)
        )
        is None
    )


@pytest.mark.parametrize(
    ("step", "state"), [("published", "Published"), ("review", "Review")]
)
def test_viewer_keeps_owner_state_and_uses_the_read_only_destination(
    monkeypatch, step, state
):
    monkeypatch.setattr(
        home_guidance,
        "load_workforce_home_guidance",
        lambda **_kw: _setup(step, NOW, position_id=UUID(int=9)),
    )
    item = home_guidance.project_home_guidance(
        _request(), _edition(), adoption_profile("workforce_only", 1)
    )
    assert item.state == state
    assert item.action_label == "Review team structure"
    assert item.action_url.endswith("/structure/")
    assert str(UUID(int=9)) not in item.action_url
