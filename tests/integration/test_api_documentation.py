import pytest
from django.test import Client
from django.urls import resolve, reverse

from maru.identity.models import Account
from tests.factories import AccountFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _platform_administrator() -> Account:
    return AccountFactory(is_staff=True, is_superuser=True)


def _assert_private_headers(response) -> None:
    cache_directives = {
        directive.strip() for directive in response.headers["Cache-Control"].split(",")
    }
    assert {"private", "no-store", "max-age=0"} <= cache_directives
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"


def test_api_documentation_routes_are_stable() -> None:
    cases = (
        ("api-schema", "/api/v1/schema"),
        ("api-docs", "/api/v1/docs/"),
        ("api-redoc", "/api/v1/redoc/"),
    )
    for route_name, path in cases:
        assert reverse(route_name) == path
        assert resolve(path).url_name == route_name


def test_api_documentation_requires_a_platform_administrator() -> None:
    client = Client()

    schema = client.get(reverse("api-schema"))
    assert schema.status_code == 403
    _assert_private_headers(schema)

    for route_name in ("api-docs", "api-redoc"):
        response = client.get(reverse(route_name))
        assert response.status_code == 302
        assert response.headers["Location"] == (
            f"{reverse('staff-login')}?next={reverse(route_name)}"
        )
        assert "no-store" in response.headers["Cache-Control"]

    client.force_login(AccountFactory())
    for route_name in ("api-schema", "api-docs", "api-redoc"):
        response = client.get(reverse(route_name))
        assert response.status_code == 403
        _assert_private_headers(response)


def test_api_documentation_rechecks_persisted_platform_authority() -> None:
    administrator = _platform_administrator()
    client = Client()
    client.force_login(administrator)
    Account.objects.filter(pk=administrator.pk).update(
        account_kind=Account.Kind.PERSON,
        is_staff=False,
        is_superuser=False,
    )

    for route_name in ("api-schema", "api-docs", "api-redoc"):
        response = client.get(reverse(route_name))
        assert response.status_code == 403
        _assert_private_headers(response)


def test_platform_administrator_can_read_schema_swagger_and_redoc() -> None:
    client = Client()
    client.force_login(_platform_administrator())

    schema = client.get(
        reverse("api-schema"),
        HTTP_ACCEPT="application/vnd.oai.openapi+json",
    )
    assert schema.status_code == 200
    assert schema.json()["openapi"] == "3.1.0"
    _assert_private_headers(schema)

    swagger = client.get(reverse("api-docs"))
    assert swagger.status_code == 200
    assert swagger.headers["Content-Type"].startswith("text/html")
    swagger_html = swagger.content.decode()
    assert reverse("api-schema") in swagger_html
    assert "drf_spectacular_sidecar/swagger-ui-dist/swagger-ui.css" in swagger_html
    assert '"supportedSubmitMethods": []' in swagger_html
    assert "cdn.jsdelivr.net" not in swagger_html
    _assert_private_headers(swagger)

    redoc = client.get(reverse("api-redoc"))
    assert redoc.status_code == 200
    assert redoc.headers["Content-Type"].startswith("text/html")
    redoc_html = redoc.content.decode()
    assert reverse("api-schema") in redoc_html
    assert "drf_spectacular_sidecar/redoc/bundles/redoc.standalone.js" in redoc_html
    assert "fonts.googleapis.com" not in redoc_html
    assert "fonts.gstatic.com" not in redoc_html
    assert "cdn.jsdelivr.net" not in redoc_html
    _assert_private_headers(redoc)


def test_api_documentation_routes_are_read_only() -> None:
    client = Client()
    client.force_login(_platform_administrator())

    for route_name in ("api-schema", "api-docs", "api-redoc"):
        response = client.post(reverse(route_name))
        assert response.status_code == 405
        _assert_private_headers(response)
