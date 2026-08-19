from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from maru.core.cors import RegistrationClientCorsMiddleware


@override_settings(
    MARU_REGISTRATION_CLIENT_ORIGINS=["https://register.example"],
)
def test_registration_client_cors_allows_only_exact_configured_api_origin() -> None:
    def response(request):
        del request
        return HttpResponse("ok")

    middleware = RegistrationClientCorsMiddleware(response)
    request = RequestFactory().options(
        "/api/v1/public/csrf",
        HTTP_ORIGIN="https://register.example",
    )
    response = middleware(request)
    assert response.status_code == 204
    assert response["Access-Control-Allow-Origin"] == "https://register.example"
    assert response["Access-Control-Allow-Credentials"] == "true"
    assert "Origin" in response["Vary"]

    denied = middleware(
        RequestFactory().get(
            "/api/v1/public/csrf",
            HTTP_ORIGIN="https://attacker.example",
        )
    )
    assert "Access-Control-Allow-Origin" not in denied

    non_api = middleware(
        RequestFactory().get(
            "/admin/workspace/",
            HTTP_ORIGIN="https://register.example",
        )
    )
    assert "Access-Control-Allow-Origin" not in non_api

    for private_documentation_path in (
        "/api/v1/schema",
        "/api/v1/schema/",
        "/api/v1/docs",
        "/api/v1/docs/",
        "/api/v1/redoc",
        "/api/v1/redoc/",
    ):
        private_documentation = middleware(
            RequestFactory().get(
                private_documentation_path,
                HTTP_ORIGIN="https://register.example",
            )
        )
        assert "Access-Control-Allow-Origin" not in private_documentation
