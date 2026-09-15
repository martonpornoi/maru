"""Bound sidebar work without removing sources, search or cross-section routes."""

from __future__ import annotations

import io
import runpy
from typing import TYPE_CHECKING

import pytest
from bs4 import BeautifulSoup
from furo import _compute_navigation_tree
from scripts.validate_docs import ROOT
from sphinx.application import Sphinx

if TYPE_CHECKING:
    from pathlib import Path

_CONFIG = runpy.run_path(str(ROOT / "docs" / "conf.py"))
_HOOK = _CONFIG["_section_navigation"]


@pytest.mark.parametrize("collapse", [False, True, None])
def test_theme_request_is_scoped_without_changing_other_options(collapse):
    calls = []

    def original(**options):
        calls.append(options)
        return "<ul><li><a href='index.html'>Owning section</a></li></ul>"

    context = {"toctree": original, "sentinel": object()}
    untouched = context.copy()
    _HOOK(None, "alpha/one", "page.html", context, None)
    context["toctree"](collapse=collapse, maxdepth=-1, includehidden=True)
    assert calls.pop() == {"collapse": True, "maxdepth": -1, "includehidden": True}
    assert "Owning section" in _compute_navigation_tree(context)
    assert calls.pop() == {
        "collapse": True,
        "maxdepth": -1,
        "includehidden": True,
        "titles_only": True,
    }
    assert untouched["toctree"] is original
    assert context["sentinel"] is untouched["sentinel"]


@pytest.mark.parametrize("context", [{}, {"toctree": None}, {"toctree": "invalid"}])
def test_missing_or_invalid_context_is_not_replaced_with_fake_navigation(context):
    original = context.copy()
    _HOOK(None, "index", "page.html", context, None)
    assert context == original


def test_navigation_failures_propagate_without_empty_success():
    def original(**options):
        raise RuntimeError("broken source tree")

    context = {"toctree": original}
    _HOOK(None, "index", "page.html", context, None)
    with pytest.raises(RuntimeError, match="broken source tree"):
        context["toctree"](collapse=False)


def test_setup_runs_before_the_theme_without_monkeypatching_it():
    calls = []

    class Application:
        def connect(self, *args, **kwargs):
            calls.append((args, kwargs))

    _CONFIG["setup"](Application())
    assert calls == [(("html-page-context", _HOOK), {"priority": 400})]
    assert _CONFIG["html_theme"] == "furo"
    assert _CONFIG["autoapi_options"] == [
        "members",
        "show-inheritance",
        "show-module-summary",
    ]
    assert _CONFIG["exclude_patterns"] == ["_build"]


def test_real_furo_build_preserves_catalogs_current_branch_search_and_other_pages(
    tmp_path: Path,
):
    source = tmp_path / "source"
    output = tmp_path / "html"
    source.mkdir()
    (source / "conf.py").write_text(
        "project = 'Synthetic documentation'\nhtml_theme = 'furo'\n", encoding="utf-8"
    )
    pages = {
        "index": (
            "Documentation\n=============\n\n.. toctree::\n   :hidden:\n"
            "   :maxdepth: 1\n\n   alpha/index\n   beta/index\n"
        ),
        "alpha/index": (
            "Alpha section\n=============\n\n.. toctree::\n\n   one\n   two\n"
        ),
        "alpha/one": "Alpha one\n=========\n\nFirst source.\n",
        "alpha/two": "Alpha two\n=========\n\nSecond source.\n",
        "beta/index": "Beta section\n============\n\n.. toctree::\n\n   leaf\n",
        "beta/leaf": "Beta leaf\n=========\n\nSearchable distant reference.\n",
    }
    for name, text in pages.items():
        path = source / f"{name}.rst"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    warnings = io.StringIO()
    app = Sphinx(
        source,
        source,
        output,
        tmp_path / "doctrees",
        "html",
        status=io.StringIO(),
        warning=warnings,
        freshenv=True,
        warningiserror=True,
    )
    _CONFIG["setup"](app)
    app.build(force_all=True)
    assert app.statuscode == 0, warnings.getvalue()
    assert not warnings.getvalue()
    assert all((output / f"{name}.html").is_file() for name in pages)
    html = BeautifulSoup(
        (output / "alpha/one.html").read_text(encoding="utf-8"), "html.parser"
    )
    sidebar = html.select_one(".sidebar-tree")
    assert sidebar is not None
    labels = [link.get_text() for link in sidebar.select("a")]
    assert "Alpha section" in labels
    assert "Beta section" in labels
    assert "Alpha one" in labels
    assert "Alpha two" in labels
    assert "Beta leaf" not in labels
    assert sidebar.select_one(".current-page a").get_text() == "Alpha one"
    beta = BeautifulSoup(
        (output / "beta/index.html").read_text(encoding="utf-8"), "html.parser"
    )
    assert any(link.get_text() == "Beta leaf" for link in beta.select("a"))
    search = (output / "searchindex.js").read_text(encoding="utf-8")
    assert "beta/leaf" in search
    assert "alpha/one" in search
