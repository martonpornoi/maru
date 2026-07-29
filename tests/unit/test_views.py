from unittest.mock import MagicMock, patch

from django.db.utils import OperationalError
from rest_framework.test import APIClient


def test_platform_home_is_a_browser_friendly_start_page() -> None:
    response = APIClient().get("/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    content = response.content.decode()
    assert "Maru is running." in content
    assert "Use this page to enter the local Maru environment" in content
    assert "For example:" in content
    assert 'href="/health/ready"' in content
    assert 'href="/api/v1/schema"' in content
    assert 'href="/admin/"' in content
    assert 'href="/staff/"' in content


def test_liveness_does_not_touch_dependencies() -> None:
    response = APIClient().get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "X-Request-ID" in response


def test_build_info_contains_only_release_identity(settings: object) -> None:
    settings.BUILD_VERSION = "test-release"  # type: ignore[attr-defined]
    settings.BUILD_COMMIT = "abc123"  # type: ignore[attr-defined]

    response = APIClient().get("/api/v1/meta/build")

    assert response.status_code == 200
    assert response.json() == {
        "service": "maru",
        "version": "test-release",
        "commit": "abc123",
    }


@patch("maru.core.views.connection.cursor")
def test_readiness_checks_database(cursor: MagicMock) -> None:
    response = APIClient().get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "dependencies": {"database": "ok"},
    }
    cursor.return_value.__enter__.return_value.execute.assert_called_once_with(
        "SELECT 1"
    )


@patch(
    "maru.core.views.connection.cursor",
    side_effect=OperationalError("private connection detail"),
)
def test_readiness_returns_safe_failure(cursor: MagicMock) -> None:
    response = APIClient().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {"database": "unavailable"},
    }
