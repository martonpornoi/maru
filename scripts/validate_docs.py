"""Validate maintained documentation and ethical example-data boundaries."""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".hypothesis",
    ".local-ci",
    ".mypy_cache",
    ".pip-audit-cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tools",
    ".uv-cache",
    ".venv",
    "_build",
    "build",
    "dist",
    "node_modules",
}
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
REQUIREMENT_PATTERN = re.compile(r"\*\*([A-Z]{3}-[0-9]{3})\b")
MOJIBAKE_MARKERS = ("â€”", "â”", "Ã", "�")
TOCTREE_START = "```{toctree}"
TOCTREE_END = "```"
TOCTREE_TITLE_PATTERN = re.compile(r".*<([^<>]+)>$")
ROOT_HUB_DOCNAMES = (
    "start-here/index",
    "product/index",
    "architecture/index",
    "development/index",
    "operations/index",
    "reference/index",
)
ARCHIVE_DOCNAME_PREFIXES = ("architecture/decisions/", "checkpoints/")
PROHIBITED_CONVENTION_NAME_FINGERPRINTS = frozenset(
    {
        "1cac428d0af21a99d5b05111a23cc57a1186cb3dd72e2a86cbc0a36b471eb273",
        "a0cbed68dccf26f396985feb3c6240b46a6e75027f412318ecdfd3139bd01b85",
        "ad2867305735bb59207c26796804eb1535c878e83e1ce60ca2bac4552d0750f1",
        "b78933a51425a7c8422a0c38f5f18d6633bdd21e65dead30b640e97affc23ab3",
    }
)
CONVENTION_NAME_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9]*")
URL_PATTERN = re.compile(r"https?://[^\s<>()\[\]\"']+", re.IGNORECASE)
LIVE_PERSON_PATH_SEGMENTS = frozenset(
    {
        "crew",
        "open-positions",
        "our-volunteers",
        "recruitment",
        "roster",
        "staff",
        "team",
        "teams",
        "volunteer",
        "volunteers",
    }
)
RESERVED_EXAMPLE_HOSTS = frozenset({"example.com", "example.net", "example.org"})
POLICY_CONTENT_ROOTS = (
    Path("frontends"),
    Path("openapi.yaml"),
    Path("scripts"),
    Path("src"),
    Path("tests"),
)
POLICY_CONTENT_SUFFIXES = frozenset(
    {
        ".html",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".ps1",
        ".py",
        ".sql",
        ".svg",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
)
POLICY_DEFINITION_PATH = Path("scripts/validate_docs.py")


def markdown_files(root: Path = ROOT) -> list[Path]:
    """Return maintained Markdown files in stable path order.

    Parameters
    ----------
    root : Path, default=ROOT
        The repository root to inspect.

    Returns
    -------
    list[Path]
        The maintained Markdown files in stable path order.
    """
    files: list[Path] = []
    for directory, directories, filenames in os.walk(root):
        directories[:] = [name for name in directories if name not in EXCLUDED_PARTS]
        files.extend(
            Path(directory) / filename
            for filename in filenames
            if Path(filename).suffix.lower() == ".md"
        )
    return sorted(files)


def _toctrees(path: Path) -> list[tuple[frozenset[str], tuple[str, ...]]]:
    """Parse MyST toctree options and entries from one Markdown document.

    Parameters
    ----------
    path : Path
        The maintained Markdown document to parse.

    Returns
    -------
    list[tuple[frozenset[str], tuple[str, ...]]]
        Each toctree's normalized option names and ordered raw entries.
    """
    blocks: list[tuple[frozenset[str], tuple[str, ...]]] = []
    options: set[str] = set()
    entries: list[str] = []
    in_toctree = False

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not in_toctree:
            if line == TOCTREE_START:
                in_toctree = True
                options = set()
                entries = []
            continue
        if line == TOCTREE_END:
            blocks.append((frozenset(options), tuple(entries)))
            in_toctree = False
            continue
        if line.startswith(":") and ":" in line[1:]:
            option_name = line[1:].split(":", maxsplit=1)[0].strip().lower()
            options.add(option_name)
        elif line and not line.startswith("#"):
            entries.append(line)

    return blocks


def _entry_target(entry: str) -> str:
    """Return the document target from one optional-title toctree entry.

    Parameters
    ----------
    entry : str
        The raw MyST toctree entry.

    Returns
    -------
    str
        The target document name or external reference.
    """
    titled = TOCTREE_TITLE_PATTERN.fullmatch(entry)
    target = titled.group(1) if titled else entry
    return target.strip().split("#", maxsplit=1)[0]


def _normalized_docname(source: Path, docs_root: Path, target: str) -> str | None:
    """Resolve one explicit toctree target to a source document name.

    Parameters
    ----------
    source : Path
        The Markdown document containing the toctree.
    docs_root : Path
        The Sphinx source directory.
    target : str
        The raw target document name.

    Returns
    -------
    str | None
        The normalized source-relative document name, or ``None`` when the
        target is external or leaves the source directory.
    """
    if not target or target == "self" or "://" in target:
        return None
    relative = Path(target.lstrip("/"))
    candidate = (
        docs_root / relative if target.startswith("/") else source.parent / relative
    )
    try:
        resolved = candidate.resolve().relative_to(docs_root.resolve())
    except ValueError:
        return None
    if resolved.suffix == ".md":
        resolved = resolved.with_suffix("")
    return resolved.as_posix()


def _source_path(docs_root: Path, docname: str) -> Path | None:
    """Return the maintained source path for one normalized document name.

    Parameters
    ----------
    docs_root : Path
        The Sphinx source directory.
    docname : str
        The source-relative extensionless document name.

    Returns
    -------
    Path | None
        The existing Markdown source, or ``None`` for generated or missing
        documents.
    """
    candidate = docs_root / f"{docname}.md"
    if candidate.is_file():
        return candidate.resolve()
    index_candidate = docs_root / docname / "index.md"
    if index_candidate.is_file():
        return index_candidate.resolve()
    return None


def _glob_targets(source: Path, docs_root: Path, target: str) -> set[Path]:
    """Expand one source-contained MyST glob target to Markdown paths.

    Parameters
    ----------
    source : Path
        The document containing the glob-enabled toctree.
    docs_root : Path
        The Sphinx source directory.
    target : str
        The source-relative glob expression.

    Returns
    -------
    set[Path]
        Existing maintained Markdown documents selected by the expression.
    """
    relative_parts = list(Path(target.lstrip("/")).parts)
    base = docs_root if target.startswith("/") else source.parent
    while relative_parts and relative_parts[0] in {".", ".."}:
        if relative_parts.pop(0) == "..":
            base = base.parent
    pattern = Path(*relative_parts)
    matches: set[Path] = set()
    for match in base.glob(str(pattern)):
        candidate = match / "index.md" if match.is_dir() else match
        if candidate.suffix != ".md" or not candidate.is_file():
            continue
        try:
            candidate.resolve().relative_to(docs_root.resolve())
        except ValueError:
            continue
        matches.add(candidate.resolve())
    return matches


def _toctree_targets(source: Path, docs_root: Path) -> set[Path]:
    """Return maintained Markdown targets linked by one document's toctrees.

    Parameters
    ----------
    source : Path
        The maintained Markdown document to inspect.
    docs_root : Path
        The Sphinx source directory.

    Returns
    -------
    set[Path]
        Existing maintained Markdown documents linked from the source.
    """
    targets: set[Path] = set()
    for options, entries in _toctrees(source):
        for entry in entries:
            target = _entry_target(entry)
            if "glob" in options and any(marker in target for marker in "*?["):
                targets.update(_glob_targets(source, docs_root, target))
                continue
            docname = _normalized_docname(source, docs_root, target)
            if docname is None:
                continue
            source_path = _source_path(docs_root, docname)
            if source_path is not None:
                targets.add(source_path)
    return targets


def navigation_failures(docs_root: Path) -> list[str]:
    """Validate Maru's curated root navigation and source reachability.

    Parameters
    ----------
    docs_root : Path
        The Sphinx source directory.

    Returns
    -------
    list[str]
        Stable human-readable policy failures.
    """
    docs_root = docs_root.resolve()
    root_index = docs_root / "index.md"
    if not root_index.is_file():
        return ["docs/index.md: missing documentation root"]

    failures: list[str] = []
    root_blocks = _toctrees(root_index)
    if any("glob" in options for options, _entries in root_blocks):
        failures.append("docs/index.md: root navigation must not use :glob:")

    root_entries = tuple(
        docname
        for _options, entries in root_blocks
        for entry in entries
        if (
            docname := _normalized_docname(
                root_index,
                docs_root,
                _entry_target(entry),
            )
        )
        is not None
    )
    if root_entries != ROOT_HUB_DOCNAMES:
        failures.append(
            "docs/index.md: root navigation must contain exactly, in order: "
            + ", ".join(ROOT_HUB_DOCNAMES)
        )
    direct_archives = tuple(
        entry for entry in root_entries if entry.startswith(ARCHIVE_DOCNAME_PREFIXES)
    )
    if direct_archives:
        failures.append(
            "docs/index.md: ADRs and checkpoints belong behind reference catalogs, "
            f"not in root navigation: {', '.join(direct_archives)}"
        )

    maintained = {
        path.resolve()
        for path in docs_root.rglob("*.md")
        if not EXCLUDED_PARTS.intersection(path.relative_to(docs_root).parts)
        and "_build" not in path.relative_to(docs_root).parts
    }
    reachable = {root_index.resolve()}
    pending = [root_index.resolve()]
    while pending:
        source = pending.pop()
        for target in _toctree_targets(source, docs_root):
            if target not in reachable:
                reachable.add(target)
                pending.append(target)

    unreachable = sorted(
        path.relative_to(docs_root).as_posix() for path in maintained - reachable
    )
    if unreachable:
        failures.append(
            "docs/index.md: maintained Markdown is not reachable through the "
            f"toctree catalogs: {', '.join(unreachable)}"
        )
    return failures


def _policy_content_files(root: Path) -> list[Path]:
    """Return maintained guides, examples, fixtures, and application text.

    Parameters
    ----------
    root : Path
        The repository root to inspect.

    Returns
    -------
    list[Path]
        Policy-controlled text files in stable path order. All maintained
        Markdown is included, including historical records and research.
    """
    files = set(markdown_files(root))
    for relative_root in POLICY_CONTENT_ROOTS:
        candidate = root / relative_root
        if candidate.is_file():
            candidates = [candidate]
        else:
            candidates = []
            for directory, directories, filenames in os.walk(candidate):
                directories[:] = [
                    name for name in directories if name not in EXCLUDED_PARTS
                ]
                candidates.extend(Path(directory) / name for name in filenames)
        for path in candidates:
            if path.suffix.lower() not in POLICY_CONTENT_SUFFIXES:
                continue
            relative = path.relative_to(root)
            if EXCLUDED_PARTS.intersection(relative.parts):
                continue
            if relative == POLICY_DEFINITION_PATH:
                continue
            files.add(path)
    return sorted(files)


def _is_external_live_person_url(raw_url: str) -> bool:
    """Return whether a URL points at a non-synthetic people directory.

    Parameters
    ----------
    raw_url : str
        The HTTP URL found in repository-controlled text.

    Returns
    -------
    bool
        ``True`` for external roster-like paths outside reserved example hosts.
    """
    parsed = urlsplit(raw_url.rstrip(".,;:`"))
    hostname = (parsed.hostname or "").lower()
    if (
        not hostname
        or hostname in {"localhost", "127.0.0.1", "::1"}
        or hostname in RESERVED_EXAMPLE_HOSTS
        or hostname.endswith(
            (
                ".example.com",
                ".example.net",
                ".example.org",
                ".invalid",
                ".localhost",
                ".test",
            )
        )
    ):
        return False
    path_segments = {segment.lower() for segment in parsed.path.split("/") if segment}
    return bool(path_segments & LIVE_PERSON_PATH_SEGMENTS)


def ethical_content_failures(root: Path) -> list[str]:
    """Reject real conventions and live people directories from current data.

    Parameters
    ----------
    root : Path
        The repository root to inspect.

    Returns
    -------
    list[str]
        Stable human-readable policy failures.

    Notes
    -----
    The narrow denylist applies to maintained current and historical text so a
    real convention cannot reappear as example data. It does not restrict
    unrelated software, source, or legal attribution.
    """
    failures: list[str] = []
    for path in _policy_content_files(root):
        content = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        for match in CONVENTION_NAME_TOKEN_PATTERN.finditer(content):
            fingerprint = hashlib.sha256(
                match.group(0).casefold().encode("utf-8")
            ).hexdigest()
            if fingerprint not in PROHIBITED_CONVENTION_NAME_FINGERPRINTS:
                continue
            line = content.count("\n", 0, match.start()) + 1
            failures.append(
                f"{relative}:{line}: prohibited real convention name is not allowed "
                "in current guides, examples, fixtures, or application data"
            )
        for match in URL_PATTERN.finditer(content):
            if not _is_external_live_person_url(match.group(0)):
                continue
            line = content.count("\n", 0, match.start()) + 1
            failures.append(
                f"{relative}:{line}: external live-person directory URL is not "
                "allowed in current guides, examples, fixtures, or application data"
            )
    return failures


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

    failures.extend(navigation_failures(ROOT / "docs"))
    failures.extend(ethical_content_failures(ROOT))

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
