"""Setup links use the same independent owning admission as their destination."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError

from maru.core import views


@pytest.fixture
def setup(monkeypatch):
    actor = SimpleNamespace(is_platform_administrator=True)
    edition = SimpleNamespace(
        adoption_profile_code="announcements_only",
        adoption_profile_version=1,
        organization_id=UUID(int=1),
        id=UUID(int=2),
    )
    query = Mock(return_value=SimpleNamespace(guidance_ready=False))
    monkeypatch.setattr(views, "load_guidance_activation_start", query)
    return actor, edition, query


def test_nonplatform_or_unsupported_event_does_not_probe_setup(setup):
    actor, edition, query = setup
    actor.is_platform_administrator = False
    assert views._guidance_setup_url(actor, edition) == ""
    actor.is_platform_administrator = True
    edition.adoption_profile_code = "full_convention"
    assert views._guidance_setup_url(actor, edition) == ""
    query.assert_not_called()


@pytest.mark.parametrize("error", [PermissionDenied, ValidationError, DatabaseError])
def test_unavailable_setup_never_discloses_link(setup, error):
    actor, edition, query = setup
    query.side_effect = error("private failure")
    assert views._guidance_setup_url(actor, edition) == ""


def test_ready_guides_do_not_offer_duplicate_setup(setup):
    actor, edition, query = setup
    query.return_value.guidance_ready = True
    assert views._guidance_setup_url(actor, edition) == ""
