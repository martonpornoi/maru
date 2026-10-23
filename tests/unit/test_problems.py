from rest_framework import serializers
from rest_framework.exceptions import NotAuthenticated, ValidationError
from rest_framework.test import APIRequestFactory

from maru.core.problems import problem_exception_handler


def test_problem_handler_returns_stable_shape() -> None:
    request = APIRequestFactory().get("/")
    request.correlation_id = "1d8f179f-22e4-4ca5-a181-f70ed0d3a412"

    response = problem_exception_handler(
        NotAuthenticated("Authentication required."),
        {"request": request},
    )

    assert response is not None
    assert response.status_code == 401
    assert response.data == {
        "type": "https://docs.maru.invalid/problems/not_authenticated",
        "title": "Unauthorized",
        "status": 401,
        "detail": "Authentication required.",
        "code": "not_authenticated",
    }


def test_problem_handler_preserves_field_errors() -> None:
    response = problem_exception_handler(
        ValidationError({"email": ["Invalid value."]}),
        {},
    )

    assert response is not None
    assert response.status_code == 400
    assert response.data["errors"] == {"email": ["Invalid value."]}


def test_nested_list_problem_preserves_positions_and_error_codes() -> None:
    class ItemSerializer(serializers.Serializer):
        label = serializers.CharField()

    class EnvelopeSerializer(serializers.Serializer):
        items = ItemSerializer(many=True)

    serializer = EnvelopeSerializer(data={"items": [{"label": "Present"}, {}]})

    assert serializer.is_valid() is False
    response = problem_exception_handler(ValidationError(serializer.errors), {})

    assert response is not None
    assert response.status_code == 400
    assert response.content_type == "application/problem+json"
    assert response.data["code"] == "required"
    assert response.data["errors"] == {
        "items": [{}, {"label": ["This field is required."]}],
    }
    assert response.data["errors"]["items"][1]["label"][0].code == "required"
