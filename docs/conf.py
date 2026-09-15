"""Sphinx configuration for the Maru contributor documentation."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sphinx.application import Sphinx

PROJECT_ROOT = Path(__file__).resolve().parents[1]

with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject_file:
    project_version = tomllib.load(pyproject_file)["project"]["version"]
if not isinstance(project_version, str):
    raise TypeError("project.version must be a string")

project = "Maru"
author = "Maru contributors"
copyright = "2026, Maru contributors"
release = project_version
version = project_version

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinxcontrib.mermaid",
    "autoapi.extension",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}
root_doc = "index"
exclude_patterns = ["_build"]

html_theme = "furo"
html_static_path = ["_static"]
html_css_files = ["maru.css"]
html_title = f"Maru {release} contributor documentation"
html_theme_options = {
    "announcement": (
        f"Maru {release} is under active development and is not approved for "
        "production personal data."
    )
}

myst_enable_extensions = ["colon_fence", "deflist", "fieldlist"]
myst_fence_as_directive = ["mermaid"]
myst_heading_anchors = 3

napoleon_google_docstring = False
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = False
napoleon_use_param = True
napoleon_use_rtype = True

autodoc_typehints = "description"
autodoc_typehints_format = "short"

autoapi_type = "python"
autoapi_dirs = [str(PROJECT_ROOT / "src" / "maru")]
autoapi_root = "autoapi"
autoapi_add_toctree_entry = False
autoapi_keep_files = False
autoapi_member_order = "groupwise"
autoapi_python_class_content = "class"
autoapi_options = ["members", "show-inheritance", "show-module-summary"]
autoapi_ignore = [
    "*/migrations/*",
    "*/__pycache__/*",
]

# Keep the extension's browser-runtime boundary explicit. These exact versions
# are reviewed in the generated-documentation license and Pages runbooks.
mermaid_version = "11.16.1"
mermaid_include_elk = ""
d3_version = "7.9.0"


def _section_navigation(
    app: Sphinx,
    pagename: str,
    templatename: str,
    context: dict[str, Any],
    doctree: Any,
) -> None:
    """Keep all documents available without rendering every branch on each page."""
    del app, pagename, templatename, doctree
    original = context.get("toctree")
    if not callable(original):
        return

    def current_section(**options: Any) -> Any:
        # Furo explicitly requests collapse=False. Apply the owning ADR 0074
        # policy before its navigation transformation, not after expensive HTML.
        return original(**(options | {"collapse": True}))

    context["toctree"] = current_section


def setup(app: Sphinx) -> None:
    """Apply section navigation before Furo builds its per-page sidebar.

    Parameters
    ----------
    app : Sphinx
        Current documentation application, with no global theme monkeypatch.
    """
    # Furo's html-page-context listener uses Sphinx's default priority of 500.
    app.connect("html-page-context", _section_navigation, priority=400)
