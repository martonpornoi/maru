"""Typed browser dates retain the existing domain precision and zone fences."""

from datetime import UTC, date, datetime

import pytest
from django import forms
from django.template.loader import render_to_string

from maru.applications.forms import EditionLocalDateTimeField as ApplicationTime
from maru.catalog.forms import CatalogEditionLocalDateTimeField
from maru.charities.forms import CharityEditionLocalDateTimeField
from maru.core.widgets import ISODateInput, ISODateTimeInput
from maru.events.forms import WorkforceAdoptionSetupForm
from maru.logistics.forms import CanonicalLocalDateTimeField
from maru.organizations.forms import (
    RepresentationProvisionForm,
    RepresentationResponseForm,
)
from maru.registration.setup_forms import EditionLocalDateTimeField as RegistrationTime
from maru.venues.forms import EditionLocalDateTimeField as VenueTime
from maru.workforce.forms import WorkforceEditionLocalDateTimeField

FIELDS = (
    ApplicationTime,
    CatalogEditionLocalDateTimeField,
    CharityEditionLocalDateTimeField,
    CanonicalLocalDateTimeField,
    RegistrationTime,
    VenueTime,
    WorkforceEditionLocalDateTimeField,
)


@pytest.mark.parametrize("field_type", FIELDS)
@pytest.mark.parametrize(
    "value", ["2031-06-06 10:00:00", "2031-06-06 10:00", "2031-06-06T10:00"]
)
def test_typed_local_time_reaches_the_original_edition_zone(field_type, value):
    form = forms.Form({"starts_at": value})
    form.fields["starts_at"] = field_type(zone_name="Europe/Budapest")
    assert form.is_valid(), form.errors
    assert form.cleaned_data["starts_at"].astimezone(UTC) == datetime(
        2031, 6, 6, 8, tzinfo=UTC
    )
    assert 'type="text"' in str(form["starts_at"])
    rendered = str(form["starts_at"])
    if isinstance(form.fields["starts_at"].widget, forms.MultiWidget):
        assert 'value="2031-06-06"' in rendered
        assert 'value="10:00"' in rendered
    else:
        assert 'value="2031-06-06 10:00:00"' in rendered


@pytest.mark.parametrize("field_type", FIELDS)
@pytest.mark.parametrize(
    "value",
    [
        "2031-02-30 10:00:00",
        "2031-06-06 25:00:00",
        "2031-06-06 10:00:01",
        "2026-10-25 02:30:00",
        "2026-03-29 02:30:00",
        "2031-06-06 10:00:00Z",
        "06/06/2031 10:00 AM",
        " 2031-06-06 10:00:00",
    ],
)
def test_typed_input_cannot_bypass_precision_or_dst_validation(field_type, value):
    form = forms.Form({"starts_at": value})
    form.fields["starts_at"] = field_type(zone_name="Europe/Budapest")
    assert not form.is_valid()
    assert "starts_at" in form.errors
    # Error redisplay keeps the submitted value available for correction.
    assert form["starts_at"].value() == form.fields[
        "starts_at"
    ].widget.value_from_datadict(form.data, {}, "starts_at")


def test_date_input_is_directly_editable_and_calendar_independent():
    widget = ISODateInput(attrs={"type": "date"})
    assert widget.input_type == "text"
    assert 'value="2031-06-06"' in widget.render("day", date(2031, 6, 6))
    assert 'placeholder="YYYY-MM-DD"' in widget.render("day", None)


def test_timestamp_widget_never_truncates_nonzero_seconds():
    widget = ISODateTimeInput()
    assert (
        widget.value_from_datadict({"at": "2031-06-06 10:00:27"}, {}, "at")
        == "2031-06-06T10:00:27"
    )
    assert 'value="2031-06-06 10:00:27"' in widget.render("at", "2031-06-06T10:00:27")
    assert 'value="invalid typed value"' in widget.render("at", "invalid typed value")


@pytest.mark.parametrize(
    ("form", "field_name"),
    [
        (RepresentationProvisionForm(), "representation_code"),
        (RepresentationResponseForm(), "decision"),
    ],
)
def test_governance_choices_have_a_group_legend_and_individual_labels(form, field_name):
    html = render_to_string(
        "core/_baseline_form_field.html", {"field": form[field_name]}
    )
    assert "<fieldset" in html
    assert "<legend>" in html
    assert html.count('type="radio"') >= 2
    assert "baseline-choice-field" in html
    assert 'for="id_' + field_name + '_0"' in html


def test_workforce_setup_does_not_default_to_duplicate_creation():
    form = WorkforceAdoptionSetupForm()
    assert "mode" not in form.initial
    form.fields["organization"].choices = []
    form.fields["series"].choices = []
    html = render_to_string("core/_baseline_form_field.html", {"field": form["mode"]})
    assert "checked" not in html


def test_choice_groups_reference_their_own_help_and_validation_errors():
    class TwoChoicesForm(forms.Form):
        first = forms.ChoiceField(
            choices=[("yes", "Yes"), ("no", "No")],
            widget=forms.RadioSelect,
            help_text="Choose the first answer.",
        )
        second = forms.ChoiceField(
            choices=[("yes", "Yes"), ("no", "No")],
            widget=forms.RadioSelect,
            help_text="Choose the second answer.",
        )

    form = TwoChoicesForm({})
    assert not form.is_valid()
    html = "".join(
        render_to_string("core/_baseline_form_field.html", {"field": form[name]})
        for name in ("first", "second")
    )
    for name in ("first", "second"):
        assert f'aria-describedby="id_{name}_helptext id_{name}_error"' in html
        assert html.count(f'id="id_{name}_helptext"') == 1
        assert html.count(f'id="id_{name}_error"') == 1
    assert 'id="_helptext"' not in html
