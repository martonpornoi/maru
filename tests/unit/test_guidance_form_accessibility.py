"""Native error summaries target real focusable controls and choice groups."""

from html.parser import HTMLParser

import pytest
from django import forms
from django.template.loader import render_to_string


class ExampleForm(forms.Form):
    """Exercise text, radio and checkbox errors through the production partials."""

    title = forms.CharField(label="Title")
    decision = forms.ChoiceField(
        label="Decision",
        choices=(("accept", "Accept"), ("decline", "Decline")),
        widget=forms.RadioSelect,
    )
    placements = forms.MultipleChoiceField(
        label="Where to show this guide",
        choices=(("writing", "Writing guides"),),
        widget=forms.CheckboxSelectMultiple,
    )


class FormMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            assert attributes["id"] not in self.elements
            self.elements[attributes["id"]] = (tag, attributes)


@pytest.mark.parametrize("owner", ["knowledge", "announcements"])
def test_error_links_target_controls_or_focusable_choice_groups(owner):
    form = ExampleForm({})
    assert not form.is_valid()
    html = render_to_string(
        f"{owner}/_form.html",
        {"form": form, "submit_label": "Save"},
    )
    markup = FormMarkup()
    markup.feed(html)
    assert 'href="#id_title"' in html
    tag, attributes = markup.elements["id_title"]
    assert tag == "input"
    assert attributes["type"] == "text"
    assert "disabled" not in attributes
    for field in ("decision", "placements"):
        assert f'href="#id_{field}_field"' in html
        tag, attributes = markup.elements[f"id_{field}_field"]
        assert tag == "div"
        assert attributes["tabindex"] == "-1"
    assert 'href="#"' not in html
    assert "<legend>Decision (required)</legend>" in html
    assert "<legend>Where to show this guide (required)</legend>" in html
    assert '<label for="id_title">' in html
    assert '<label for="id_decision_0">' in html
    assert '<label for="id_placements_0">' in html
    assert "<script" not in html
