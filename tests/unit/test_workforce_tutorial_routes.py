"""Check that the maintained Workforce tutorial names actual mounted routes."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

import pytest
from django.urls import resolve, reverse

from maru.events.models import WorkforceAdoptionSetupReceipt

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs/operations/workforce-only-rehearsal.md"
TEXT = GUIDE.read_text(encoding="utf-8")
ROUTES = re.findall(
    r"^\| `([a-z-]+)` \| `(/[^`]+)` \|$",
    TEXT,
    flags=re.MULTILINE,
)
VALUES = {
    "organization_slug": "synthetic-cedar-volunteer-team",
    "series_slug": "marucon-cedar",
    "edition_slug": "marucon-cedar-rehearsal",
    "edition_id": UUID("38ec713d-37e9-4b1c-a1ac-403b3cef2c4a"),
}


def test_tutorial_route_reference_cannot_silently_disappear() -> None:
    assert len(ROUTES) == 11
    assert len({name for name, _path in ROUTES}) == len(ROUTES)


@pytest.mark.parametrize(("name", "documented"), ROUTES, ids=[r[0] for r in ROUTES])
def test_tutorial_route_matches_current_mounted_owner(
    name: str, documented: str
) -> None:
    parameters = re.findall(r"<([a-z_]+)>", documented)
    kwargs = {key: VALUES[key] for key in parameters}
    expected = documented
    for key, value in kwargs.items():
        expected = expected.replace(f"<{key}>", str(value))
    actual = reverse(name, kwargs=kwargs, urlconf="maru.urls")
    assert actual == expected
    assert resolve(actual, urlconf="maru.urls").url_name == name


def test_tutorial_covers_twenty_ordered_steps_with_explicit_evidence() -> None:
    rows = re.findall(r"^\| (\d+)\. ([^\n]+) \|$", TEXT, flags=re.MULTILINE)
    assert [int(number) for number, _ in rows] == list(range(1, 21))
    for _number, row in rows:
        cells = row.split(" | ")
        assert len(cells) == 4
        assert all(cell.strip() for cell in cells)
    assert str(WorkforceAdoptionSetupReceipt.Mode.NEW_FOUNDATION.label) in TEXT


@pytest.mark.parametrize(
    ("step", "actor", "action"),
    [
        (3, "A, then B", "Accept invitation"),
        (4, "Platform administrator", "activate"),
        (10, "A;", "Record proposal"),
        (11, "B;", "Approve and activate"),
        (12, "Volunteer;", "Save private draft"),
        (13, "Volunteer;", "Share with organizers"),
        (16, "Volunteer;", "Claim this Shift"),
        (17, "B;", "Confirm commitment"),
        (19, "A;", "Complete Shift"),
        (20, "B;", "End assignment and revoke authority"),
    ],
)
def test_tutorial_retains_independent_and_person_owned_handoffs(
    step: int, actor: str, action: str
) -> None:
    row = re.search(rf"^\| {step}\. [^\n]+$", TEXT, flags=re.MULTILINE)
    assert row is not None
    _title, start, instruction, _expected = row.group().strip("| ").split(" | ")
    assert start.startswith(actor)
    assert action in instruction


def test_tutorial_keeps_current_entry_links_and_historical_boundary() -> None:
    for path in (
        ROOT / "README.md",
        ROOT / "docs/operations/index.md",
        ROOT / "docs/operations/workforce-only-adoption-and-recovery.md",
        ROOT / "docs/project/CURRENT.md",
    ):
        assert "workforce-only-rehearsal.md" in path.read_text(encoding="utf-8")
    historical = (ROOT / "docs/operations/maru-hands-on-tutorial.md").read_text(
        encoding="utf-8"
    )
    assert "Historical stopping point" in historical
    assert "workforce-only-rehearsal.md" in historical
