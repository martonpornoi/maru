#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys


def main() -> None:
    """Run the command-line entry point.

    Raises
    ------
    ImportError
        If Django cannot be imported in the active environment.
    """
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE",
        os.environ.get("MARU_SETTINGS_MODULE", "maru.settings.local"),
    )

    try:
        from django.core.management import execute_from_command_line
    except ImportError as error:
        raise ImportError(
            "Django is unavailable. Run `uv sync --all-groups` first."
        ) from error

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
