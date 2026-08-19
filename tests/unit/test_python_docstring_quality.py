"""Tests for the semantic Python-docstring quality gate."""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType


def _validator_module() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "validate_python_docstrings.py"
    spec = importlib.util.spec_from_file_location("validate_python_docstrings", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def test_validator_accepts_professional_sections(tmp_path: Path) -> None:
    module = _validator_module()
    source = tmp_path / "documented.py"
    source.write_text(
        '''"""Example module."""
from dataclasses import dataclass

@dataclass
class Result:
    """Capture a normalized answer.

    Attributes
    ----------
    answer
        The normalized answer safe for persistence.
    """
    answer: str

def normalize(answer: str) -> Result:
    """Normalize one submitted answer.

    Parameters
    ----------
    answer
        The untrusted answer submitted by the caller.

    Returns
    -------
    Result
        A normalized answer safe for persistence.

    Raises
    ------
    ValueError
        If the submitted answer is empty.
    """
    if not answer:
        raise ValueError("answer is required")
    return Result(answer.strip())
''',
        encoding="utf-8",
    )

    assert module.validate_file(source) == []


def test_validator_rejects_generated_placeholders_and_missing_contracts(
    tmp_path: Path,
) -> None:
    module = _validator_module()
    source = tmp_path / "placeholder.py"
    source.write_text(
        '''"""Example module."""
from dataclasses import dataclass

@dataclass
class Result:
    """Represent result."""
    answer: str

def normalize(answer: str) -> Result:
    """Handle normalize.

    Parameters
    ----------
    answer
        The answer value.
    """
    raise ValueError("invalid")
''',
        encoding="utf-8",
    )

    codes = {issue.code for issue in module.validate_file(source)}

    assert codes == {"PDQ001", "PDQ002", "PDQ003", "PDQ004"}


def test_validator_rejects_structurally_valid_contract_placeholders(
    tmp_path: Path,
) -> None:
    module = _validator_module()
    source = tmp_path / "contract_placeholder.py"
    source.write_text(
        '''"""Example module."""

def normalize(answer: str) -> str:
    """Normalize one answer.

    Parameters
    ----------
    answer
        The answer accepted by this callable contract.

    Returns
    -------
    str
        The normalized answer.
    """
    return answer.strip()

def display(answer: str) -> str:
    """Prepare one answer for display.

    Parameters
    ----------
    answer
        The normalized answer to display.

    Returns
    -------
    str
        The value defined by this callable's public contract.
    """
    return answer
''',
        encoding="utf-8",
    )

    issues = module.validate_file(source)

    assert [issue.code for issue in issues].count("PDQ002") == 2


def test_pydoclint_keeps_the_strict_contract_enabled() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )
    config = pyproject["tool"]["pydoclint"]

    for option in (
        "arg-type-hints-in-signature",
        "arg-type-hints-in-docstring",
        "check-arg-order",
        "check-return-types",
        "require-yield-section-when-yielding-nothing",
        "check-yield-types",
        "check-style-mismatch",
        "should-document-star-arguments",
        "should-declare-assert-error-if-assert-statement-exists",
        "check-arg-defaults",
        "show-filenames-in-every-violation-message",
    ):
        assert config[option] is True

    for option in (
        "skip-checking-short-docstrings",
        "skip-checking-private-functions",
        "skip-checking-raises",
        "ignore-underscore-args",
        "ignore-private-args",
        "omit-stars-when-documenting-varargs",
    ):
        assert config[option] is False

    assert config["style"] == "numpy"
    assert config["allow-init-docstring"] is True
    assert config["native-mode-noqa-location"] == "definition"


def test_ruff_global_exemptions_stay_bounded() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )
    config = pyproject["tool"]["ruff"]["lint"]
    global_ignores = set(config["ignore"])

    assert config["select"] == ["ALL"]
    assert config["external"] == ["DOC"]
    assert global_ignores <= {
        "ANN401",
        "C901",
        "COM812",
        "EM101",
        "EM102",
        "ISC001",
        "PLR0913",
        "TRY003",
    }
    assert global_ignores.isdisjoint(
        {
            "ANN001",
            "ANN002",
            "ANN003",
            "ANN201",
            "ANN202",
            "ANN204",
            "D105",
            "D106",
            "RSE102",
            "SLF001",
            "TC001",
            "TC002",
            "TC003",
            "TC006",
        }
    )
