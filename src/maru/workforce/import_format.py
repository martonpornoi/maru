"""Validate file-local Workforce proposals without loading application state."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from collections.abc import Sequence

FORMAT = "maru.workforce-import"
VERSION = 1
PROFILE = "workforce_only@1"
MAX_BYTES = 1_048_576
MAX_DEPTH = 16
MAX_ISSUES = 64
MAX_ANCESTRY = 16
MAX_TEXT = 200
MAX_CAPACITY = 1024
MAX_INTEGER_DIGITS = 19
# JSON Schema uses search semantics; this end assertion also rejects a final
# newline, which a bare dollar anchor would allow in several regex engines.
KEY_PATTERN = r"^[a-z][a-z0-9_-]{0,63}(?![\s\S])"
INSTANT_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})(?![\s\S])"
)
TEXT_PATTERN = r"^[^\x00-\x1f\x7f-\x9f\ud800-\udfff]{1,200}(?![\s\S])"
ASSURANCE = (
    "Checks file format and internal consistency only. Identity, current scope, "
    "permissions, eligibility, Availability, approvals and live coverage were "
    "not checked. No Maru records were changed."
)
ROW_LIMITS = {
    "departments": 128,
    "positions": 512,
    "people": 2048,
    "assignments": 4096,
    "shifts": 1024,
    "commitments": 4096,
}
FIELDS = {
    "departments": {"key": "key", "name": "text", "parent_key": "nullable_key"},
    "positions": {"key": "key", "department_key": "key", "title": "text"},
    "people": {"key": "key", "label": "text"},
    "assignments": {"key": "key", "person_key": "key", "position_key": "key"},
    "shifts": {
        "key": "key",
        "position_key": "key",
        "starts_at": "instant",
        "ends_at": "instant",
        "capacity": "capacity",
    },
    "commitments": {"key": "key", "assignment_key": "key", "shift_key": "key"},
}
SCOPE_FIELDS = {"organization_key": "key", "edition_key": "key", "time_zone": "zone"}
MESSAGES = {
    "input_too_large": "The file exceeds the byte limit.",
    "invalid_encoding": "Use UTF-8 JSON without a byte-order mark.",
    "invalid_json": "The file is not a complete JSON document.",
    "duplicate_member": "A JSON object repeats a member.",
    "invalid_json_number": "Use bounded integer number tokens only.",
    "too_deep": "The JSON nesting exceeds the depth limit.",
    "invalid_document": "The document must be a JSON object.",
    "missing_field": "A required field is missing.",
    "unknown_field": "The object contains an unsupported field.",
    "unsupported_format": "Use the Workforce import-proposal format.",
    "unsupported_version": "The format version is not supported.",
    "unsupported_profile": "The declared profile is not supported.",
    "invalid_field": "The field does not match its documented type or bounds.",
    "too_many_records": "The section exceeds its record limit.",
    "duplicate_key": "A record key is repeated within this section.",
    "unknown_reference": "The referenced record is absent from this file.",
    "department_cycle": "Department parent references form a cycle.",
    "department_depth": "Department ancestry exceeds the depth limit.",
    "duplicate_assignment": "This person and Position proposal pair is repeated.",
    "duplicate_commitment": "This Assignment and Shift proposal pair is repeated.",
    "position_mismatch": "The proposed Assignment and Shift name different Positions.",
    "capacity_exceeded": "Proposed commitments exceed the declared Shift capacity.",
    "invalid_interval": "The Shift end must be after its start.",
    "time_zone_mismatch": "The instant's offset disagrees with the declared time zone.",
    "invalid_time_zone": "Use an available IANA time-zone name.",
    "unavailable_file": "A readable regular local file is required.",
    "invalid_arguments": "Supply one file or --schema; use --help for instructions.",
}


@dataclass(frozen=True, slots=True)
class ImportIssue:
    """Identify a fixed failure without retaining a supplied value.

    Attributes
    ----------
    code : str
        Code from the closed diagnostic vocabulary.
    location : str
        Root or a known section, zero-based row and known field pointer.
    """

    code: str
    location: str


@dataclass(frozen=True, slots=True)
class ImportValidationReport:
    """Describe file validation without granting import authority.

    Attributes
    ----------
    status : Literal["valid", "invalid", "unavailable"]
        Result of local validation or inability to read a selected file.
    issues : tuple[ImportIssue, ...]
        At most 64 minimized issues in deterministic traversal order.
    counts : tuple[tuple[str, int], ...]
        Section counts, populated only for a valid proposal.
    issues_truncated : bool
        Whether further issues were omitted after reaching the ceiling.
    """

    status: Literal["valid", "invalid", "unavailable"]
    issues: tuple[ImportIssue, ...]
    counts: tuple[tuple[str, int], ...] = ()
    issues_truncated: bool = False

    def as_document(self) -> dict[str, Any]:
        """Return a JSON-compatible report containing no source values.

        Returns
        -------
        dict[str, Any]
            Closed report, fixed explanations, optional counts and assurance.
        """
        return {
            "status": self.status,
            "counts": dict(self.counts) if self.status == "valid" else None,
            "issues": [
                {
                    "code": issue.code,
                    "location": issue.location,
                    "message": MESSAGES[issue.code],
                }
                for issue in self.issues
            ],
            "issues_truncated": self.issues_truncated,
            "assurance": ASSURANCE,
        }


class _FormatError(ValueError):
    """Carry a fixed decoder code without the original parser exception."""


class _Issues:
    """Accumulate bounded diagnostics while retaining a truthful truncation flag."""

    def __init__(self) -> None:
        self.values: list[ImportIssue] = []
        self.truncated = False

    def add(self, code: str, location: str) -> None:
        """Record one fixed issue or mark further diagnostics as truncated.

        Parameters
        ----------
        code : str
            Closed diagnostic code.
        location : str
            Pointer assembled exclusively from known fields and integer indices.
        """
        if len(self.values) < MAX_ISSUES:
            self.values.append(ImportIssue(code, location))
        else:
            self.truncated = True


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _FormatError("duplicate_member")
        result[key] = value
    return result


def _reject_number(_value: str) -> Any:
    raise _FormatError("invalid_json_number")


def _integer(value: str) -> int:
    if len(value.lstrip("-")) > MAX_INTEGER_DIGITS:
        raise _FormatError("invalid_json_number")
    return int(value)


def _check_depth(raw: bytes) -> None:
    depth = 0
    quoted = escaped = False
    for value in raw:
        if quoted:
            if escaped:
                escaped = False
            elif value == ord("\\"):
                escaped = True
            elif value == ord('"'):
                quoted = False
        elif value == ord('"'):
            quoted = True
        elif value in (ord("{"), ord("[")):
            depth += 1
            if depth > MAX_DEPTH:
                raise _FormatError("too_deep")
        elif value in (ord("}"), ord("]")):
            depth -= 1


def _decode(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_BYTES:
        raise _FormatError("input_too_large")
    _check_depth(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _FormatError("invalid_encoding") from None
    if text.startswith("\ufeff"):
        raise _FormatError("invalid_encoding")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_int=_integer,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except _FormatError:
        raise
    except (json.JSONDecodeError, RecursionError):
        raise _FormatError("invalid_json") from None
    if not isinstance(value, dict):
        raise _FormatError("invalid_document")
    return cast("dict[str, Any]", value)


def _instant(value: str) -> datetime | None:
    if not re.fullmatch(INSTANT_PATTERN, value):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _field_valid(value: Any, kind: str) -> bool:
    if kind == "capacity":
        return type(value) is int and 1 <= value <= MAX_CAPACITY
    if kind == "nullable_key" and value is None:
        return True
    if not isinstance(value, str):
        return False
    if kind in {"key", "nullable_key"}:
        return re.fullmatch(KEY_PATTERN, value) is not None
    if kind == "instant":
        return _instant(value) is not None
    return (
        re.fullmatch(TEXT_PATTERN, value) is not None
        and value == value.strip()
        and unicodedata.normalize("NFC", value) == value
    )


def _closed(
    value: dict[str, Any], fields: Sequence[str], location: str, issues: _Issues
) -> None:
    for name in fields:
        if name not in value:
            issues.add("missing_field", f"{location}/{name}")
    if set(value) - set(fields):
        issues.add("unknown_field", location or "/")


def _record(value: Any, fields: dict[str, str], location: str, issues: _Issues) -> None:
    if not isinstance(value, dict):
        issues.add("invalid_field", location)
        return
    _closed(value, tuple(fields), location, issues)
    for name, kind in fields.items():
        if name in value and not _field_valid(value[name], kind):
            issues.add("invalid_field", f"{location}/{name}")


def _structure(document: dict[str, Any], issues: _Issues) -> None:
    _closed(document, ("format", "version", "profile", "scope", *FIELDS), "", issues)
    for name, expected, code in (
        ("format", FORMAT, "unsupported_format"),
        ("version", VERSION, "unsupported_version"),
        ("profile", PROFILE, "unsupported_profile"),
    ):
        if name in document and (
            type(document[name]) is not type(expected) or document[name] != expected
        ):
            issues.add(code, f"/{name}")
    if "scope" in document:
        _record(document["scope"], SCOPE_FIELDS, "/scope", issues)
    for section, fields in FIELDS.items():
        if section not in document:
            continue
        rows = document[section]
        if not isinstance(rows, list):
            issues.add("invalid_field", f"/{section}")
        elif len(rows) > ROW_LIMITS[section]:
            issues.add("too_many_records", f"/{section}")
        else:
            for index, row in enumerate(rows):
                _record(row, fields, f"/{section}/{index}", issues)


def _indexes(document: dict[str, Any], issues: _Issues) -> dict[str, dict[str, Any]]:
    indexes: dict[str, dict[str, Any]] = {}
    for section in FIELDS:
        index: dict[str, Any] = {}
        for number, row in enumerate(document[section]):
            if row["key"] in index:
                issues.add("duplicate_key", f"/{section}/{number}/key")
            else:
                index[row["key"]] = row
        indexes[section] = index
    return indexes


def _references(
    document: dict[str, Any], indexes: dict[str, dict[str, Any]], issues: _Issues
) -> None:
    relations = (
        ("departments", "parent_key", "departments"),
        ("positions", "department_key", "departments"),
        ("assignments", "person_key", "people"),
        ("assignments", "position_key", "positions"),
        ("shifts", "position_key", "positions"),
        ("commitments", "assignment_key", "assignments"),
        ("commitments", "shift_key", "shifts"),
    )
    for section, field, target in relations:
        for number, row in enumerate(document[section]):
            reference = row[field]
            if reference is not None and reference not in indexes[target]:
                issues.add("unknown_reference", f"/{section}/{number}/{field}")


def _ancestry(document: dict[str, Any], index: dict[str, Any], issues: _Issues) -> None:
    for number, row in enumerate(document["departments"]):
        visited = {row["key"]}
        parent = row["parent_key"]
        while parent in index:
            if parent in visited:
                issues.add("department_cycle", f"/departments/{number}/parent_key")
                break
            if len(visited) >= MAX_ANCESTRY:
                issues.add("department_depth", f"/departments/{number}/parent_key")
                break
            visited.add(parent)
            parent = index[parent]["parent_key"]


def _unique_pairs(
    rows: list[Any], first: str, second: str, section: str, code: str, issues: _Issues
) -> None:
    seen: set[tuple[str, str]] = set()
    for number, row in enumerate(rows):
        pair = (row[first], row[second])
        if pair in seen:
            issues.add(code, f"/{section}/{number}")
        seen.add(pair)


def _commitments(
    document: dict[str, Any], indexes: dict[str, dict[str, Any]], issues: _Issues
) -> None:
    counts: Counter[str] = Counter()
    for number, row in enumerate(document["commitments"]):
        assignment = indexes["assignments"].get(row["assignment_key"])
        shift = indexes["shifts"].get(row["shift_key"])
        if shift is not None:
            counts[row["shift_key"]] += 1
        if (
            assignment is not None
            and shift is not None
            and assignment["position_key"] != shift["position_key"]
        ):
            issues.add("position_mismatch", f"/commitments/{number}/assignment_key")
    for number, row in enumerate(document["shifts"]):
        if counts[row["key"]] > row["capacity"]:
            issues.add("capacity_exceeded", f"/shifts/{number}/capacity")


def _times(document: dict[str, Any], issues: _Issues) -> None:
    try:
        zone = ZoneInfo(document["scope"]["time_zone"])
    except (ZoneInfoNotFoundError, ValueError, OSError):
        issues.add("invalid_time_zone", "/scope/time_zone")
        return
    for number, row in enumerate(document["shifts"]):
        start = cast("datetime", _instant(row["starts_at"]))
        end = cast("datetime", _instant(row["ends_at"]))
        try:
            if end.astimezone(UTC) <= start.astimezone(UTC):
                issues.add("invalid_interval", f"/shifts/{number}/ends_at")
            for name, instant in (("starts_at", start), ("ends_at", end)):
                if instant.astimezone(zone).utcoffset() != instant.utcoffset():
                    issues.add("time_zone_mismatch", f"/shifts/{number}/{name}")
        except (OverflowError, ValueError):
            issues.add("invalid_field", f"/shifts/{number}")


def validate_import_bytes(raw: bytes) -> ImportValidationReport:
    """Check a bounded proposal's format and file-local relationships.

    Parameters
    ----------
    raw : bytes
        Complete UTF-8 JSON proposal, never a rota archive or live command.

    Returns
    -------
    ImportValidationReport
        Deterministic minimized result; success carries no application authority.
    """
    try:
        document = _decode(raw)
    except _FormatError as error:
        return ImportValidationReport("invalid", (ImportIssue(str(error), "/"),))
    issues = _Issues()
    _structure(document, issues)
    if not issues.values:
        indexes = _indexes(document, issues)
        _references(document, indexes, issues)
        _ancestry(document, indexes["departments"], issues)
        _unique_pairs(
            document["assignments"],
            "person_key",
            "position_key",
            "assignments",
            "duplicate_assignment",
            issues,
        )
        _unique_pairs(
            document["commitments"],
            "assignment_key",
            "shift_key",
            "commitments",
            "duplicate_commitment",
            issues,
        )
        _commitments(document, indexes, issues)
        _times(document, issues)
    return ImportValidationReport(
        "invalid" if issues.values else "valid",
        tuple(issues.values),
        tuple((name, len(document[name])) for name in FIELDS)
        if not issues.values
        else (),
        issues.truncated,
    )


def _field_schema(kind: str) -> dict[str, Any]:
    shapes: dict[str, dict[str, Any]] = {
        "key": {"type": "string", "pattern": KEY_PATTERN},
        "nullable_key": {"type": ["string", "null"], "pattern": KEY_PATTERN},
        "text": {"type": "string", "pattern": TEXT_PATTERN},
        "instant": {
            "type": "string",
            "pattern": INSTANT_PATTERN,
            "format": "date-time",
        },
        "capacity": {"type": "integer", "minimum": 1, "maximum": MAX_CAPACITY},
        "zone": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT},
    }
    return shapes[kind]


def import_schema() -> dict[str, Any]:
    """Return the code-owned closed structural schema without fetching resources.

    Returns
    -------
    dict[str, Any]
        JSON Schema 2020-12; references, NFC, token spelling and time-zone
        consistency additionally require the normative offline validator.
    """

    def closed(fields: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": fields,
            "required": list(fields),
            "additionalProperties": False,
        }

    properties: dict[str, Any] = {
        "format": {"const": FORMAT},
        "version": {"type": "integer", "const": VERSION},
        "profile": {"const": PROFILE},
        "scope": closed(
            {name: _field_schema(kind) for name, kind in SCOPE_FIELDS.items()}
        ),
    }
    for name, fields in FIELDS.items():
        properties[name] = {
            "type": "array",
            "maxItems": ROW_LIMITS[name],
            "items": closed(
                {field: _field_schema(kind) for field, kind in fields.items()}
            ),
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:maru:workforce-import:1",
        "title": "Workforce import proposals version 1",
        **closed(properties),
    }
