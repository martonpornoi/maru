"""File-local Workforce proposals, hostile inputs and bounded diagnostics."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from maru.workforce.import_format import import_schema, validate_import_bytes

EXAMPLE = Path(__file__).resolve().parents[2] / "docs/examples/workforce-import-v1.json"
SECTIONS = (
    "departments",
    "positions",
    "people",
    "assignments",
    "shifts",
    "commitments",
)


@pytest.fixture
def proposal():
    return json.loads(EXAMPLE.read_bytes())


def _report(proposal):
    return validate_import_bytes(json.dumps(proposal).encode()).as_document()


def _has(proposal, code, location):
    report = _report(proposal)
    assert report["status"] == "invalid"
    assert report["counts"] is None
    assert (code, location) in {
        (issue["code"], issue["location"]) for issue in report["issues"]
    }


def test_example_schema_and_normative_validation_agree():
    raw = EXAMPLE.read_bytes()
    schema = import_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        json.loads(raw)
    )
    report = validate_import_bytes(raw).as_document()
    assert report["status"] == "valid"
    assert report["counts"] == dict.fromkeys(SECTIONS, 1)
    assert report["issues"] == []
    assert report["issues_truncated"] is False
    assert "No Maru records were changed" in report["assurance"]
    assert EXAMPLE.read_bytes() == raw


def test_empty_proposal_is_valid_without_claiming_readiness(proposal):
    for section in SECTIONS:
        proposal[section] = []
    report = _report(proposal)
    assert report["status"] == "valid"
    assert report["counts"] == dict.fromkeys(SECTIONS, 0)
    assert "approvals and live coverage were not checked" in report["assurance"]


def test_documented_invalid_example_can_be_corrected_without_external_state():
    document = json.loads(
        EXAMPLE.with_name("workforce-import-v1-invalid.json").read_bytes()
    )
    _has(document, "unknown_reference", "/positions/0/department_key")
    document["departments"] = [
        {"key": "missing-team", "name": "Fictional team", "parent_key": None}
    ]
    assert _report(document)["status"] == "valid"


@pytest.mark.parametrize(
    ("section", "fields"),
    [
        ("departments", ("key", "name", "parent_key")),
        ("positions", ("key", "department_key", "title")),
        ("people", ("key", "label")),
        ("assignments", ("key", "person_key", "position_key")),
        ("shifts", ("key", "position_key", "starts_at", "ends_at", "capacity")),
        ("commitments", ("key", "assignment_key", "shift_key")),
    ],
)
def test_every_row_field_is_required_and_only_parent_may_be_null(
    proposal, section, fields
):
    original = deepcopy(proposal)
    for field in fields:
        proposal = deepcopy(original)
        del proposal[section][0][field]
        _has(proposal, "missing_field", f"/{section}/0/{field}")
        if field != "parent_key":
            proposal[section][0][field] = None
            _has(proposal, "invalid_field", f"/{section}/0/{field}")


def test_schema_rejects_structural_errors_and_does_not_claim_semantic_validation(
    proposal,
):
    validator = Draft202012Validator(import_schema())
    proposal["people"][0]["contact"] = "PRIVATE_SENTINEL"
    assert list(validator.iter_errors(proposal))
    del proposal["people"][0]["contact"]
    proposal["commitments"][0]["assignment_key"] = "absent"
    assert list(validator.iter_errors(proposal)) == []
    _has(proposal, "unknown_reference", "/commitments/0/assignment_key")


@pytest.mark.parametrize("field", ["format", "version", "profile", "scope", *SECTIONS])
def test_every_root_field_is_required(proposal, field):
    del proposal[field]
    _has(proposal, "missing_field", f"/{field}")


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("format", "maru.workforce-rota", "unsupported_format"),
        ("format", None, "unsupported_format"),
        ("version", 2, "unsupported_version"),
        ("version", True, "unsupported_version"),
        ("version", "1", "unsupported_version"),
        ("profile", "full@1", "unsupported_profile"),
        ("profile", {}, "unsupported_profile"),
    ],
)
def test_format_version_and_profile_are_exact(proposal, field, value, code):
    proposal[field] = value
    _has(proposal, code, f"/{field}")


@pytest.mark.parametrize("section", SECTIONS)
def test_arrays_rows_and_keys_have_explicit_types(proposal, section):
    original = deepcopy(proposal)
    proposal[section] = {}
    _has(proposal, "invalid_field", f"/{section}")
    proposal = deepcopy(original)
    proposal[section] = [None]
    _has(proposal, "invalid_field", f"/{section}/0")
    proposal = deepcopy(original)
    del proposal[section][0]["key"]
    _has(proposal, "missing_field", f"/{section}/0/key")
    proposal = deepcopy(original)
    proposal[section][0]["key"] = False
    _has(proposal, "invalid_field", f"/{section}/0/key")


@pytest.mark.parametrize("field", ["organization_key", "edition_key", "time_zone"])
def test_scope_is_required_and_closed(proposal, field):
    del proposal["scope"][field]
    _has(proposal, "missing_field", f"/scope/{field}")


@pytest.mark.parametrize("section", ["scope", *SECTIONS])
def test_unknown_nested_fields_are_refused_without_echo(proposal, section):
    row = proposal[section] if section == "scope" else proposal[section][0]
    row["PRIVATE_UNKNOWN_SENTINEL"] = "PRIVATE_VALUE_SENTINEL"
    location = "/scope" if section == "scope" else f"/{section}/0"
    _has(proposal, "unknown_field", location)
    assert "SENTINEL" not in json.dumps(_report(proposal))


def test_unknown_root_and_invalid_scope_are_refused(proposal):
    proposal["PRIVATE_UNKNOWN_SENTINEL"] = "PRIVATE_VALUE_SENTINEL"
    proposal["scope"] = []
    _has(proposal, "unknown_field", "/")
    _has(proposal, "invalid_field", "/scope")
    assert "SENTINEL" not in json.dumps(_report(proposal))


@pytest.mark.parametrize("key", ["", "A", " a", "a ", "a/b", "1a", "á", "a" * 65])
def test_invalid_local_keys_are_refused(proposal, key):
    proposal["people"][0]["key"] = key
    _has(proposal, "invalid_field", "/people/0/key")


@pytest.mark.parametrize(
    "label",
    [
        "",
        " ",
        " Name",
        "Name ",
        "a" * 201,
        "a\n",
        "\x00",
        "\x85",
        "\ud800",
        "e\u0301",
        1,
        None,
    ],
)
def test_labels_are_trimmed_bounded_nfc_text(proposal, label):
    proposal["people"][0]["label"] = label
    _has(proposal, "invalid_field", "/people/0/label")


def test_duplicate_labels_do_not_match_people_and_key_bounds_are_inclusive(proposal):
    proposal["people"] = [
        {"key": "a", "label": "É" * 200},
        {"key": "a" * 64, "label": "É" * 200},
    ]
    proposal["assignments"][0]["person_key"] = "a"
    assert _report(proposal)["status"] == "valid"


@pytest.mark.parametrize("section", SECTIONS)
def test_duplicate_keys_are_typed_and_located(proposal, section):
    proposal[section].append(deepcopy(proposal[section][0]))
    _has(proposal, "duplicate_key", f"/{section}/1/key")


def test_same_key_in_different_sections_does_not_collide(proposal):
    for section in SECTIONS:
        proposal[section][0]["key"] = "same"
    proposal["positions"][0]["department_key"] = "same"
    proposal["assignments"][0].update(person_key="same", position_key="same")
    proposal["shifts"][0]["position_key"] = "same"
    proposal["commitments"][0].update(assignment_key="same", shift_key="same")
    assert _report(proposal)["status"] == "valid"


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("departments", "parent_key"),
        ("positions", "department_key"),
        ("assignments", "person_key"),
        ("assignments", "position_key"),
        ("shifts", "position_key"),
        ("commitments", "assignment_key"),
        ("commitments", "shift_key"),
    ],
)
def test_every_reference_stays_in_its_typed_file_section(proposal, section, field):
    proposal[section][0][field] = "fictional-moonfox"  # scope key is not a record
    _has(proposal, "unknown_reference", f"/{section}/0/{field}")


@pytest.mark.parametrize("length", [1, 16, 17])
def test_department_ancestry_ceiling(proposal, length):
    proposal["departments"] = [
        {
            "key": f"d{index}",
            "name": "Fictional team",
            "parent_key": f"d{index - 1}" if index else None,
        }
        for index in range(length)
    ]
    proposal["positions"][0]["department_key"] = "d0"
    if length <= 16:
        assert _report(proposal)["status"] == "valid"
    else:
        _has(proposal, "department_depth", "/departments/16/parent_key")


@pytest.mark.parametrize("self_cycle", [True, False])
def test_department_cycles_are_refused(proposal, self_cycle):
    proposal["departments"][0]["parent_key"] = "welcome" if self_cycle else "other"
    if not self_cycle:
        proposal["departments"].append(
            {"key": "other", "name": "Other", "parent_key": "welcome"}
        )
    _has(proposal, "department_cycle", "/departments/0/parent_key")


@pytest.mark.parametrize(
    ("section", "code"),
    [("assignments", "duplicate_assignment"), ("commitments", "duplicate_commitment")],
)
def test_duplicate_proposal_pairs_are_refused(proposal, section, code):
    row = deepcopy(proposal[section][0])
    row["key"] = "different-key"
    proposal[section].append(row)
    _has(proposal, code, f"/{section}/1")


def test_commitment_position_and_capacity_are_checked(proposal):
    proposal["positions"].append(
        {"key": "other", "title": "Other", "department_key": "welcome"}
    )
    proposal["people"].append({"key": "person-b", "label": "Fictional B"})
    proposal["assignments"].append(
        {"key": "assignment-b", "person_key": "person-b", "position_key": "other"}
    )
    proposal["commitments"].append(
        {
            "key": "commitment-b",
            "assignment_key": "assignment-b",
            "shift_key": "morning",
        }
    )
    _has(proposal, "position_mismatch", "/commitments/1/assignment_key")
    _has(proposal, "capacity_exceeded", "/shifts/0/capacity")
    proposal["assignments"][1]["position_key"] = "desk"
    proposal["shifts"][0]["capacity"] = 2
    assert _report(proposal)["status"] == "valid"


@pytest.mark.parametrize("capacity", [0, 1025, -1, True, "1", None])
def test_capacity_is_a_bounded_integer(proposal, capacity):
    proposal["shifts"][0]["capacity"] = capacity
    _has(proposal, "invalid_field", "/shifts/0/capacity")


def test_maximum_capacity_is_accepted(proposal):
    proposal["shifts"][0]["capacity"] = 1024
    assert _report(proposal)["status"] == "valid"


@pytest.mark.parametrize("zone", ["No/Such_Zone", "../UTC", "/UTC", "UTC\x00secret"])
def test_unavailable_or_unsafe_zone_is_refused(proposal, zone):
    proposal["scope"]["time_zone"] = zone
    code = "invalid_field" if "\x00" in zone else "invalid_time_zone"
    _has(proposal, code, "/scope/time_zone")


@pytest.mark.parametrize(
    "instant",
    [
        "2027-07-10",
        "2027-07-10T09:00",
        "2027-07-10T09:00:00",
        "2027-07-10T09:00:00.1+02:00",
        "2027-02-30T09:00:00Z",
        "2027-07-10T09:00:60Z",
        "2027-07-10T09:00:00+25:00",
        "2027-07-10T09:00:00+02:00\n",
    ],
)
def test_instants_require_real_dates_full_seconds_and_explicit_offset(
    proposal, instant
):
    proposal["shifts"][0]["starts_at"] = instant
    _has(proposal, "invalid_field", "/shifts/0/starts_at")


@pytest.mark.parametrize(
    ("start", "end", "code"),
    [
        ("2027-07-10T09:00:00+02:00", "2027-07-10T09:00:00+02:00", "invalid_interval"),
        ("2027-07-10T11:00:00+02:00", "2027-07-10T09:00:00+02:00", "invalid_interval"),
        ("2027-07-10T09:00:00Z", "2027-07-10T11:00:00+02:00", "time_zone_mismatch"),
        (
            "2027-03-28T02:30:00+01:00",
            "2027-03-28T04:30:00+02:00",
            "time_zone_mismatch",
        ),
        ("0001-01-01T00:00:00+02:00", "2027-07-10T11:00:00+02:00", "invalid_field"),
    ],
)
def test_intervals_and_zone_offsets_are_checked_at_each_instant(
    proposal, start, end, code
):
    proposal["shifts"][0].update(starts_at=start, ends_at=end)
    assert code in {issue["code"] for issue in _report(proposal)["issues"]}


@pytest.mark.parametrize(
    ("zone", "start", "end"),
    [
        ("Europe/Budapest", "2027-10-31T02:30:00+02:00", "2027-10-31T02:15:00+01:00"),
        ("Europe/Budapest", "2027-03-28T01:30:00+01:00", "2027-03-28T03:30:00+02:00"),
        ("UTC", "2000-01-01T09:00:00Z", "2000-01-01T10:00:00+00:00"),
    ],
)
def test_dst_transitions_and_past_proposals_use_utc_order(proposal, zone, start, end):
    proposal["scope"]["time_zone"] = zone
    proposal["shifts"][0].update(starts_at=start, ends_at=end)
    assert _report(proposal)["status"] == "valid"


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"\xff", "invalid_encoding"),
        (b"\xef\xbb\xbf{}", "invalid_encoding"),
        (b"{", "invalid_json"),
        (b"{}{}", "invalid_json"),
        (b'{"x":"PRIVATE_SENTINEL",}', "invalid_json"),
        (b'{"x":1,"x":2}', "duplicate_member"),
        (b'{"a":{"x":1,"x":2}}', "duplicate_member"),
        (b'{"version":1.0}', "invalid_json_number"),
        (b'{"version":1e0}', "invalid_json_number"),
        (b'{"x":NaN}', "invalid_json_number"),
        (b'{"x":Infinity}', "invalid_json_number"),
        (b'{"x":-Infinity}', "invalid_json_number"),
        (b'{"x":12345678901234567890}', "invalid_json_number"),
        (b'{"x":' + b"9" * 5000 + b"}", "invalid_json_number"),
        (b"[]", "invalid_document"),
        (b"null", "invalid_document"),
        (b"[" * 17 + b"0" + b"]" * 17, "too_deep"),
    ],
)
def test_decoder_failures_are_minimized(raw, code):
    report = validate_import_bytes(raw).as_document()
    assert report["issues"] == [
        {"code": code, "location": "/", "message": report["issues"][0]["message"]}
    ]
    assert report["status"] == "invalid"
    assert "PRIVATE_SENTINEL" not in json.dumps(report)


def test_depth_scanner_ignores_brackets_escaped_quotes_and_backslashes(proposal):
    proposal["people"][0]["label"] = '["' + "\\" * 20 + "]" * 100
    assert _report(proposal)["status"] == "valid"
    raw = b"[" * 16 + b"0" + b"]" * 16
    assert validate_import_bytes(raw).issues[0].code == "invalid_document"


def test_integer_token_ceiling_does_not_depend_on_python_decoder_configuration():
    assert (
        validate_import_bytes(b'{"version":1234567890123456789}').issues[0].code
        == "missing_field"
    )
    # The nineteen-digit token is decoded normally; a longer token is refused
    # before conversion even if Python's configurable integer limit is disabled.
    previous = sys.get_int_max_str_digits()
    try:
        sys.set_int_max_str_digits(0)
        for token in (b"9" * 20, b"-" + b"9" * 5000):
            assert (
                validate_import_bytes(b'{"x":' + token + b"}").issues[0].code
                == "invalid_json_number"
            )
    finally:
        sys.set_int_max_str_digits(previous)


def test_byte_limit_is_inclusive_and_read_only(proposal):
    raw = json.dumps(proposal).encode()
    at_limit = raw + b" " * (1_048_576 - len(raw))
    assert validate_import_bytes(at_limit).status == "valid"
    assert validate_import_bytes(at_limit + b" ").issues[0].code == "input_too_large"
    assert raw == json.dumps(proposal).encode()


@pytest.mark.parametrize(
    ("section", "limit"),
    [
        ("departments", 128),
        ("positions", 512),
        ("people", 2048),
        ("assignments", 4096),
        ("shifts", 1024),
        ("commitments", 4096),
    ],
)
def test_each_section_has_an_independent_row_ceiling(proposal, section, limit):
    proposal[section] = [None] * (limit + 1)
    _has(proposal, "too_many_records", f"/{section}")


def test_people_row_limit_accepts_exact_boundary(proposal):
    proposal["people"] = [
        {"key": f"p{i}", "label": "Fictional person"} for i in range(2048)
    ]
    proposal["assignments"][0]["person_key"] = "p0"
    assert _report(proposal)["status"] == "valid"


@pytest.mark.parametrize("count", [64, 65])
def test_issue_ceiling_and_truncation_are_exact_and_deterministic(proposal, count):
    proposal["people"] = [{"key": f"p{i}", "label": ""} for i in range(count)]
    first = _report(proposal)
    assert len(first["issues"]) == 64
    assert first["issues_truncated"] is (count > 64)
    assert first == _report(proposal)
    assert first["issues"][0]["location"] == "/people/0/label"
    assert first["issues"][-1]["location"] == "/people/63/label"


def test_schema_is_fresh_and_extra_schema_is_data_not_executable(proposal):
    first = import_schema()
    first["properties"].clear()
    assert import_schema()["properties"]
    proposal["$schema"] = "https://invalid.example/PRIVATE_SENTINEL"
    _has(proposal, "unknown_field", "/")
    assert "PRIVATE_SENTINEL" not in json.dumps(_report(proposal))


@pytest.mark.parametrize(
    ("section", "field"),
    [("people", "key"), ("people", "label"), ("shifts", "starts_at")],
)
def test_schema_patterns_do_not_accept_trailing_newlines(proposal, section, field):
    proposal[section][0][field] += "\n"
    assert list(Draft202012Validator(import_schema()).iter_errors(proposal))
