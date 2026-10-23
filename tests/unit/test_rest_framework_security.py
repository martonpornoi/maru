"""Exercise the configured HTTP parser and negotiation security boundaries."""

from io import BytesIO

import pytest
from rest_framework.exceptions import NotAcceptable, ParseError
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from maru.core.problems import problem_exception_handler


@pytest.mark.parametrize("encoding", ["zlib_codec", "bz2_codec", "base64_codec"])
def test_json_rejects_non_text_charsets_before_reading_the_body(encoding: str) -> None:
    stream = BytesIO(b"{}")

    with pytest.raises(ParseError, match="Unsupported charset") as rejected:
        JSONParser().parse(stream, parser_context={"encoding": encoding})

    assert stream.tell() == 0
    response = problem_exception_handler(rejected.value, {})
    assert response is not None
    assert response.status_code == 400
    assert response.data["code"] == "parse_error"
    assert response.content_type == "application/problem+json"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_json_retains_ordinary_text_encoding_support(encoding: str) -> None:
    stream = BytesIO('{"label": "Convention"}'.encode(encoding))

    assert JSONParser().parse(stream, parser_context={"encoding": encoding}) == {
        "label": "Convention",
    }


def test_oversized_accept_parameter_cannot_enter_renderer_negotiation() -> None:
    header = 'application/json; padding="' + ";" * 512 + '"'
    request = Request(APIRequestFactory().get("/", HTTP_ACCEPT=header))

    with pytest.raises(NotAcceptable) as rejected:
        DefaultContentNegotiation().select_renderer(request, [JSONRenderer()])

    response = problem_exception_handler(rejected.value, {})
    assert response is not None
    assert response.status_code == 406
    assert response.data["code"] == "not_acceptable"


def test_oversized_accept_token_preserves_a_following_ordinary_json_choice() -> None:
    header = 'application/json; padding="' + ";" * 512 + '", application/json'
    request = Request(APIRequestFactory().get("/", HTTP_ACCEPT=header))

    renderer, media_type = DefaultContentNegotiation().select_renderer(
        request, [JSONRenderer()]
    )

    assert isinstance(renderer, JSONRenderer)
    assert media_type == "application/json"
