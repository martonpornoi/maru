import json
import re
from pathlib import Path

from django.contrib.staticfiles import finders
from PIL import Image

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BRAND_STATIC_PREFIX = "core/brand/"
EXPECTED_IMAGES = {
    "android-chrome-192x192.png": (192, 192),
    "android-chrome-512x512.png": (512, 512),
    "apple-touch-icon.png": (180, 180),
    "favicon.ico": (48, 48),
    "maru_rectangle_full_logo.png": (2918, 825),
    "maru_square_full_logo.png": (1254, 1254),
    "maru_square_logo_no_text.png": (836, 835),
}
PLATFORM_TEMPLATES = (
    "src/maru/core/templates/core/home.html",
    "src/maru/core/templates/core/login.html",
    "src/maru/registration/templates/registration/base_public.html",
    "src/maru/templates/admin/base_site.html",
)
PALETTE_PATTERN = re.compile(r"--maru-(?:navy|gold|ivory)-\d+:\s*(#[0-9a-f]{6});")


def _static_path(relative_path: str) -> Path:
    found = finders.find(relative_path)
    assert isinstance(found, str)
    return Path(found)


def _linear_channel(channel: int) -> float:
    value = channel / 255
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _luminance(color: str) -> float:
    channels = (int(color[index : index + 2], 16) for index in range(1, len(color), 2))
    red, green, blue = (_linear_channel(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(foreground: str, background: str) -> float:
    brighter, darker = sorted(
        (_luminance(foreground), _luminance(background)), reverse=True
    )
    return (brighter + 0.05) / (darker + 0.05)


def test_brand_images_are_discoverable_and_keep_owned_dimensions() -> None:
    for filename, dimensions in EXPECTED_IMAGES.items():
        with Image.open(_static_path(BRAND_STATIC_PREFIX + filename)) as image:
            assert image.size == dimensions


def test_brand_manifest_uses_deployable_static_paths_and_colors() -> None:
    manifest = json.loads(
        _static_path(BRAND_STATIC_PREFIX + "site.webmanifest").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["name"] == "Maru Convention Planning"
    assert manifest["short_name"] == "Maru"
    assert manifest["theme_color"] == "#071B3A"
    assert manifest["background_color"] == "#FAF3E3"
    assert manifest["display"] == "standalone"
    assert manifest["icons"] == [
        {
            "src": "/static/core/brand/android-chrome-192x192.png",
            "sizes": "192x192",
            "type": "image/png",
        },
        {
            "src": "/static/core/brand/android-chrome-512x512.png",
            "sizes": "512x512",
            "type": "image/png",
        },
    ]


def test_staff_console_palette_matches_canonical_brand_scale() -> None:
    canonical = _static_path("core/brand.css").read_text(encoding="utf-8")
    frontend = (REPOSITORY_ROOT / "frontends/staff-console/src/styles.css").read_text(
        encoding="utf-8"
    )

    assert PALETTE_PATTERN.findall(canonical) == PALETTE_PATTERN.findall(frontend)
    assert canonical.count("--maru-navy-900: #071b3a;") == 1
    assert canonical.count("--maru-gold-600: #b9822e;") == 1
    assert canonical.count("--maru-ivory-200: #faf3e3;") == 1


def test_approved_brand_text_pairs_meet_wcag_aa() -> None:
    assert _contrast("#071b3a", "#faf3e3") >= 4.5
    assert _contrast("#faf3e3", "#071b3a") >= 4.5
    assert _contrast("#071b3a", "#b9822e") >= 4.5
    assert _contrast("#77511a", "#faf3e3") >= 4.5
    assert _contrast("#b9822e", "#faf3e3") < 4.5


def test_platform_templates_include_brand_metadata() -> None:
    for relative_path in PLATFORM_TEMPLATES:
        source = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        assert "core/brand/favicon.ico" in source
        assert "core/brand/apple-touch-icon.png" in source
        assert "core/brand/site.webmanifest" in source
        assert "core/brand.css" in source
        assert 'name="theme-color" content="#071B3A"' in source
