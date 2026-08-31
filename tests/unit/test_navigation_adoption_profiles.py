"""Unit coverage for exact adoption-profile navigation filtering."""

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from maru.core.navigation import (
    NavigationItem,
    _personal_items,
    _profile_filtered_items,
    _specialist_items,
)

if TYPE_CHECKING:
    from django.http import HttpRequest

    from maru.events.models import EventEdition


def _item(code: str, profile_destination_kind: str = "") -> NavigationItem:
    return NavigationItem(
        code=code,
        label=code,
        url=f"/{code}/",
        section="Test",
        profile_destination_kind=profile_destination_kind,
    )


def test_navigation_filters_destinations_against_the_exact_profile_pair() -> None:
    """Keep unscoped items while selecting only pinned edition destinations."""
    edition = cast(
        "EventEdition",
        SimpleNamespace(
            adoption_profile_code="workforce_only",
            adoption_profile_version=1,
        ),
    )

    items = _profile_filtered_items(
        items=(
            _item("unscoped"),
            _item("workforce", "work.workforce"),
            _item("registration", "edition.registration"),
        ),
        edition=edition,
    )

    assert [item.code for item in items] == ["unscoped", "workforce"]


def test_navigation_fails_closed_for_an_unknown_profile_version() -> None:
    """Disclose no edition destination when its exact manifest is unknown."""
    edition = cast(
        "EventEdition",
        SimpleNamespace(
            adoption_profile_code="workforce_only",
            adoption_profile_version=2,
        ),
    )

    items = _profile_filtered_items(
        items=(
            _item("unscoped"),
            _item("workforce", "work.workforce"),
        ),
        edition=edition,
    )

    assert [item.code for item in items] == ["unscoped"]


def test_specialist_items_filter_only_governed_unpinned_apps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep foundation/global records while hiding retained Registration."""
    edition = cast(
        "EventEdition",
        SimpleNamespace(
            adoption_profile_code="workforce_only",
            adoption_profile_version=1,
        ),
    )
    request = cast(
        "HttpRequest",
        SimpleNamespace(path="/admin/"),
    )
    monkeypatch.setattr(
        "maru.events.admin_context.selected_admin_edition",
        lambda _request: edition,
    )
    available_apps = (
        {
            "app_label": "registration",
            "name": "Registration",
            "models": (
                {
                    "admin_url": "/admin/registration/registrationconfiguration/",
                    "object_name": "RegistrationConfiguration",
                    "name": "Registration configurations",
                },
            ),
        },
        {
            "app_label": "identity",
            "name": "Identity",
            "models": (
                {
                    "admin_url": "/admin/identity/accountsecurityevent/",
                    "object_name": "AccountSecurityEvent",
                    "name": "Account security events",
                },
            ),
        },
        {
            "app_label": "privacyops",
            "name": "Privacy operations",
            "models": (
                {
                    "admin_url": "/admin/privacyops/disposalreceipt/",
                    "object_name": "DisposalReceipt",
                    "name": "Disposal receipts",
                },
            ),
        },
    )

    codes = {item.code for item in _specialist_items(request, available_apps)}

    assert codes == {
        "record.identity.accountsecurityevent",
        "record.privacyops.disposalreceipt",
    }


def test_personal_destinations_follow_only_disclosed_exact_profile_pairs() -> None:
    """Keep global personal links while gating every module destination."""
    request = cast(
        "HttpRequest",
        SimpleNamespace(resolver_match=None, GET={}),
    )

    full_codes = {
        item.code
        for item in _personal_items(
            request,
            profile_pairs=(("full_convention", 1),),
        )
    }
    workforce_codes = {
        item.code
        for item in _personal_items(
            request,
            profile_pairs=(("workforce_only", 1),),
        )
    }
    unknown_codes = {
        item.code
        for item in _personal_items(
            request,
            profile_pairs=(("workforce_only", 2),),
        )
    }

    assert full_codes == {
        "my.home",
        "my.registrations",
        "my.catalog",
        "my.applications",
        "my.workforce",
        "my.schedule",
        "my.equipment_offers",
        "my.governance-invitations",
    }
    assert workforce_codes == {
        "my.home",
        "my.workforce",
        "my.governance-invitations",
    }
    assert unknown_codes == {"my.home", "my.governance-invitations"}
