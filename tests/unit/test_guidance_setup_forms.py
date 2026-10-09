"""Foundation setup forms preserve real choices and route-owned parent identity."""

from uuid import UUID

from django.http import QueryDict

from maru.events.guidance_setup_forms import GuidanceSetupForm


def setup_data(**changes):
    data = QueryDict("", mutable=True)
    data.update(
        {
            "organization_name": "Synthetic organizers",
            "series_name": "Synthetic convention",
            "edition_name": "Synthetic 2027",
            "starts_on": "2027-06-18",
            "ends_on": "2027-06-20",
            "time_zone": "Europe/Budapest",
            "reason": "Prepare synthetic internal guides",
            "confirmed": "on",
            "foundation_fingerprint": "",
            "idempotency_key": str(UUID(int=1)),
        }
    )
    data.setlist("language_codes", ["en", "hu"])
    for name, value in changes.items():
        data[name] = value
    return data


def test_setup_retains_multiple_languages_with_readable_choices():
    form = GuidanceSetupForm(setup_data(), mode="new_foundation")
    assert form.is_valid(), form.errors
    assert form.setup_input().language_codes == ("en", "hu")
    assert ("en", "English") in form.fields["language_codes"].choices
    assert form.setup_input().organization_id is None


def test_setup_reuse_does_not_accept_a_renamed_parent():
    form = GuidanceSetupForm(
        setup_data(foundation_fingerprint="a" * 64),
        mode="existing_series",
        organization_id=UUID(int=2),
        series_id=UUID(int=3),
    )
    assert not form.is_valid()
    assert "cannot be renamed" in str(form.non_field_errors())


def test_setup_scope_actor_and_approval_cannot_be_smuggled_into_form():
    data = setup_data(
        actor_id=str(UUID(int=2)), organization_id=str(UUID(int=3)), approved="yes"
    )
    form = GuidanceSetupForm(data, mode="new_foundation")
    assert not form.is_valid()
    assert "unsupported input" in str(form.non_field_errors())


def test_setup_date_error_is_attached_to_end_date_and_keeps_input():
    form = GuidanceSetupForm(setup_data(ends_on="2027-06-17"), mode="new_foundation")
    assert not form.is_valid()
    assert "ends_on" in form.errors
    assert form["ends_on"].value() == "2027-06-17"
