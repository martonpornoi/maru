"""Build explicit, complete PostgreSQL work groups without importing test code.

Historical membership is reviewed data, not a filename, speed or import heuristic.
All unlisted cases remain current behavior. Execution verifies these source-level
groups against pytest's actual collected cases before a database is opened.
"""

from __future__ import annotations

import ast
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from scripts.ci_changes import ChangedFile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "scripts/ci_historical_tests.json"
TIMINGS = "scripts/ci_test_group_timings.json"
MODULE_PATH_LENGTH = 4
RECOVERY_SMOKE = (
    "tests/integration/test_authority_provenance_migration_fences.py::"
    "test_full_graph_reverse_and_forward_preserve_migration_ownership"
)


@dataclass(frozen=True)
class HistoricalFile:
    """Reviewed functions, owning modules and shared-baseline grouping.

    Attributes
    ----------
    owners : frozenset[str]
        Modules whose migration boundaries the file exercises.
    tests : frozenset[str]
        Exact top-level historical test function names, including all variants.
    shared_baseline : bool
        Whether the historical functions must remain in one process.
    """

    owners: frozenset[str]
    tests: frozenset[str]
    shared_baseline: bool


@dataclass(frozen=True)
class TestGroup:
    """An indivisible serial set of tests assigned to one isolated database.

    Attributes
    ----------
    key : str
        Stable file/group identity independent of randomized parameter IDs.
    file : str
        Repository-relative integration test file.
    historical : bool
        Whether this group exercises a historical migration boundary.
    weight : float
        Estimated group duration in seconds; never an acceptance assertion.
    """

    key: str
    file: str
    historical: bool
    weight: float


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate inventory key: {key}")
        result[key] = value
    return result


def _string_set(value: object) -> frozenset[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError("inventory lists must contain unique nonempty strings")
    return frozenset(value)


def load_history_inventory(root: Path = ROOT) -> dict[str, HistoricalFile]:
    """Validate the reviewed inventory against existing source and fixture scopes.

    Parameters
    ----------
    root : Path, default=ROOT
        Repository whose current test sources must match the inventory.

    Returns
    -------
    dict[str, HistoricalFile]
        Exact historical files and validated grouping rules.

    Raises
    ------
    ValueError
        If membership is missing, ambiguous or would split a shared baseline.
    """
    raw = json.loads(
        (root / MANIFEST).read_text(encoding="utf-8"), object_pairs_hook=_unique_object
    )
    if not isinstance(raw, dict) or not raw:
        raise ValueError("historical inventory must be a nonempty object")
    result = {}
    for file, entry in raw.items():
        if not re.fullmatch(r"tests/integration/test_[a-z0-9_]+\.py", file):
            raise ValueError(f"invalid historical file: {file}")
        if (
            not isinstance(entry, dict)
            or set(entry)
            - {"owners", "tests", "shared_baseline", "independent_fixtures"}
            or not {"owners", "tests", "shared_baseline"} <= set(entry)
        ):
            raise ValueError(f"invalid historical entry: {file}")
        owners = _string_set(entry["owners"])
        tests = _string_set(entry["tests"])
        if not all(re.fullmatch(r"[a-z][a-z0-9_]*", owner) for owner in owners):
            raise ValueError(f"invalid migration owner: {file}")
        if not all(
            (root / "src/maru" / owner / "migrations").is_dir() for owner in owners
        ):
            raise ValueError(f"unknown migration owner: {file}")
        if type(entry["shared_baseline"]) is not bool:
            raise ValueError(f"invalid baseline flag: {file}")
        path = root / file
        if not path.is_file():
            raise ValueError(f"historical file is missing: {file}")
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        names = [node.name for node in functions if node.name.startswith("test_")]
        if not tests <= set(names) or len(names) != len(set(names)):
            raise ValueError(f"missing or duplicate historical function: {file}")
        independent_fixtures = (
            _string_set(entry["independent_fixtures"])
            if "independent_fixtures" in entry
            else frozenset()
        )
        broad_fixtures = {
            node.name
            for node in functions
            if any(
                isinstance(decorator, ast.Call)
                and ast.unparse(decorator.func).endswith("fixture")
                and any(
                    keyword.arg == "scope"
                    and ast.literal_eval(keyword.value) != "function"
                    for keyword in decorator.keywords
                )
                for decorator in node.decorator_list
            )
        }
        if not independent_fixtures <= broad_fixtures:
            raise ValueError(f"unknown independently repeatable fixture: {file}")
        if broad_fixtures - independent_fixtures and not entry["shared_baseline"]:
            raise ValueError(f"shared fixture cannot be split: {file}")
        if entry["shared_baseline"] and set(names) != tests:
            raise ValueError(
                f"shared historical baseline has unclassified tests: {file}"
            )
        result[file] = HistoricalFile(owners, tests, entry["shared_baseline"])
    return result


def case_group(file: str, function: str, inventory: dict[str, HistoricalFile]) -> str:
    """Resolve a collected function to exactly one stable work group.

    Parameters
    ----------
    file : str
        Repository-relative file of the collected case.
    function : str
        Original function name without parameter identifiers.
    inventory : dict[str, HistoricalFile]
        Validated historical membership.

    Returns
    -------
    str
        Current-file, shared-history or independent-function group key.
    """
    entry = inventory.get(file)
    if entry is None or function not in entry.tests:
        return f"{file}::current"
    return f"{file}::historical" if entry.shared_baseline else f"{file}::{function}"


def build_groups(root: Path = ROOT) -> tuple[TestGroup, ...]:
    """Enumerate every current and historical group with positive cost evidence.

    Parameters
    ----------
    root : Path, default=ROOT
        Repository holding sources, reviewed membership and group costs.

    Returns
    -------
    tuple[TestGroup, ...]
        Stable complete inventory; new groups receive a conservative fallback.

    Raises
    ------
    ValueError
        If costs are invalid, stale or the integration inventory is empty.
    """
    inventory = load_history_inventory(root)
    timings = json.loads(
        (root / TIMINGS).read_text(encoding="utf-8"), object_pairs_hook=_unique_object
    )
    if not isinstance(timings, dict) or not timings:
        raise ValueError("group timings must be a nonempty object")
    for value in timings.values():
        if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
            raise ValueError("group timings must be positive finite seconds")
    groups = []
    for path in sorted((root / "tests/integration").glob("test_*.py")):
        file = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        functions = [
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        ]
        keys = {case_group(file, name, inventory) for name in functions}
        if any(
            isinstance(node, ast.ClassDef) and node.name.startswith("Test")
            for node in tree.body
        ):
            keys.add(f"{file}::current")
        groups.extend(
            TestGroup(
                key,
                file,
                not key.endswith("::current"),
                float(timings.get(key, max(timings.values()))),
            )
            for key in sorted(keys)
        )
    if not groups or set(timings) - {group.key for group in groups}:
        raise ValueError("empty integration inventory or stale group timings")
    return tuple(groups)


def affected_migration_owners(changes: Sequence[ChangedFile]) -> frozenset[str]:
    """Resolve changed schema nodes and their actual graph descendants.

    Parameters
    ----------
    changes : Sequence[ChangedFile]
        Exact base-to-candidate diff, including both sides of renames.

    Returns
    -------
    frozenset[str]
        Modules owning changed or dependent migration nodes.

    Raises
    ------
    ValueError
        If an affected schema node cannot be resolved safely.
    """
    from django.db.migrations.loader import MigrationLoader  # noqa: PLC0415

    loader = MigrationLoader(None)
    nodes = set()
    owners = set()
    for change in changes:
        parts = change.path.parts
        if len(parts) < MODULE_PATH_LENGTH or parts[:2] != ("src", "maru"):
            continue
        if "migrations" not in parts and parts[-1] != "models.py":
            continue
        owner = parts[2]
        owners.add(owner)
        if change.status == "D":
            raise ValueError("removed schema node requires exhaustive history")
        if "migrations" in parts and parts[-1] != "__init__.py":
            node = (owner, change.path.stem)
            if node not in loader.graph.nodes:
                raise ValueError(f"unknown migration node: {node}")
            nodes.add(node)
        else:
            leaves = loader.graph.leaf_nodes(owner)
            if not leaves:
                raise ValueError(f"unknown migration owner: {owner}")
            nodes.update(leaves)
    for node in nodes:
        owners.update(owner for owner, _name in loader.graph.backwards_plan(node))
    return frozenset(owners)


def select_groups(
    groups: Sequence[TestGroup],
    inventory: dict[str, HistoricalFile],
    history: str,
    owners: frozenset[str] = frozenset(),
    changed_files: frozenset[str] = frozenset(),
) -> tuple[TestGroup, ...]:
    """Select all current behavior plus the required historical boundary.

    Parameters
    ----------
    groups : Sequence[TestGroup]
        Complete validated work-group inventory.
    inventory : dict[str, HistoricalFile]
        Reviewed historical memberships and owners.
    history : str
        One of ``current``, ``affected`` or ``all``.
    owners : frozenset[str], default=frozenset()
        Changed and dependent schema owners.
    changed_files : frozenset[str], default=frozenset()
        Directly changed tests are always included when historical.

    Returns
    -------
    tuple[TestGroup, ...]
        Exact required groups including whole-graph recovery for affected history.

    Raises
    ------
    ValueError
        If the scope or mandatory recovery evidence is invalid.
    """
    if history not in {"current", "affected", "all"}:
        raise ValueError("unknown historical test scope")
    selected = [
        group
        for group in groups
        if not group.historical
        or history == "all"
        or (
            history == "affected"
            and (group.file in changed_files or inventory[group.file].owners & owners)
        )
    ]
    if history == "affected" and (
        owners or any(group.historical for group in selected)
    ):
        smoke = next((group for group in groups if group.key == RECOVERY_SMOKE), None)
        if smoke is None:
            raise ValueError("mandatory full-graph recovery test is missing")
        if smoke not in selected:
            selected.append(smoke)
    return tuple(sorted(selected, key=lambda group: group.key))


def partition_groups(
    groups: Sequence[TestGroup], count: int
) -> tuple[tuple[TestGroup, ...], ...]:
    """Balance complete indivisible groups without duplicating or dropping work.

    Parameters
    ----------
    groups : Sequence[TestGroup]
        Required groups and measured cost estimates.
    count : int
        Number of isolated serial work groups, each required to be nonempty.

    Returns
    -------
    tuple[tuple[TestGroup, ...], ...]
        Deterministic shards whose disjoint union equals the input inventory.

    Raises
    ------
    ValueError
        If the requested partition cannot preserve complete unique execution.
    """
    if (
        count < 1
        or count > len(groups)
        or len({group.key for group in groups}) != len(groups)
    ):
        raise ValueError("invalid shard count or duplicate work group")
    buckets: list[list[TestGroup]] = [[] for _ in range(count)]
    costs = [0.0] * count
    for group in sorted(groups, key=lambda group: (-group.weight, group.key)):
        if not math.isfinite(group.weight) or group.weight <= 0:
            raise ValueError("invalid work group duration")
        index = min(range(count), key=lambda index: (costs[index], index))
        buckets[index].append(group)
        costs[index] += group.weight
    return tuple(
        tuple(sorted(bucket, key=lambda group: group.key)) for bucket in buckets
    )
