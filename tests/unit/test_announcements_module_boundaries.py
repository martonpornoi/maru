"""Keep standalone Announcements behind its documented foundation boundaries."""

import ast
from pathlib import Path

from django.apps import apps

_SOURCE = Path(__file__).parents[2] / "src" / "maru" / "announcements"
_FOUNDATIONS = frozenset(
    {"core", "audit", "authorization", "effects", "events", "identity", "organizations"}
)


def test_announcements_imports_no_foreign_private_models_or_unadopted_modules() -> None:
    violations = []
    for path in sorted(_SOURCE.rglob("*.py")):
        if "migrations" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                modules = [node.module or ""]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            for module in modules:
                if not module.startswith("maru."):
                    continue
                owner = module.split(".")[1]
                if owner == "announcements":
                    continue
                if owner not in _FOUNDATIONS or (
                    module.endswith(".models") and module != "maru.core.models"
                ):
                    violations.append((path.name, node.lineno, module))
    assert violations == []


def test_announcements_relations_cannot_create_unadopted_person_relationships() -> None:
    owners = {
        field.related_model._meta.app_label
        for model in apps.get_app_config("announcements").get_models()
        for field in model._meta.fields
        if field.is_relation
    }
    assert owners == {"announcements", "events", "identity", "organizations"}
