import pytest
from django.contrib.staticfiles import finders


@pytest.mark.parametrize(
    "asset_path",
    [
        "drf_spectacular_sidecar/swagger-ui-dist/swagger-ui.css",
        "drf_spectacular_sidecar/swagger-ui-dist/swagger-ui-bundle.js",
        "drf_spectacular_sidecar/swagger-ui-dist/swagger-ui-standalone-preset.js",
        "drf_spectacular_sidecar/swagger-ui-dist/favicon-32x32.png",
        "drf_spectacular_sidecar/redoc/bundles/redoc.standalone.js",
    ],
)
def test_api_documentation_assets_are_bundled(asset_path: str) -> None:
    assert finders.find(asset_path) is not None
