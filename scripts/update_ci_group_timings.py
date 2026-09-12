"""Refresh diagnostic group costs from complete source-matched JUnit evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

from scripts.ci_test_policy import ROOT, build_groups


def _identity(node: str) -> tuple[str, str]:
    file, remainder = node.split("::", 1)
    prefix, bracket, parameters = remainder.partition("[")
    parts = prefix.split("::")
    classname = file.removesuffix(".py").replace("/", ".")
    if len(parts) > 1:
        classname += "." + ".".join(parts[:-1])
    name = (parts[-1] + bracket + parameters).replace("\n", r"\n").replace("\r", r"\r")
    return classname, name


def _validate_suite_counts(tree: ET.ElementTree, expected_count: int) -> None:
    for suite in tree.iter("testsuite"):
        if any(
            int(suite.attrib.get(key, "0")) != 0
            for key in ("failures", "errors", "skipped")
        ):
            raise ValueError("nonpassing suite cannot provide cost evidence")
    if (
        sum(int(suite.attrib["tests"]) for suite in tree.iter("testsuite"))
        != expected_count
    ):
        raise ValueError("JUnit suite count differs from the selected identities")


def report_costs(
    report: Path, selection: Path
) -> tuple[dict[str, float], frozenset[str]]:
    """Reconcile a complete passing report to its exact selected test identities.

    Parameters
    ----------
    report : Path
        Complete JUnit report; partial, failed or skipped reports are rejected.
    selection : Path
        Matching selected-group JSON from that exact process.

    Returns
    -------
    tuple[dict[str, float], frozenset[str]]
        Group durations including setup/teardown and exact selected node IDs.

    Raises
    ------
    ValueError
        For incomplete, duplicate, malformed or nonpassing evidence.
    """
    evidence = json.loads(selection.read_text(encoding="utf-8"))
    expected = {}
    nodeids = set()
    for group, nodes in evidence["groups"].items():
        if not nodes:
            raise ValueError("empty measured group")
        for node in nodes:
            identity = _identity(node)
            if identity in expected or node in nodeids:
                raise ValueError("duplicate selected testcase")
            expected[identity] = group
            nodeids.add(node)
    if len(expected) != evidence["selected"] or not expected:
        raise ValueError("selection count differs from its identities")
    tree = ET.parse(report)  # noqa: S314 - local diagnostic evidence, never production input
    groups = defaultdict(float)
    seen = set()
    _validate_suite_counts(tree, len(expected))
    for case in tree.iter("testcase"):
        if any(case.find(tag) is not None for tag in ("failure", "error", "skipped")):
            raise ValueError("nonpassing testcase cannot provide cost evidence")
        identity = case.attrib["classname"], case.attrib["name"]
        if identity not in expected or identity in seen:
            raise ValueError("unexpected or duplicated report identity")
        seen.add(identity)
        duration = float(case.attrib["time"])
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("invalid testcase duration")
        groups[expected[identity]] += duration
    if seen != set(expected) or any(value <= 0 for value in groups.values()):
        raise ValueError("incomplete or nonpositive group timing evidence")
    return dict(groups), frozenset(nodeids)


def _merge_hosted_costs(
    directory: Path | None,
    exclusions: set[str],
    measured: dict[str, float],
    local_nodes: set[str],
    inputs: list[Path],
) -> set[str]:
    observed: set[str] = set()
    excluded_observed: set[str] = set()
    if directory is None:
        if exclusions:
            raise ValueError("hosted exclusions require hosted evidence")
        return observed
    for report in sorted(directory.rglob("integration-*.xml")):
        selection = report.with_name(
            report.name.replace("integration-", "selection-")
        ).with_suffix(".json")
        costs, nodes = report_costs(report, selection)
        excluded_observed.update(
            key.split("::", 1)[0]
            for key in costs
            if key.split("::", 1)[0] in exclusions
        )
        costs = {
            key: value
            for key, value in costs.items()
            if key.split("::", 1)[0] not in exclusions
        }
        nodes = frozenset(
            node for node in nodes if node.split("::", 1)[0] not in exclusions
        )
        if (
            observed & costs.keys()
            or not costs.keys() <= measured.keys()
            or not nodes <= local_nodes
        ):
            unmatched = sorted({node.split("::", 1)[0] for node in nodes - local_nodes})
            raise ValueError(
                f"hosted observations differ from local inventory: {report}; "
                f"unmatched files: {unmatched}"
            )
        for key, value in costs.items():
            measured[key] = max(measured[key], value)
        observed.update(costs)
        inputs.extend((report, selection))
    if excluded_observed != exclusions or not observed:
        raise ValueError("unused exclusions or no usable hosted timing observations")
    return observed


def main() -> int:
    """Write a complete cost map with exact receipt and file-hash provenance.

    Returns
    -------
    int
        Zero after every required group and selected case has been reconciled.

    Raises
    ------
    ValueError
        If provenance, source identity, group coverage or observations differ.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-evidence", type=Path, required=True)
    parser.add_argument("--hosted-evidence", type=Path)
    parser.add_argument("--exclude-hosted-file", action="append", default=[])
    parser.add_argument("--commit", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if not all(
        re.fullmatch(r"[0-9a-f]{40}", value) for value in (args.commit, args.base)
    ):
        parser.error("full exact commit and base identifiers are required")
    receipt_path = args.local_evidence / "certification.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    if (
        receipt.get("result"),
        receipt.get("commit"),
        receipt.get("base_commit"),
        receipt.get("historical_scope"),
    ) != ("success", args.commit, args.base, "all"):
        raise ValueError("cost refresh requires a complete exact-head local receipt")
    required = build_groups()
    git = shutil.which("git")
    if git is None:
        raise ValueError("Git is required to verify measured source provenance")
    for file in {group.file for group in required}:
        original = subprocess.run(  # noqa: S603 - validated commit and source inventory
            [git, "show", f"{args.commit}:{file}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        if original.replace(b"\r\n", b"\n") != (ROOT / file).read_bytes().replace(
            b"\r\n", b"\n"
        ):
            raise ValueError(f"measured test source changed: {file}")
    measured = {}
    local_nodes = set()
    inputs = [receipt_path]
    reports = sorted((args.local_evidence / "reports").glob("integration-*.xml"))
    if len(reports) != receipt["integration_shards"]:
        raise ValueError("local shard inventory differs from receipt")
    for report in reports:
        selection = report.with_name(
            report.name.replace("integration-", "selection-")
        ).with_suffix(".json")
        costs, nodes = report_costs(report, selection)
        if measured.keys() & costs.keys() or local_nodes & nodes:
            raise ValueError("duplicated local groups or cases")
        measured.update(costs)
        local_nodes.update(nodes)
        inputs.extend((report, selection))
    if measured.keys() != {group.key for group in required}:
        raise ValueError(
            "local cost evidence does not cover every current and historical group"
        )
    exclusions = set(args.exclude_hosted_file)
    if not exclusions <= {group.file for group in required}:
        raise ValueError("unknown hosted diagnostic exclusion")
    observed = _merge_hosted_costs(
        args.hosted_evidence, exclusions, measured, local_nodes, inputs
    )
    provenance = {
        "schema_version": 1,
        "commit": args.commit,
        "base": args.base,
        "historical_scope": "all",
        "local_groups": len(measured),
        "hosted_observed_groups": len(observed),
        "excluded_hosted_files": sorted(exclusions),
        "method": (
            "maximum complete observed local/hosted group cost; "
            "planner separately adds slowdown and overhead"
        ),
        "inputs": [
            {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in inputs
        ],
    }
    args.destination.write_text(
        json.dumps(
            {key: round(value, 3) for key, value in sorted(measured.items())}, indent=2
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    args.destination.with_suffix(".provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        f"Measured {len(measured)} groups; {len(observed)} have additional hosted "
        "observations. No acceptance claim is made."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
