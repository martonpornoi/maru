"""Offline proposal comparison, value minimization and fail-closed limits."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from maru.workforce import import_comparison, import_validation
from maru.workforce.import_format import FIELDS, MAX_BYTES, validate_import_bytes

EXAMPLE = Path(__file__).resolve().parents[2] / "docs/examples/workforce-import-v1.json"


def proposal():
    return json.loads(EXAMPLE.read_bytes())


def encoded(document):
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def compared(before, after):
    report = import_comparison.compare_import_bytes(encoded(before), encoded(after))
    assert report.status == "compared", report.as_document()
    return report.as_document()


def test_identical_proposal_has_all_zero_counts_and_original_byte_hashes():
    raw = EXAMPLE.read_bytes()
    report = import_comparison.compare_import_bytes(raw, raw).as_document()
    assert report["status"] == "compared"
    assert report["changes"] == report["issues"] == []
    assert report["counts"] == {
        section: {"added": 0, "removed": 0, "changed": 0} for section in FIELDS
    }
    assert set(report["hashes"].values()) == {hashlib.sha256(raw).hexdigest()}
    assert "No Maru records or input files were changed" in report["assurance"]


def test_documented_fictional_revision_has_exactly_the_three_explained_changes():
    revised = EXAMPLE.with_name("workforce-import-v1-revised.json").read_bytes()
    report = import_comparison.compare_import_bytes(EXAMPLE.read_bytes(), revised)
    assert report.status == "compared"
    assert [(change.section, change.fields) for change in report.changes] == [
        ("departments", ("name",)),
        ("people", ("label",)),
        ("shifts", ("capacity",)),
    ]


def test_object_order_whitespace_and_row_order_do_not_create_changes():
    before = proposal()
    before["people"].append({"key": "second", "label": "Fictional person"})
    after = dict(reversed(list(before.items())))
    after["people"] = list(reversed(before["people"]))
    raw = encoded(before)
    revised = json.dumps(after, sort_keys=True, indent=3).encode()
    report = import_comparison.compare_import_bytes(raw, revised).as_document()
    assert report["status"] == "compared"
    assert report["changes"] == []
    assert report["hashes"]["before_sha256"] != report["hashes"]["after_sha256"]


@pytest.mark.parametrize(
    ("section", "field", "replacement"),
    [
        ("departments", "name", "PRIVATE_DEPARTMENT_SENTINEL"),
        ("positions", "title", "PRIVATE_POSITION_SENTINEL"),
        ("people", "label", "PRIVATE_PERSON_SENTINEL"),
        ("assignments", "person_key", "second"),
        ("shifts", "capacity", 2),
        ("commitments", "shift_key", "second"),
    ],
)
def test_each_typed_section_reports_only_changed_field_names(
    section, field, replacement
):
    before = proposal()
    before["people"].append({"key": "second", "label": "Fictional person"})
    shift = {**before["shifts"][0], "key": "second"}
    before["shifts"].append(shift)
    after = copy.deepcopy(before)
    after[section][0][field] = replacement
    report = compared(before, after)
    assert report["changes"] == [
        {
            "section": section,
            "action": "changed",
            "before_row": 0,
            "after_row": 0,
            "fields": [field],
        }
    ]
    assert report["counts"][section] == {"added": 0, "removed": 0, "changed": 1}
    assert "PRIVATE_" not in json.dumps(report)


@pytest.mark.parametrize("section", list(FIELDS))
def test_each_typed_section_can_be_added_and_removed_without_values(section):
    whole = proposal()
    empty = {**whole, **{name: [] for name in FIELDS}}
    # Retain all dependencies but discard all sections that depend on the target.
    subsets = {
        "departments": ["departments"],
        "positions": ["departments", "positions"],
        "people": ["people"],
        "assignments": ["departments", "positions", "people", "assignments"],
        "shifts": ["departments", "positions", "shifts"],
        "commitments": list(FIELDS),
    }
    before = {**empty, **{name: whole[name] for name in subsets[section]}}
    after = copy.deepcopy(before)
    after[section] = []
    removed = compared(before, after)
    added = compared(after, before)
    assert removed["changes"] == [
        {
            "section": section,
            "action": "removed",
            "before_row": 0,
            "after_row": None,
            "fields": [],
        }
    ]
    assert added["changes"] == [
        {
            "section": section,
            "action": "added",
            "before_row": None,
            "after_row": 0,
            "fields": [],
        }
    ]


def test_key_rename_is_removed_added_even_when_labels_match():
    before = proposal()
    before["people"].append({"key": "unused", "label": "Same fictional label"})
    after = copy.deepcopy(before)
    after["people"][1]["key"] = "renamed"
    changes = compared(before, after)["changes"]
    assert [row["action"] for row in changes] == ["removed", "added"]
    assert all(row["fields"] == [] for row in changes)
    assert "renamed" not in json.dumps(changes)


def test_row_locations_follow_each_original_file_and_fields_use_contract_order():
    before = proposal()
    before["shifts"].append({**before["shifts"][0], "key": "second"})
    after = copy.deepcopy(before)
    after["shifts"].reverse()
    after["shifts"][1].update(capacity=3, ends_at="2027-07-10T12:00:00+02:00")
    change = compared(before, after)["changes"][0]
    assert (change["before_row"], change["after_row"]) == (0, 1)
    assert change["fields"] == ["ends_at", "capacity"]


def test_equivalent_utc_spellings_remain_literal_field_changes():
    before = proposal()
    before["scope"]["time_zone"] = "UTC"
    before["shifts"][0].update(
        starts_at="2027-07-10T09:00:00Z", ends_at="2027-07-10T11:00:00Z"
    )
    after = copy.deepcopy(before)
    after["shifts"][0]["starts_at"] = "2027-07-10T09:00:00+00:00"
    assert compared(before, after)["changes"][0]["fields"] == ["starts_at"]


@pytest.mark.parametrize("field", ["organization_key", "edition_key", "time_zone"])
def test_scope_difference_has_no_counts_hashes_or_partial_changes(field):
    before = proposal()
    after = copy.deepcopy(before)
    after["scope"][field] = "different" if field != "time_zone" else "Europe/Paris"
    after["people"][0]["label"] = "PRIVATE_SENTINEL"
    report = import_comparison.compare_import_bytes(
        encoded(before), encoded(after)
    ).as_document()
    assert report["status"] == "invalid"
    assert report["issues"][0]["code"] == "incompatible_scope"
    assert report["changes"] == []
    assert report["counts"] == report["hashes"] == {}
    assert "PRIVATE_SENTINEL" not in json.dumps(report)


def test_both_inputs_validate_and_combined_issues_are_capped_with_truncation():
    before = proposal()
    before["people"] = [{} for _ in range(40)]
    after = {"PRIVATE_SENTINEL": "SECRET"}
    report = import_comparison.compare_import_bytes(
        encoded(before), encoded(after)
    ).as_document()
    assert report["status"] == "invalid"
    assert len(report["issues"]) == 64
    assert report["issues_truncated"] is True
    assert report["changes"] == []
    assert report["counts"] == report["hashes"] == {}
    assert "PRIVATE_SENTINEL" not in json.dumps(report)
    assert "SECRET" not in json.dumps(report)
    both = import_comparison.compare_import_bytes(b"{", b"[").as_document()
    assert [row["side"] for row in both["issues"]] == ["before", "after"]
    assert both["issues_truncated"] is False


@pytest.mark.parametrize(
    "invalid",
    [
        b"{",
        b"\xef\xbb\xbf{}",
        b'{"version":1,"version":1}',
        b" " * (MAX_BYTES + 1),
        b'{"version":1.0}',
    ],
    ids=["malformed", "bom", "duplicate-member", "byte-limit", "floating-token"],
)
def test_invalid_bytes_never_reach_comparison_or_hashes(invalid):
    report = import_comparison.compare_import_bytes(
        EXAMPLE.read_bytes(), invalid
    ).as_document()
    assert report["status"] == "invalid"
    assert report["issues"][0]["side"] == "after"
    assert report["changes"] == []
    assert report["counts"] == report["hashes"] == {}


@pytest.mark.parametrize("count", [128, 129])
@pytest.mark.parametrize("action", ["changed", "added", "removed"])
def test_change_limit_is_complete_or_unavailable_without_partial_report(count, action):
    before = proposal()
    before["people"] = [
        {"key": f"person-{number}", "label": "Fictional person"}
        for number in range(count)
    ]
    before["assignments"][0]["person_key"] = "person-0"
    after = copy.deepcopy(before)
    for row in after["people"]:
        row["label"] = "Revised fictional person"
    if action != "changed":
        before["assignments"] = after["assignments"] = []
        before["commitments"] = after["commitments"] = []
        if action == "added":
            before["people"] = []
        else:
            after["people"] = []
    assert validate_import_bytes(encoded(before)).status == "valid"
    report = import_comparison.compare_import_bytes(
        encoded(before), encoded(after)
    ).as_document()
    if count == 128:
        assert report["status"] == "compared"
        assert len(report["changes"]) == 128
        assert report["counts"]["people"][action] == 128
    else:
        assert report["status"] == "unavailable"
        assert report["issues"][0]["code"] == "too_many_changes"
        assert report["changes"] == []
        assert report["counts"] == report["hashes"] == {}


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["one"],
        ["one", "two", "PRIVATE_SENTINEL"],
        ["--PRIVATE_SENTINEL"],
        ["--sche"],
    ],
)
def test_argument_failures_never_echo_source_text(capsys, arguments):
    assert import_comparison.main(arguments) == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert "PRIVATE_SENTINEL" not in output.out
    assert json.loads(output.out)["issues"][0]["code"] == "invalid_arguments"


def test_cli_preserves_inputs_and_reports_both_unavailable_sides(tmp_path, capsys):
    before = tmp_path / "PRIVATE_BEFORE.json"
    after = tmp_path / "PRIVATE_AFTER.json"
    original = EXAMPLE.read_bytes()
    before.write_bytes(original)
    after.write_bytes(original)
    assert import_comparison.main([str(before), str(after)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "compared"
    assert before.read_bytes() == after.read_bytes() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        [before.name, after.name]
    )
    assert import_comparison.main([str(tmp_path), str(tmp_path / "missing")]) == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert str(tmp_path) not in output.out
    assert [row["side"] for row in json.loads(output.out)["issues"]] == [
        "before",
        "after",
    ]


def test_cli_reuses_regular_read_only_nonblocking_owner_boundary(monkeypatch, capsys):
    calls = []
    original_open = import_validation.os.open

    def opened(path, flags):
        calls.append(flags)
        return original_open(path, flags)

    monkeypatch.setattr(import_validation.os, "open", opened)
    assert import_comparison.main([str(EXAMPLE), str(EXAMPLE)]) == 0
    capsys.readouterr()
    assert len(calls) == 2
    assert all(
        flags & getattr(os, "O_NONBLOCK", 0) == getattr(os, "O_NONBLOCK", 0)
        for flags in calls
    )
    assert all(
        not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        for flags in calls
    )


def test_cli_invalid_file_and_help_exit_codes(tmp_path, capsys):
    path = tmp_path / "invalid.json"
    path.write_bytes(b"{")
    assert import_comparison.main([str(EXAMPLE), str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["issues"][0]["side"] == "after"
    with pytest.raises(SystemExit) as error:
        import_comparison.main(["--help"])
    assert error.value.code == 0
    assert "original regular" in capsys.readouterr().out


def test_fresh_interpreter_comparison_needs_no_application_network_or_writes():
    script = """
import importlib.abc, os, runpy, sys
class NoApplication(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'django', 'psycopg', 'sqlite3'}:
            raise AssertionError('Application or database import')
def guard(event, args):
    if event.startswith(('socket.', 'subprocess.', 'sqlite3.')):
        raise AssertionError('Network or process access')
    if event in {'os.remove', 'os.rename', 'os.mkdir', 'os.rmdir'}:
        raise AssertionError('File mutation')
    if event == 'open':
        flags = args[2] or 0
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise AssertionError('Write access')
sys.meta_path.insert(0, NoApplication())
sys.addaudithook(guard)
sys.argv = ['maru.workforce.import_comparison', sys.argv[1], sys.argv[1]]
runpy.run_module('maru.workforce.import_comparison', run_name='__main__')
"""
    result = subprocess.run(  # noqa: S603 - fixed script and fictional repository fixture
        [sys.executable, "-B", "-c", script, str(EXAMPLE)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout)["status"] == "compared"
