import re
from pathlib import Path

from django.contrib.staticfiles import finders


def _static_path(relative_path: str) -> Path:
    found = finders.find(relative_path)
    assert isinstance(found, str)
    return Path(found)


def test_single_select_keeps_enough_height_for_its_selected_label() -> None:
    baseline = _static_path("core/baseline.css").read_text(encoding="utf-8")
    select_rule = re.search(
        r"\.baseline-form select\s*\{(?P<body>[^}]*)\}",
        baseline,
    )

    assert select_rule is not None
    declarations = select_rule.group("body")
    assert "height: auto;" in declarations
    assert "min-height: 2.75rem;" in declarations
