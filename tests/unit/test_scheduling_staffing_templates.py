"""Staffing navigation has one purpose-selected native focus destination."""

from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from django import forms
from django.template.loader import render_to_string


class FocusTargets(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.targets = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "data-maru-focus-on-load" in values:
            self.targets.append((tag, values.get("id"), values.get("role")))


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("overview", ("h2", "planning-staffing-title", None)),
        ("form", ("h2", "planning-control-title", None)),
        ("preview", ("h2", "staffing-impact-title", None)),
        ("invalid", ("div", None, "alert")),
        ("ordinary", ("h2", "planning-selected-title", None)),
    ],
)
def test_staffing_focus_does_not_return_to_unrelated_item_heading(mode, expected):
    form = forms.Form(data={} if mode == "invalid" else None)
    form.fields["reason"] = forms.CharField(required=True)
    control = (
        SimpleNamespace(title="Synthetic staffing task", form=form, button_choices=())
        if mode in {"form", "preview", "invalid"}
        else None
    )
    html = render_to_string(
        "scheduling/_planning_tools.html",
        {
            "staffing_active": mode != "ordinary",
            "staffing_preview": {"synthetic": True} if mode == "preview" else None,
            "selected_item": SimpleNamespace(internal_title="Selected synthetic item"),
            "control": control,
        },
    )
    assert FocusTargets(html).targets == [expected]
