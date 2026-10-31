"""Check a local Workforce proposal file and print a minimized JSON report."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING

from maru.workforce.import_format import (
    MAX_BYTES,
    ImportIssue,
    ImportValidationReport,
    import_schema,
    validate_import_bytes,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import NoReturn


class _ArgumentsUnavailableError(ValueError):
    """Refuse arguments without retaining their source text."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        """Refuse arguments without printing their rejected values.

        Parameters
        ----------
        message : str
            Parser detail discarded to preserve minimized output.

        Raises
        ------
        _ArgumentsUnavailableError
            Always, with no source values attached.
        """
        del message
        raise _ArgumentsUnavailableError


def _read_file(path: Path) -> bytes:
    normalized = str(path).replace("\\", "/")
    if (
        normalized.startswith("//")
        or ":" in path.name
        or PureWindowsPath(path).is_reserved()
    ):
        raise OSError("unavailable_file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise OSError("unavailable_file")
        return stream.read(MAX_BYTES + 1)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate one file or emit the code-owned schema without app startup.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        Explicit arguments, or ``None`` for process arguments.

    Returns
    -------
    int
        Zero for valid/schema output, one for invalid content, two for unavailable
        input or arguments. Standard ``--help`` exits with zero.
    """
    parser = _Parser(
        prog="python -m maru.workforce.import_validation",
        description=__doc__,
        allow_abbrev=False,
    )
    parser.add_argument(
        "source", nargs="?", type=Path, help="regular UTF-8 proposal file"
    )
    parser.add_argument(
        "--schema", action="store_true", help="print the version-one structural schema"
    )
    try:
        arguments = parser.parse_args(argv)
        if arguments.schema == (arguments.source is not None):
            parser.error("")
    except _ArgumentsUnavailableError:
        report = ImportValidationReport(
            "unavailable", (ImportIssue("invalid_arguments", "/"),)
        )
        sys.stdout.write(json.dumps(report.as_document(), indent=2) + "\n")
        return 2
    if arguments.schema:
        sys.stdout.write(json.dumps(import_schema(), indent=2) + "\n")
        return 0
    try:
        raw = _read_file(arguments.source)
    except (OSError, ValueError):
        report = ImportValidationReport(
            "unavailable", (ImportIssue("unavailable_file", "/"),)
        )
        exit_code = 2
    else:
        report = validate_import_bytes(raw)
        exit_code = 0 if report.status == "valid" else 1
    sys.stdout.write(json.dumps(report.as_document(), indent=2) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
