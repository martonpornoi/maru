"""Compare validated Workforce proposals offline without disclosing their values."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from maru.workforce.import_format import (
    FIELDS,
    MAX_ISSUES,
    MESSAGES,
    validate_import_bytes,
)
from maru.workforce.import_validation import (
    _ArgumentsUnavailableError,
    _Parser,
    _read_file,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

MAX_CHANGES = 128
SIDES: tuple[Literal["before", "after"], ...] = ("before", "after")
ASSURANCE = (
    "Compares two internally valid file-local proposals only. Keys do not identify "
    "live records. Original-byte hashes do not establish authenticity, authority, "
    "approval or freshness. No Maru records or input files were changed."
)
COMPARISON_MESSAGES = {
    "incompatible_scope": "Both proposals must declare exactly the same scope.",
    "too_many_changes": "The comparison exceeds the complete-report change limit.",
    "invalid_arguments": "Supply before and after files; use --help for instructions.",
}


@dataclass(frozen=True, slots=True)
class ComparisonIssue:
    """Locate a fixed problem without retaining input values or paths.

    Attributes
    ----------
    side : Literal["before", "after", "comparison"]
        Input side or comparison-level failure.
    code : str
        Closed validator or comparison diagnostic code.
    location : str
        Root or a validator-owned known-field pointer.
    """

    side: Literal["before", "after", "comparison"]
    code: str
    location: str = "/"


@dataclass(frozen=True, slots=True)
class ProposalChange:
    """Identify a changed row by position and known fields, never by values.

    Attributes
    ----------
    section : str
        One of the six code-owned proposal sections.
    action : Literal["added", "removed", "changed"]
        File-local key addition, removal or retained-key field change.
    before_row : int | None
        Zero-based original row, absent for additions.
    after_row : int | None
        Zero-based revised row, absent for removals.
    fields : tuple[str, ...]
        Changed known field names, empty for whole-row additions/removals.
    """

    section: str
    action: Literal["added", "removed", "changed"]
    before_row: int | None
    after_row: int | None
    fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ImportComparisonReport:
    """Return a complete minimized comparison or a fail-closed diagnosis.

    Attributes
    ----------
    status : Literal["compared", "invalid", "unavailable"]
        Complete comparison, invalid inputs/scope or unavailable result.
    issues : tuple[ComparisonIssue, ...]
        At most 64 fixed issues; no input text or parser errors.
    issues_truncated : bool
        Whether additional input issues were omitted.
    changes : tuple[ProposalChange, ...]
        At most 128 complete changes, populated only on success.
    counts : tuple[tuple[str, int, int, int], ...]
        Section and added/removed/changed counts, only on success.
    hashes : tuple[tuple[str, str], ...]
        SHA256 of each original byte input, only on success.
    """

    status: Literal["compared", "invalid", "unavailable"]
    issues: tuple[ComparisonIssue, ...] = ()
    issues_truncated: bool = False
    changes: tuple[ProposalChange, ...] = ()
    counts: tuple[tuple[str, int, int, int], ...] = ()
    hashes: tuple[tuple[str, str], ...] = ()

    def as_document(self) -> dict[str, Any]:
        """Render the bounded report using fixed keys and explanations.

        Returns
        -------
        dict[str, Any]
            JSON-compatible report without source values, aliases or paths.
        """
        return {
            "status": self.status,
            "issues": [
                {
                    "side": issue.side,
                    "code": issue.code,
                    "location": issue.location,
                    "message": COMPARISON_MESSAGES.get(issue.code)
                    or MESSAGES[issue.code],
                }
                for issue in self.issues
            ],
            "issues_truncated": self.issues_truncated,
            "changes": [
                {
                    "section": change.section,
                    "action": change.action,
                    "before_row": change.before_row,
                    "after_row": change.after_row,
                    "fields": list(change.fields),
                }
                for change in self.changes
            ],
            "counts": {
                section: {"added": added, "removed": removed, "changed": changed}
                for section, added, removed, changed in self.counts
            },
            "hashes": dict(self.hashes),
            "assurance": ASSURANCE,
        }


def _changes(
    before: dict[str, Any], after: dict[str, Any]
) -> tuple[ProposalChange, ...] | None:
    changes: list[ProposalChange] = []
    for section, fields in FIELDS.items():
        original = {
            row["key"]: (number, row) for number, row in enumerate(before[section])
        }
        revised = {
            row["key"]: (number, row) for number, row in enumerate(after[section])
        }
        for key, (before_row, row) in original.items():
            if key not in revised:
                changes.append(ProposalChange(section, "removed", before_row, None))
            else:
                after_row, new = revised[key]
                changed = tuple(
                    name for name in fields if name != "key" and row[name] != new[name]
                )
                if changed:
                    changes.append(
                        ProposalChange(
                            section, "changed", before_row, after_row, changed
                        )
                    )
            if len(changes) > MAX_CHANGES:
                return None
        for key, (after_row, _) in revised.items():
            if key not in original:
                changes.append(ProposalChange(section, "added", None, after_row))
                if len(changes) > MAX_CHANGES:
                    return None
    return tuple(changes)


def compare_import_bytes(before: bytes, after: bytes) -> ImportComparisonReport:
    """Validate both inputs before comparing exact file-local field values.

    Parameters
    ----------
    before : bytes
        Complete original proposal, subject to the existing 1 MiB limit.
    after : bytes
        Complete revised proposal under the same validated scope.

    Returns
    -------
    ImportComparisonReport
        Complete bounded changes and byte hashes, or issues with no partial data.
    """
    reports = (validate_import_bytes(before), validate_import_bytes(after))
    issues = tuple(
        ComparisonIssue(side, issue.code, issue.location)
        for side, report in zip(SIDES, reports, strict=True)
        for issue in report.issues
    )
    if issues:
        return ImportComparisonReport(
            "invalid",
            issues[:MAX_ISSUES],
            len(issues) > MAX_ISSUES
            or any(report.issues_truncated for report in reports),
        )
    # Only the already validated immutable bytes reach the standard decoder.
    original, revised = json.loads(before), json.loads(after)
    if original["scope"] != revised["scope"]:
        return ImportComparisonReport(
            "invalid", (ComparisonIssue("comparison", "incompatible_scope", "/scope"),)
        )
    changes = _changes(original, revised)
    if changes is None:
        return ImportComparisonReport(
            "unavailable", (ComparisonIssue("comparison", "too_many_changes"),)
        )
    return ImportComparisonReport(
        "compared",
        changes=changes,
        counts=tuple(
            (
                section,
                sum(
                    change.section == section and change.action == "added"
                    for change in changes
                ),
                sum(
                    change.section == section and change.action == "removed"
                    for change in changes
                ),
                sum(
                    change.section == section and change.action == "changed"
                    for change in changes
                ),
            )
            for section in FIELDS
        ),
        hashes=(
            ("before_sha256", hashlib.sha256(before).hexdigest()),
            ("after_sha256", hashlib.sha256(after).hexdigest()),
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Read two bounded regular files and print a minimized JSON comparison.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        Explicit arguments, or ``None`` for the process arguments.

    Returns
    -------
    int
        Zero for complete comparison, one for invalid input/scope, two for
        unavailable input, arguments or change limit. Help exits with zero.
    """
    parser = _Parser(
        prog="python -m maru.workforce.import_comparison",
        description=__doc__,
        allow_abbrev=False,
    )
    parser.add_argument(
        "before", type=Path, help="original regular UTF-8 proposal file"
    )
    parser.add_argument("after", type=Path, help="revised regular UTF-8 proposal file")
    try:
        arguments = parser.parse_args(argv)
    except _ArgumentsUnavailableError:
        report = ImportComparisonReport(
            "unavailable", (ComparisonIssue("comparison", "invalid_arguments"),)
        )
    else:
        files: list[bytes] = []
        issues: list[ComparisonIssue] = []
        for side, path in zip(SIDES, (arguments.before, arguments.after), strict=True):
            try:
                files.append(_read_file(path))
            except (OSError, ValueError):
                issues.append(ComparisonIssue(side, "unavailable_file"))
        report = (
            ImportComparisonReport("unavailable", tuple(issues))
            if issues
            else compare_import_bytes(*files)
        )
    sys.stdout.write(json.dumps(report.as_document(), indent=2) + "\n")
    return {"compared": 0, "invalid": 1, "unavailable": 2}[report.status]


if __name__ == "__main__":
    raise SystemExit(main())
