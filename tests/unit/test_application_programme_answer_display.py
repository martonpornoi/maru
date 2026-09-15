"""Pure typed review display without reference resolution or unsafe markup."""

import pytest

from maru.applications.programme_answer_display import (
    programme_choice_display_options as choices,
)
from maru.applications.programme_answer_display import (
    programme_review_answer_text as display,
)
from maru.applications.programme_review_rules import ProgrammeReviewUnavailableError

OPTIONS = [
    {"code": "talk", "label": "Talk & discussion"},
    {"code": "workshop", "label": "Practical <workshop>"},
    {"code": "other", "label": "Unselected private option"},
]
ADDRESS = {
    "country_code": "HU",
    "postal_code": "1000",
    "region": "",
    "line_2": "",
    "line_1": "Synthetic street 1",
    "locality": "Example city",
}


def answer(kind, value, **extra):
    return display({"type": kind, "value": value, **extra})


@pytest.mark.parametrize(
    ("kind", "value", "expected"),
    [
        ("short_text", "Exact title", "Exact title"),
        (
            "long_text",
            "Line one\n<script>escape me</script>",
            "Line one\n<script>escape me</script>",
        ),
        ("email", "person@example.invalid", "person@example.invalid"),
        ("phone", "+36000000000", "+36000000000"),
        ("url", "https://example.invalid/private", "https://example.invalid/private"),
        ("boolean", False, "No"),
        ("boolean", True, "Yes"),
        ("integer", 0, "0"),
        ("integer", -(2**31), str(-(2**31))),
        ("decimal", "0.00", "0.00"),
        ("decimal", "-1.2500", "-1.2500"),
        ("date", "2026-09-15", "2026-09-15"),
        ("time", "18:30:00", "18:30:00"),
        ("time", "18:30:00+02:00", "18:30:00+02:00"),
        ("instant", "2026-09-15T18:30:00+02:00", "2026-09-15 18:30:00+02:00"),
        ("instant", "2026-09-15T18:30:00-05:00", "2026-09-15 18:30:00-05:00"),
    ],
)
def test_typed_scalars_keep_exact_meaning_without_links_or_inferred_timezone(
    kind, value, expected
):
    assert answer(kind, value) == expected


@pytest.mark.parametrize(
    "kind",
    [
        "short_text",
        "boolean",
        "integer",
        "decimal",
        "single_choice",
        "multiple_choice",
        "address",
        "safe_file",
        "person_reference",
        "domain_reference",
        "date",
        "time",
        "instant",
    ],
)
def test_absence_is_not_false_zero_or_empty_selection(kind):
    assert (
        answer(kind, None, selected_options=OPTIONS)
        == "No answer in this exact revision."
    )


def test_single_choice_uses_only_original_selected_label():
    selected = choices("single_choice", "workshop", OPTIONS)
    assert selected == [OPTIONS[1]]
    assert (
        answer("single_choice", "workshop", selected_options=selected)
        == "Practical <workshop>"
    )


def test_multiple_choices_preserve_order_and_distinguish_explicit_empty_selection():
    selected = choices("multiple_choice", ["workshop", "talk"], OPTIONS)
    assert selected == [OPTIONS[1], OPTIONS[0]]
    assert (
        answer("multiple_choice", ["workshop", "talk"], selected_options=selected)
        == "• Practical <workshop>\n• Talk & discussion"
    )
    assert (
        answer("multiple_choice", [], selected_options=[])
        == "No options selected in this exact revision."
    )
    assert choices("multiple_choice", [], OPTIONS) == []


def test_unicode_choice_labels_and_codes_use_character_bounds():
    options = [
        {"code": "界" * 80, "label": "界" * 160},
        {"code": "other", "label": "Other"},
    ]
    selected = choices("single_choice", "界" * 80, options)
    assert answer("single_choice", "界" * 80, selected_options=selected) == "界" * 160


def test_address_is_ordered_labelled_and_omits_only_empty_optional_components():
    assert answer("address", ADDRESS) == (
        "Address line 1: Synthetic street 1\nCity or locality: Example city\n"
        "Postal code: 1000\nCountry code: HU"
    )
    assert "Address line 2: Floor 2" in answer(
        "address", ADDRESS | {"line_2": "Floor 2"}
    )


@pytest.mark.parametrize("kind", ["safe_file", "person_reference", "domain_reference"])
@pytest.mark.parametrize(
    "value", ["private-identifier", {"private": "payload"}, ["private-file"]]
)
def test_protected_references_ignore_identifying_values_and_spurious_display_data(
    kind, value
):
    text = answer(kind, value, display_text="PRIVATE", selected_options=OPTIONS)
    assert "no download or person lookup" in text
    assert "PRIVATE" not in text
    assert "private-identifier" not in text
    assert "payload" not in text


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("unknown", "hidden"),
        ("boolean", "false"),
        ("boolean", 0),
        ("integer", True),
        ("integer", 1.0),
        ("integer", "1"),
        ("integer", 2**31),
        ("integer", -(2**31) - 1),
        ("decimal", True),
        ("decimal", "NaN"),
        ("decimal", "Infinity"),
        ("decimal", "not-a-number"),
        ("decimal", {}),
        ("date", "2026-02-30"),
        ("time", "25:00"),
        ("instant", "2026-09-15T18:00"),
        ("instant", "invalid"),
        ("short_text", {}),
        ("long_text", ["one", "two"]),
        pytest.param("short_text", "x" * 65537, id="oversized-text"),
        pytest.param("short_text", "\ud800", id="invalid-unicode"),
        ("single_choice", "missing"),
        ("multiple_choice", ["talk"]),
        ("address", {}),
        ("address", ADDRESS | {"secret": "hidden"}),
        ("address", ADDRESS | {"line_1": ""}),
        ("address", ADDRESS | {"region": 1}),
        ("address", ADDRESS | {"line_2": "x" * 201}),
        ("address", ADDRESS | {"country_code": "HUN"}),
        ("address", ADDRESS | {"country_code": "12"}),
    ],
)
def test_malformed_projection_is_unavailable_not_raw_repr_or_silent_guess(kind, value):
    with pytest.raises(ProgrammeReviewUnavailableError):
        answer(kind, value)


@pytest.mark.parametrize("row", [None, [], {}, {"type": []}, {"type": "short_text"}])
def test_missing_or_malformed_envelope_is_unavailable(row):
    with pytest.raises(ProgrammeReviewUnavailableError):
        display(row)


@pytest.mark.parametrize(
    "value",
    [
        ["talk", "talk"],
        [True],
        [["talk"]],
        "talk",
        ["unknown"],
        ["x" * 81],
        ["talk"] * 101,
    ],
)
def test_invalid_multiple_selection_cannot_produce_option_labels(value):
    with pytest.raises(ProgrammeReviewUnavailableError):
        choices("multiple_choice", value, OPTIONS)


@pytest.mark.parametrize(
    "options",
    [
        None,
        {},
        [],
        OPTIONS[:1],
        OPTIONS * 40,
        [*OPTIONS, OPTIONS[0]],
        [{"code": "a", "label": ""}, OPTIONS[1]],
        [{"code": "a", "label": "x" * 161}, OPTIONS[1]],
        [{"code": "a", "label": "A", "extra": "secret"}, OPTIONS[1]],
    ],
)
def test_malformed_option_metadata_is_closed_and_bounded(options):
    with pytest.raises(ProgrammeReviewUnavailableError):
        choices("single_choice", "workshop", options)


@pytest.mark.parametrize(
    "selected",
    [
        None,
        {},
        [],
        OPTIONS,
        [OPTIONS[0]],
        [{"code": "workshop", "label": ""}],
        [{"code": "workshop", "label": "W", "extra": "hidden"}],
    ],
)
def test_choice_display_requires_exact_selected_code_label_correspondence(selected):
    with pytest.raises(ProgrammeReviewUnavailableError):
        answer("single_choice", "workshop", selected_options=selected)


def test_non_choice_cannot_request_option_projection():
    with pytest.raises(ProgrammeReviewUnavailableError):
        choices("short_text", "talk", OPTIONS)
