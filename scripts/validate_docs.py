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
AGENT_SKILL_ROOT = Path(".agents/skills")
EXPECTED_AGENT_SKILLS = (
    "maru-browser-rehearsal",
    "maru-change-map",
    "maru-pr-delivery",
    "maru-product-planning",
)
AGENT_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
AGENT_SKILL_FRONTMATTER_FIELD_PATTERN = re.compile(r"^([a-z][a-z0-9_-]*):\s*(.+?)\s*$")
AGENT_SKILL_PLACEHOLDER_PATTERN = re.compile(r"\b(?:TODO|TBD)\b")
MIN_QUOTED_SCALAR_LENGTH = 2
MAX_AGENT_SKILL_NAME_LENGTH = 64
MAX_AGENT_SKILL_DESCRIPTION_LENGTH = 500
MIN_AGENT_SKILL_SHORT_DESCRIPTION_LENGTH = 25
MAX_AGENT_SKILL_SHORT_DESCRIPTION_LENGTH = 64
ARCHIVE_DOCNAME_PREFIXES = ("architecture/decisions/", "checkpoints/")
PURPOSE_NAMING_ARCHIVE_PREFIXES = (
    "docs/architecture/decisions/",
    "docs/checkpoints/",
)
PURPOSE_NAMING_ARCHIVE_PATHS = frozenset(
    {
        "docs/project/PRODUCTION_CONSOLIDATION.md",
        "docs/project/PROGRESS.md",
        "docs/project/RESET_REBUILD.md",
    }
)
NUMBERED_SURFACE_LABEL_PATTERN = re.compile(
    r"\bpages?\s+(?:10|[1-9])(?:[a-z](?:\.\d+)?)?(?=\b|[\u2013-])",
    re.IGNORECASE,
)
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
    Path(".agents"),
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


def purpose_name_failures(root: Path) -> list[str]:
    """Reject numbered management-surface labels from living guidance.

    Parameters
    ----------
    root : Path
        The repository root whose documentation should be inspected.

    Returns
    -------
    list[str]
        Stable failures for current documents that use implementation-order
        labels instead of human task names.

    Notes
    -----
    Accepted decisions, append-only checkpoints, and explicitly frozen project
    ledgers retain their original language as historical evidence. Numeric
    filename prefixes are not content and remain valid for link stability.
    """
    failures: list[str] = []
    docs_root = root / "docs"
    if not docs_root.is_dir():
        return failures

    for path in sorted(docs_root.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        if relative in PURPOSE_NAMING_ARCHIVE_PATHS or relative.startswith(
            PURPOSE_NAMING_ARCHIVE_PREFIXES
        ):
            continue
        content = path.read_text(encoding="utf-8")
        for match in NUMBERED_SURFACE_LABEL_PATTERN.finditer(content):
            line = content.count("\n", 0, match.start()) + 1
            failures.append(
                f"{relative}:{line}: use the management surface's purpose name "
                f"instead of historical label {match.group(0)!r}"
            )
    return failures


def _agent_skill_frontmatter(content: str) -> dict[str, str] | None:
    """Parse the flat required fields from one skill frontmatter block.

    Parameters
    ----------
    content : str
        Complete ``SKILL.md`` text.

    Returns
    -------
    dict[str, str] | None
        Unquoted top-level scalar fields, or ``None`` when the opening or
        closing delimiter is missing.
    """
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        return None
    try:
        closing_index = lines.index("---", 1)
    except ValueError:
        return None

    fields: dict[str, str] = {}
    for line in lines[1:closing_index]:
        match = AGENT_SKILL_FRONTMATTER_FIELD_PATTERN.fullmatch(line)
        if match is None:
            continue
        value = match.group(2).strip()
        quoted_scalar = (
            len(value) >= MIN_QUOTED_SCALAR_LENGTH
            and value[0] == value[-1]
            and value[0] in {'"', "'"}
        )
        if quoted_scalar:
            value = value[1:-1]
        fields[match.group(1)] = value
    return fields


def _quoted_openai_yaml_value(content: str, field: str) -> str | None:
    """Return one quoted two-space-indented interface scalar.

    Parameters
    ----------
    content : str
        Complete ``agents/openai.yaml`` text.
    field : str
        Interface field name to locate.

    Returns
    -------
    str | None
        The quoted scalar value, or ``None`` when the field is absent or uses
        another shape.
    """
    match = re.search(
        rf'^  {re.escape(field)}: "([^"\n]+)"\s*$',
        content,
        flags=re.MULTILINE,
    )
    return None if match is None else match.group(1)


def _agent_skill_entrypoint_findings(
    root: Path,
    skill_root: Path,
    skill_name: str,
) -> tuple[str, list[str]]:
    """Read and validate one skill entrypoint and directory shape.

    Parameters
    ----------
    root : Path
        Repository root used for stable relative paths.
    skill_root : Path
        Directory containing the skill entrypoint.
    skill_name : str
        Expected directory and frontmatter name.

    Returns
    -------
    tuple[str, list[str]]
        Complete entrypoint text when present and stable validation failures.
    """
    failures: list[str] = []
    relative_root = skill_root.relative_to(root).as_posix()
    invalid_name = (
        len(skill_name) > MAX_AGENT_SKILL_NAME_LENGTH
        or AGENT_SKILL_NAME_PATTERN.fullmatch(skill_name) is None
    )
    if invalid_name:
        failures.append(f"{relative_root}: invalid lowercase hyphenated skill name")

    readme = skill_root / "README.md"
    if readme.exists():
        relative_readme = readme.relative_to(root).as_posix()
        failures.append(
            f"{relative_readme}: skill guidance belongs in SKILL.md or a routed "
            "reference"
        )

    skill_path = skill_root / "SKILL.md"
    if not skill_path.is_file():
        failures.append(f"{relative_root}/SKILL.md: missing skill entrypoint")
        return "", failures

    skill_content = skill_path.read_text(encoding="utf-8")
    relative_skill_path = skill_path.relative_to(root).as_posix()
    fields = _agent_skill_frontmatter(skill_content)
    if fields is None:
        failures.append(f"{relative_skill_path}: missing delimited YAML frontmatter")
        return skill_content, failures

    if fields.get("name") != skill_name:
        failures.append(
            f"{relative_skill_path}: frontmatter name must equal {skill_name!r}"
        )
    description = fields.get("description", "").strip()
    if not description:
        failures.append(f"{relative_skill_path}: description is required")
    elif len(description) > MAX_AGENT_SKILL_DESCRIPTION_LENGTH:
        failures.append(
            f"{relative_skill_path}: description must remain concise enough for "
            "skill discovery"
        )
    return skill_content, failures


def _agent_skill_metadata_failures(
    root: Path,
    skill_root: Path,
    skill_name: str,
) -> list[str]:
    """Validate one skill's user-facing Codex interface metadata.

    Parameters
    ----------
    root : Path
        Repository root used for stable relative paths.
    skill_root : Path
        Directory containing the skill metadata.
    skill_name : str
        Skill name that the default prompt must invoke.

    Returns
    -------
    list[str]
        Stable metadata validation failures.
    """
    metadata_path = skill_root / "agents" / "openai.yaml"
    relative_root = skill_root.relative_to(root).as_posix()
    if not metadata_path.is_file():
        return [
            f"{relative_root}/agents/openai.yaml: missing repository skill metadata"
        ]

    failures: list[str] = []
    metadata_content = metadata_path.read_text(encoding="utf-8")
    relative_metadata_path = metadata_path.relative_to(root).as_posix()
    if not metadata_content.startswith("interface:\n"):
        failures.append(
            f"{relative_metadata_path}: metadata must start with the interface mapping"
        )

    display_name = _quoted_openai_yaml_value(metadata_content, "display_name")
    short_description = _quoted_openai_yaml_value(
        metadata_content,
        "short_description",
    )
    default_prompt = _quoted_openai_yaml_value(metadata_content, "default_prompt")
    if display_name is None:
        failures.append(f"{relative_metadata_path}: quoted display_name is required")

    valid_short_description = short_description is not None and (
        MIN_AGENT_SKILL_SHORT_DESCRIPTION_LENGTH
        <= len(short_description)
        <= MAX_AGENT_SKILL_SHORT_DESCRIPTION_LENGTH
    )
    if not valid_short_description:
        failures.append(
            f"{relative_metadata_path}: quoted short_description must contain "
            f"{MIN_AGENT_SKILL_SHORT_DESCRIPTION_LENGTH} through "
            f"{MAX_AGENT_SKILL_SHORT_DESCRIPTION_LENGTH} characters"
        )
    if default_prompt is None or f"${skill_name}" not in default_prompt:
        failures.append(
            f"{relative_metadata_path}: quoted default_prompt must explicitly mention "
            f"${skill_name}"
        )
    return failures


def _agent_skill_placeholder_failures(
    root: Path,
    skill_path: Path,
    metadata_path: Path,
    references: list[Path],
) -> list[str]:
    """Find unfinished scaffold markers in one complete skill package.

    Parameters
    ----------
    root : Path
        Repository root used for stable relative paths.
    skill_path : Path
        Skill entrypoint to inspect.
    metadata_path : Path
        Optional interface metadata path to inspect when present.
    references : list[Path]
        Routed Markdown references belonging to the skill.

    Returns
    -------
    list[str]
        Stable placeholder validation failures.
    """
    skill_text_files = [skill_path]
    if metadata_path.is_file():
        skill_text_files.append(metadata_path)
    skill_text_files.extend(references)
    return [
        f"{path.relative_to(root).as_posix()}: unfinished scaffold placeholder"
        for path in skill_text_files
        if AGENT_SKILL_PLACEHOLDER_PATTERN.search(path.read_text(encoding="utf-8"))
    ]


def _agent_skill_reference_failures(
    root: Path,
    skill_root: Path,
    skill_content: str,
    references: list[Path],
) -> list[str]:
    """Require every skill reference to be reachable from its entrypoint.

    Parameters
    ----------
    root : Path
        Repository root used for stable relative paths.
    skill_root : Path
        Directory used to resolve entrypoint-relative links.
    skill_content : str
        Complete skill entrypoint text.
    references : list[Path]
        Markdown references that must be linked for progressive disclosure.

    Returns
    -------
    list[str]
        Stable failures for references not linked from ``SKILL.md``.
    """
    linked_references: set[Path] = set()
    for match in LINK_PATTERN.finditer(skill_content):
        raw_target = match.group(1).strip().strip("<>").split("#", 1)[0]
        target = unquote(raw_target)
        if target.startswith("references/"):
            linked_references.add((skill_root / target).resolve())

    return [
        (
            f"{reference.relative_to(root).as_posix()}: reference must be linked "
            "from SKILL.md for progressive disclosure"
        )
        for reference in references
        if reference.resolve() not in linked_references
    ]


def agent_skill_failures(root: Path) -> list[str]:
    """Validate Maru's curated repository-scoped Codex skills.

    Parameters
    ----------
    root : Path
        Repository root containing ``.agents/skills``.

    Returns
    -------
    list[str]
        Stable failures for missing skills, invalid metadata, scaffold
        placeholders, or references that progressive disclosure cannot reach.
    """
    failures: list[str] = []
    skills_root = root / AGENT_SKILL_ROOT
    if not skills_root.is_dir():
        return [f"{AGENT_SKILL_ROOT.as_posix()}: missing repository skill catalog"]

    actual_names = tuple(
        sorted(path.name for path in skills_root.iterdir() if path.is_dir())
    )
    missing = sorted(set(EXPECTED_AGENT_SKILLS) - set(actual_names))
    unexpected = sorted(set(actual_names) - set(EXPECTED_AGENT_SKILLS))
    if missing:
        failures.append(
            f"{AGENT_SKILL_ROOT.as_posix()}: missing curated skills: "
            + ", ".join(missing)
        )
    if unexpected:
        failures.append(
            f"{AGENT_SKILL_ROOT.as_posix()}: unexpected skills require policy review: "
            + ", ".join(unexpected)
        )

    for skill_name in EXPECTED_AGENT_SKILLS:
        skill_root = skills_root / skill_name
        if not skill_root.is_dir():
            continue
        skill_path = skill_root / "SKILL.md"
        skill_content, entrypoint_failures = _agent_skill_entrypoint_findings(
            root,
            skill_root,
            skill_name,
        )
        failures.extend(entrypoint_failures)
        if not skill_content:
            continue
        metadata_path = skill_root / "agents" / "openai.yaml"
        failures.extend(_agent_skill_metadata_failures(root, skill_root, skill_name))
        references_root = skill_root / "references"
        references = (
            sorted(references_root.rglob("*.md")) if references_root.is_dir() else []
        )
        failures.extend(
            _agent_skill_placeholder_failures(
                root,
                skill_path,
                metadata_path,
                references,
            )
        )
        failures.extend(
            _agent_skill_reference_failures(
                root,
                skill_root,
                skill_content,
                references,
            )
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
    failures.extend(purpose_name_failures(ROOT))
    failures.extend(agent_skill_failures(ROOT))
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
        f"Documentation and agent support valid: {len(files)} Markdown files, "
        f"{len(EXPECTED_AGENT_SKILLS)} repository skills, "
        f"{len(requirements)} unique requirement identifiers."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
