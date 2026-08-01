from pathlib import Path

import pytest

from maru.demo import public_roster

ROSTER_HTML = """
<h2>Outside main is ignored</h2>
<main>
  <h3>Person before a department is ignored</h3>
  <p>Also ignored.</p>
  <h2><span>Executive Board</span></h2>
  <p>Accountable <em>organizer</em> board.</p>
  <article><h3><span>ChairFox</span></h3><p>Chairman | Director</p></article>
  <aside><h3>This department is recruiting!</h3><p>Open positions</p></aside>
  <h2>Helpers</h2>
  <p>Friendly helpers.</p>
  <article><h3>HelperHare</h3><p>Volunteer</p></article>
  <h2> </h2>
</main>
"""


def test_semantic_roster_parser_minimizes_and_splits_public_roles() -> None:
    departments = public_roster.parse_public_roster(ROSTER_HTML)

    assert [item.name for item in departments] == ["Executive Board", "Helpers"]
    assert departments[0].description == "Accountable organizer board."
    assert [
        (assignment.username, assignment.role)
        for assignment in departments[0].assignments
    ] == [
        ("ChairFox", "Chairman"),
        ("ChairFox", "Director"),
    ]
    assert departments[1].assignments[0].username == "HelperHare"
    assert "recruiting" not in str(departments).casefold()


def test_roster_parser_rejects_empty_or_single_person_sources() -> None:
    with pytest.raises(ValueError, match="no recognizable departments"):
        public_roster.parse_public_roster("<main><h2>Board</h2><p>Empty</p></main>")

    with pytest.raises(ValueError, match="too few distinct usernames"):
        public_roster.parse_public_roster(
            "<main><h2>Board</h2><h3>OnlyOne</h3><p>Chair</p></main>"
        )


def test_roster_file_stays_local_and_network_adapter_is_retired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roster_path = tmp_path / "roster.html"
    roster_path.write_text(ROSTER_HTML, encoding="utf-8")
    assert len(public_roster.load_public_roster_file(roster_path)) == 2

    network_called = False

    def forbidden_urlopen(*args: object, **kwargs: object) -> None:
        del args, kwargs
        nonlocal network_called
        network_called = True
        raise AssertionError("The retired adapter attempted network I/O.")

    monkeypatch.setattr("urllib.request.urlopen", forbidden_urlopen)

    for url in (
        public_roster.AWOOSTRIA_ROSTER_URL,
        "http://awoostria.at/about-us/our-volunteers",
        "https://example.invalid/our-volunteers",
    ):
        with pytest.raises(
            public_roster.PublicRosterNetworkImportRetiredError
        ) as caught:
            public_roster.fetch_awoostria_roster(url)
        assert str(caught.value) == public_roster.NETWORK_IMPORT_RETIRED_MESSAGE

    assert network_called is False
