"""Validate repository-owned Markdown links, IDs, and UTF-8 text."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".pip-audit-cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tools",
    ".uv-cache",
    ".venv",
    "node_modules",
}
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
REQUIREMENT_PATTERN = re.compile(r"\*\*([A-Z]{3}-[0-9]{3})\b")
MOJIBAKE_MARKERS = ("â€”", "â”", "Ã", "�")


def markdown_files() -> list[Path]:
    """Return maintained Markdown files in stable path order.

    Returns
    -------
    list[Path]
        The maintained Markdown files in stable path order.
    """
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not EXCLUDED_PARTS.intersection(path.relative_to(ROOT).parts)
    )


def main() -> int:
    """Run the command-line entry point.

    Returns
    -------
    int
        The process exit status.
    """
    failures: list[str] = []
    files = markdown_files()

    for path in files:
        content = path.read_text(encoding="utf-8")
        failures.extend(
            f"{path.relative_to(ROOT)}: encoding marker {marker!r}"
            for marker in MOJIBAKE_MARKERS
            if marker in content
        )

        for match in LINK_PATTERN.finditer(content):
            target = match.group(1).strip().strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_text = unquote(target.split("#", maxsplit=1)[0])
            if not path_text:
                continue
            resolved = (path.parent / path_text).resolve()
            if not resolved.exists():
                failures.append(
                    f"{path.relative_to(ROOT)}: missing relative link {target}"
                )

    requirements_path = ROOT / "docs" / "product" / "requirements.md"
    requirements = REQUIREMENT_PATTERN.findall(
        requirements_path.read_text(encoding="utf-8")
    )
    duplicates = sorted(
        identifier
        for identifier in set(requirements)
        if requirements.count(identifier) > 1
    )
    if duplicates:
        failures.append(f"duplicate requirement identifiers: {', '.join(duplicates)}")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1

    print(
        f"Documentation valid: {len(files)} Markdown files, "
        f"{len(requirements)} unique requirement identifiers."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
