"""24-hour deadline entry preserves strict transport, zones and error recovery."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup
from django.http import QueryDict

from maru.applications.forms import StarterCopyForm


def _data():
    data = QueryDict(mutable=True)
    data.update(
        {
            "retry_key": str(uuid4()),
            "opens_at_date": "2027-01-01",
            "opens_at_time": "00:00",
            "applicant_edit_until_date": "2027-02-01",
            "applicant_edit_until_time": "12:00",
            "closes_at_date": "2027-03-01",
            "closes_at_time": "23:59",
        }
    )
    return data


@pytest.mark.parametrize("clock", ["00:00", "12:00", "23:59"])
@pytest.mark.parametrize(("date", "offset"), [("2026-01-01", 1), ("2026-07-01", 2)])
def test_clock_and_edition_zone_are_preserved(clock, date, offset):
    data = _data()
    data["opens_at_date"] = date
    data["opens_at_time"] = clock
    form = StarterCopyForm(data, edition_time_zone="Europe/Budapest")
    assert form.is_valid(), form.errors
    opening = form.cleaned_data["opens_at"]
    assert opening.strftime("%H:%M") == clock
    assert opening.utcoffset() == timedelta(hours=offset)


@pytest.mark.parametrize(
    ("date", "clock", "code"),
    [
        ("2026-03-29", "02:30", "nonexistent"),
        ("2026-10-25", "02:30", "ambiguous"),
        ("2026-01-01", "24:00", "invalid"),
        ("2026-01-01", "12:60", "invalid"),
        ("2026-01-01", "12:00 PM", "invalid"),
        ("2026-01-01", "1:00", "invalid"),
        ("2026-01-01", "12:00:00", "invalid"),
        ("2026-01-01", "12:00+01:00", "invalid"),
        ("2026-02-30", "12:00", "invalid"),
        ("2026-01-01", "", "invalid"),
        ("", "12:00", "invalid"),
        ("", "", "required"),
    ],
)
def test_invalid_or_incomplete_split_deadlines_remain_refused(date, clock, code):
    data = _data()
    data["opens_at_date"] = date
    data["opens_at_time"] = clock
    form = StarterCopyForm(data, edition_time_zone="Europe/Budapest")
    assert not form.is_valid()
    assert form.errors.as_data()["opens_at"][0].code == code


@pytest.mark.parametrize("part", ["opens_at_date", "opens_at_time", "closes_at_time"])
def test_repeated_split_values_are_not_silently_selected(part):
    data = _data()
    data.appendlist(part, data[part])
    form = StarterCopyForm(data, edition_time_zone="Europe/Budapest")
    assert not form.is_valid()
    assert form.non_field_errors().as_data()[0].code == "invalid_input_cardinality"


@pytest.mark.parametrize("scalar", ["", "2027-01-01T00:00"])
def test_mixed_combined_and_split_values_are_refused_even_when_equal(scalar):
    data = _data()
    data["opens_at"] = scalar
    form = StarterCopyForm(data, edition_time_zone="Europe/Budapest")
    assert not form.is_valid()
    assert form.non_field_errors().as_data()[0].code == "invalid_input_cardinality"


@pytest.mark.parametrize("extra", ["actor_id", "retry_key_time", "opens_at_zone"])
def test_split_controls_do_not_admit_other_request_values(extra):
    data = _data()
    data[extra] = "unexpected"
    form = StarterCopyForm(data, edition_time_zone="Europe/Budapest")
    assert not form.is_valid()
    assert form.non_field_errors().as_data()[0].code == "unknown_input_field"


def test_initial_deadline_uses_edition_date_and_explicit_24_hour_clock():
    form = StarterCopyForm(
        initial={"opens_at": datetime(2026, 12, 31, 23, tzinfo=UTC)},
        edition_time_zone="Europe/Budapest",
    )
    soup = BeautifulSoup(str(form["opens_at"]), "html.parser")
    calendar = soup.select_one('[name="opens_at_date"]')
    clock = soup.select_one('[name="opens_at_time"]')
    assert (calendar["type"], calendar["value"]) == ("date", "2027-01-01")
    assert (clock["type"], clock["value"]) == ("text", "00:00")
    assert clock["aria-label"] == "Opens: Time (24-hour)"
    assert "Midnight is 00:00; noon is 12:00." in soup.get_text()
    assert form["opens_at"].id_for_label == calendar["id"]
    for node in (calendar, clock):
        assert soup.select_one(f'label[for="{node["id"]}"]')


def test_invalid_clock_retains_both_values_and_accessible_error_references():
    data = _data()
    data["opens_at_time"] = "24:00"
    form = StarterCopyForm(data, edition_time_zone="Europe/Budapest")
    form.fields["opens_at"].help_text = "Times use Europe/Budapest."
    assert not form.is_valid()
    soup = BeautifulSoup(str(form["opens_at"]), "html.parser")
    assert soup.select_one('[name="opens_at_date"]')["value"] == "2027-01-01"
    assert soup.select_one('[name="opens_at_time"]')["value"] == "24:00"
    for node in soup.select("input"):
        assert node.has_attr("required")
        assert node["aria-invalid"] == "true"
        assert "id_opens_at_helptext" in node["aria-describedby"].split()
        assert "id_opens_at_error" in node["aria-describedby"].split()
