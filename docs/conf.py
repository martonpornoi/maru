"""Sphinx configuration for the Maru contributor documentation."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

project = "Maru"
author = "Maru contributors"
copyright = "2026, Maru contributors"
release = "0.1.0a0"

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
html_title = "Maru documentation"

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
