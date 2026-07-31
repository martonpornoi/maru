"""Explicit local-only adapter for the public Awoostria volunteer roster."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

AWOOSTRIA_ROSTER_URL = "https://awoostria.at/about-us/our-volunteers"
MINIMUM_ROSTER_ACCOUNTS = 2
NON_PERSON_HEADINGS = frozenset(
    {
        "this department is recruiting!",
        "open positions",
    }
)


@dataclass(frozen=True, slots=True)
class PublicRosterAssignment:
    username: str
    role: str


@dataclass(frozen=True, slots=True)
class PublicRosterDepartment:
    name: str
    description: str
    assignments: tuple[PublicRosterAssignment, ...]


@dataclass(slots=True)
class _MutableDepartment:
    name: str
    description_parts: list[str] = field(default_factory=list)
    assignments: list[PublicRosterAssignment] = field(default_factory=list)


class _RosterParser(HTMLParser):
    """Parse semantic headings without retaining links, avatars, or contacts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.main_depth = 0
        self.capture_tag: str | None = None
        self.capture_depth = 0
        self.capture_parts: list[str] = []
        self.current: _MutableDepartment | None = None
        self.pending_username: str | None = None
        self.departments: list[_MutableDepartment] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag == "main":
            self.main_depth += 1
        if self.capture_tag is not None:
            self.capture_depth += 1
            return
        if self.main_depth and tag in {"h2", "h3", "p"}:
            self.capture_tag = tag
            self.capture_depth = 0
            self.capture_parts = []

    def handle_data(self, data: str) -> None:
        if self.capture_tag is not None:
            self.capture_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.capture_tag is not None:
            if tag == self.capture_tag and self.capture_depth == 0:
                captured_tag = self.capture_tag
                text = " ".join("".join(self.capture_parts).split())
                self.capture_tag = None
                self.capture_parts = []
                self._captured(captured_tag, text)
            elif self.capture_depth:
                self.capture_depth -= 1
        if tag == "main" and self.main_depth:
            self.main_depth -= 1

    def _captured(self, tag: str, text: str) -> None:
        if not text:
            return
        if tag == "h2":
            self.current = _MutableDepartment(name=text)
            self.departments.append(self.current)
            self.pending_username = None
            return
        if self.current is None:
            return
        if tag == "h3":
            self.pending_username = (
                None if text.casefold() in NON_PERSON_HEADINGS else text
            )
            return
        if tag == "p" and self.pending_username:
            roles = [item.strip() for item in text.split("|") if item.strip()]
            self.current.assignments.extend(
                PublicRosterAssignment(
                    username=self.pending_username,
                    role=role,
                )
                for role in roles
            )
            self.pending_username = None
        elif tag == "p" and not self.current.assignments:
            self.current.description_parts.append(text)


def parse_public_roster(html: str) -> tuple[PublicRosterDepartment, ...]:
    parser = _RosterParser()
    parser.feed(html)
    departments = tuple(
        PublicRosterDepartment(
            name=item.name,
            description=" ".join(item.description_parts),
            assignments=tuple(item.assignments),
        )
        for item in parser.departments
        if item.assignments
    )
    if not departments:
        raise ValueError("The public roster contained no recognizable departments.")
    usernames = {
        assignment.username.casefold()
        for department in departments
        for assignment in department.assignments
    }
    if len(usernames) < MINIMUM_ROSTER_ACCOUNTS:
        raise ValueError("The public roster contained too few distinct usernames.")
    return departments


def load_public_roster_file(path: Path) -> tuple[PublicRosterDepartment, ...]:
    return parse_public_roster(path.read_text(encoding="utf-8"))


def fetch_awoostria_roster(
    url: str = AWOOSTRIA_ROSTER_URL,
) -> tuple[PublicRosterDepartment, ...]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "awoostria.at",
        "www.awoostria.at",
    }:
        raise ValueError("The rehearsal roster URL must be HTTPS on awoostria.at.")
    request = Request(  # noqa: S310
        url,
        headers={
            "User-Agent": (
                "Maru local rehearsal importer/1.0 "
                "(public volunteer roles; no contact or image import)"
            )
        },
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310
        html = response.read().decode("utf-8")
    return parse_public_roster(html)
