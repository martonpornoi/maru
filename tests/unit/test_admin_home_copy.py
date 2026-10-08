"""The first organizer page explains tasks before technical profile details."""

from types import SimpleNamespace

import pytest
from django.template import Context
from django.template.loader import get_template
from django.template.loader_tags import BlockNode

from maru.events.adoption import adoption_profile


def _render_home(monkeypatch, profile):
    monkeypatch.setattr(
        "maru.events.templatetags.admin_edition_context.admin_edition_options",
        lambda _request: {
            "selected": SimpleNamespace(name="Synthetic event"),
            "selected_profile": profile,
        },
    )
    template = get_template("admin/index.html").template
    content = next(
        block
        for block in template.nodelist.get_nodes_by_type(BlockNode)
        if block.name == "content"
    )
    return content.render(
        Context(
            {
                "request": SimpleNamespace(
                    user=SimpleNamespace(is_platform_administrator=False)
                ),
                "maru_shell_access": {"workspace_available": True},
            }
        )
    )


@pytest.mark.parametrize(
    ("profile_code", "purpose"),
    [
        ("full_convention", "Use the tools below to set up and run this event."),
        (
            "workforce_only",
            "Plan your volunteer team's roles, availability, and shifts.",
        ),
    ],
)
def test_supported_home_keeps_profile_explanation_in_closed_details(
    monkeypatch, profile_code, purpose
):
    profile = adoption_profile(profile_code, 1)
    assert profile is not None

    html = _render_home(monkeypatch, profile)

    introduction, disclosure = html.split(
        '<details class="maru-admin-profile-details">', 1
    )
    details, _rest = disclosure.split("</details>", 1)
    assert purpose in introduction
    assert profile.description not in introduction
    assert "<summary>Technical setup details</summary>" in details
    assert profile.description in details
    assert html.count(profile.description) == 1
    assert "Continue setup" in html
    if profile_code == "workforce_only":
        assert "Team workspace" in html
        assert "Registration desk" not in html


def test_unknown_home_setup_explains_next_step_without_offering_unavailable_work(
    monkeypatch,
):
    html = _render_home(monkeypatch, None)

    assert "This event uses tools that this version of Maru cannot open." in html
    assert "Choose another event or ask an administrator to check its setup." in html
    assert "adoption profile" not in html
    assert "Technical setup details" not in html
    assert "Continue setup" not in html
    assert "Team workspace" not in html
    assert "Registration desk" not in html
