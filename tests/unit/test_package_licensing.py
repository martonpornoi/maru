from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LICENSE_PATH = REPOSITORY_ROOT / "LICENSE"
NOTICE_PATH = REPOSITORY_ROOT / "THIRD_PARTY_NOTICES.md"
BUNDLE_DIRECTORY = (
    REPOSITORY_ROOT / "src" / "maru" / "core" / "static" / "staff-console"
)

EXPECTED_MIT_LICENSE = """MIT License

Copyright (c) Meta Platforms, Inc. and affiliates.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def test_pep639_metadata_declares_every_distributed_license_file() -> None:
    configuration = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    metadata = configuration["project"]

    assert metadata["license"] == "Apache-2.0 AND MIT"
    assert metadata["license-files"] == ["LICENSE", "THIRD_PARTY_NOTICES.md"]
    for relative_path in metadata["license-files"]:
        assert (REPOSITORY_ROOT / relative_path).is_file()
    assert configuration["tool"]["setuptools"]["package-data"] == {
        "*": ["templates/**/*.html", "static/**/*"]
    }


def test_staff_console_notice_matches_locked_runtime_components() -> None:
    package = json.loads(
        (REPOSITORY_ROOT / "frontends" / "staff-console" / "package.json").read_text(
            encoding="utf-8"
        )
    )
    lock = (
        REPOSITORY_ROOT / "frontends" / "staff-console" / "pnpm-lock.yaml"
    ).read_text(encoding="utf-8")
    notice = NOTICE_PATH.read_text(encoding="utf-8")

    assert package["dependencies"] == {
        "react": "19.2.8",
        "react-dom": "19.2.8",
    }
    assert re.search(r"^  scheduler@0\.27\.0:$", lock, re.MULTILINE)
    for component, version in (
        ("React", "19.2.8"),
        ("React DOM", "19.2.8"),
        ("Scheduler", "0.27.0"),
    ):
        assert f"| {component} | `{version}` |" in notice
    assert notice.endswith(EXPECTED_MIT_LICENSE)


def test_browser_bundle_preserves_the_bundled_runtime_license() -> None:
    bundled_notice = (BUNDLE_DIRECTORY / "THIRD_PARTY_NOTICES.md").read_text(
        encoding="utf-8"
    )

    expected_banner = (
        "/*! Maru is Apache-2.0: see LICENSE.txt. Bundled dependency licenses: "
        "see THIRD_PARTY_NOTICES.md. */"
    )
    javascript_files = tuple(sorted(BUNDLE_DIRECTORY.rglob("*.js")))
    assert javascript_files
    for javascript_file in javascript_files:
        assert javascript_file.read_text(encoding="utf-8").startswith(expected_banner)
    assert (BUNDLE_DIRECTORY / "LICENSE.txt").read_bytes() == LICENSE_PATH.read_bytes()
    for evidence in (
        "## react - 19.2.8 (MIT)",
        "## react-dom - 19.2.8 (MIT)",
        "## scheduler - 0.27.0 (MIT)",
        "MIT License",
        "Copyright (c) Meta Platforms, Inc. and affiliates.",
        "The above copyright notice and this permission notice shall be included",
        'THE SOFTWARE IS PROVIDED "AS IS"',
    ):
        assert evidence in bundled_notice


def test_generated_documentation_carries_locked_asset_licenses() -> None:
    locked_packages = {
        package["name"]: package["version"]
        for package in tomllib.loads(
            (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8")
        )["package"]
    }
    notice = (
        REPOSITORY_ROOT / "docs" / "operations" / "generated-documentation-licenses.md"
    ).read_text(encoding="utf-8")
    license_directory = REPOSITORY_ROOT / "docs" / "_static" / "licenses"
    assert (license_directory / "Maru-Apache-2.0-LICENSE.txt").read_bytes() == (
        LICENSE_PATH.read_bytes()
    )
    assert "| Maru | This build |" in notice
    expected = {
        "Sphinx": ("sphinx", "Sphinx-LICENSE.txt", "BSD-2-Clause"),
        "sphinxcontrib-mermaid": (
            "sphinxcontrib-mermaid",
            "Sphinxcontrib-Mermaid-LICENSE.txt",
            "BSD-2-Clause",
        ),
        "Furo": ("furo", "Furo-LICENSE.txt", "MIT"),
        "Pygments": ("pygments", "Pygments-LICENSE.txt", "BSD-2-Clause"),
    }

    for display_name, (package_name, license_file, license_name) in expected.items():
        version = locked_packages[package_name]
        assert f"| {display_name} | `{version}` |" in notice
        assert license_name in notice
        assert (license_directory / license_file).is_file()

    mermaid_extension_license = (
        license_directory / "Sphinxcontrib-Mermaid-LICENSE.txt"
    ).read_bytes()
    assert hashlib.sha256(mermaid_extension_license).hexdigest() == (
        "cd6008a1fe5026aff77f773ca6591951060a35e0dc79aeee5bcf3cd27fad6ef9"
    )

    embedded_components = {
        "normalize.css": (
            "8.0.1",
            "Normalize-LICENSE.txt",
            "Copyright © Nicolas Gallagher and Jonathan Neal",
        ),
        "Gumshoe": (
            "5.1.2",
            "Gumshoe-LICENSE.txt",
            "Copyright (c) 2019 Chris Ferdinandi",
        ),
    }
    for display_name, (
        version,
        license_file,
        copyright_notice,
    ) in embedded_components.items():
        assert f"| {display_name} | `{version}` |" in notice
        license_text = (license_directory / license_file).read_text(encoding="utf-8")
        assert copyright_notice in license_text
        assert "Permission is hereby granted, free of charge" in license_text
        assert 'THE SOFTWARE IS PROVIDED "AS IS"' in license_text


def test_container_carries_project_and_bundled_component_notices() -> None:
    dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert (
        "COPY pyproject.toml uv.lock README.md LICENSE THIRD_PARTY_NOTICES.md ./"
        in (dockerfile)
    )
    assert (
        "COPY --chown=maru:maru LICENSE README.md THIRD_PARTY_NOTICES.md /app/"
        in dockerfile
    )
