"""Portable rota interchange, escaping and bounded package contracts."""

from __future__ import annotations

import hashlib
import io
import json
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile
from zoneinfo import ZoneInfo

import pytest
from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from maru.workforce import rota
from maru.workforce.rota_schema import rota_schema

SCOPE = {
    "organization_id": "00000000-0000-4000-8000-000000000001",
    "series_id": "00000000-0000-4000-8000-000000000002",
    "edition_id": "00000000-0000-4000-8000-000000000003",
    "edition_name": "Fictional <script>alert('edition')</script> convention",
    "edition_version": 1,
    "edition_lifecycle": "preparing",
    "starts_on": "2030-10-26",
    "ends_on": "2030-10-28",
    "time_zone": "Europe/Budapest",
    "profile_code": "workforce_only",
    "profile_version": 1,
}


@pytest.fixture
def payload():
    return {
        "format": "maru.workforce-rota",
        "version": 1,
        "observed_at": "2030-10-26T12:00:00+00:00",
        "scope": deepcopy(SCOPE),
        "limitations": list(rota.LIMITATIONS),
        "shifts": [],
    }


def test_package_is_self_contained_schema_valid_and_hashes_every_member(payload):
    snapshot = rota.RotaSnapshot(SimpleNamespace(), payload)
    html = render_to_string("workforce/rota.html", {"rota": payload})
    data = rota.rota_package(snapshot=snapshot, printable_html=html)
    assert data == rota.rota_package(snapshot=snapshot, printable_html=html)
    with ZipFile(io.BytesIO(data)) as archive:
        assert set(archive.namelist()) == {
            "rota.json",
            "rota.html",
            "schema.json",
            "README.txt",
            "manifest.json",
        }
        assert archive.testzip() is None
        schema = json.loads(archive.read("schema.json"))
        result = json.loads(archive.read("rota.json"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)
        assert result == payload
        assert archive.read("rota.html").decode() == html
        manifest = json.loads(archive.read("manifest.json"))
        assert set(manifest["files"]) == set(archive.namelist()) - {"manifest.json"}
        for name, entry in manifest["files"].items():
            content = archive.read(name)
            assert len(content) == entry["bytes"]
            assert hashlib.sha256(content).hexdigest() == entry["sha256"]
        assert b"not authenticity" in archive.read("README.txt")


def test_schema_rejects_unknown_fields_versions_profiles_and_invalid_scope(payload):
    validator = Draft202012Validator(rota_schema(), format_checker=FormatChecker())
    for path, value in (
        (("version",), 2),
        (("private_notes",), "must not leak"),
        (("scope", "profile_code"), "full_convention"),
        (("scope", "edition_id"), "not-a-uuid"),
    ):
        changed = deepcopy(payload)
        node = changed
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        with pytest.raises(ValidationError):
            validator.validate(changed)


def test_print_copy_escapes_labels_and_has_no_remote_resources_or_scripts(payload):
    html = render_to_string("workforce/rota.html", {"rota": payload})
    page = BeautifulSoup(html, "html.parser")
    assert len(page.select("main")) == len(page.select("h1")) == 1
    assert not page.select("script, img, iframe, link, form, nav, a")
    assert "<script>alert('edition')</script>" in page.get_text()
    assert "No Shift demand" in page.get_text()
    assert "does not establish staffing readiness" in page.get_text()
    assert "Private Availability windows" in page.get_text()
    assert "@media print" in html


def test_package_refuses_complete_uncompressed_overflow(payload, monkeypatch):
    snapshot = rota.RotaSnapshot(SimpleNamespace(), payload)
    monkeypatch.setattr(rota, "MAX_ROTA_BYTES", 32)
    with pytest.raises(rota.RotaUnavailableError):
        rota.rota_package(snapshot=snapshot, printable_html="x" * 33)


def test_utc_instant_rejects_naive_and_retains_offset_semantics():
    assert (
        rota._instant(datetime(2030, 10, 27, 1, tzinfo=UTC))
        == "2030-10-27T01:00:00+00:00"
    )
    with pytest.raises(rota.RotaUnavailableError):
        rota._instant(datetime(2030, 10, 27, 1, tzinfo=UTC).replace(tzinfo=None))


def test_offset_bearing_local_times_preserve_the_repeated_dst_hour_and_date():
    def item(starts_at, ends_at):
        demand = SimpleNamespace(
            id=uuid4(),
            command_version=1,
            position_id=uuid4(),
            title="Night desk",
            status="open",
            starts_at=starts_at,
            ends_at=ends_at,
            location_label="Night desk",
            briefing="Receive the handover.",
            supervision_note="Contact the current lead.",
            required_headcount=1,
            break_minutes=0,
            minimum_rest_minutes=60,
        )
        return SimpleNamespace(
            demand=demand,
            department_name="Operations",
            position_title="Night desk",
            claimed_count=0,
            confirmed_count=0,
            remaining_count=1,
            commitments=(),
        )

    before_fold = datetime.fromisoformat("2030-10-27T00:30:00+00:00")
    after_fold = datetime.fromisoformat("2030-10-27T01:30:00+00:00")
    converted = rota._shift(item(before_fold, after_fold), ZoneInfo("Europe/Budapest"))
    assert converted["local_starts_at"] == "2030-10-27T02:30:00+02:00"
    assert converted["local_ends_at"] == "2030-10-27T02:30:00+01:00"
    assert converted["starts_at"] != converted["ends_at"]
    overnight = rota._shift(
        item(datetime.fromisoformat("2030-10-26T21:00:00+00:00"), after_fold),
        ZoneInfo("Europe/Budapest"),
    )
    assert overnight["local_starts_at"].startswith("2030-10-26")
    assert overnight["local_ends_at"].startswith("2030-10-27")
