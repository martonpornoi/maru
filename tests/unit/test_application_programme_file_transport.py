"""Real CSRF and raw-body boundaries over explicit database-free command seams."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.core import signing
from django.db import DatabaseError
from django.middleware.csrf import get_token
from django.test import RequestFactory

from maru.applications import programme_file_forms as forms
from maru.applications import programme_file_transport as transport
from maru.applications.programme_reference_sources import (
    ProgrammeAnswerReferenceIntent,
    ProgrammeAnswerReferenceRequest,
)

PDF = b"%PDF-1.7\nSynthetic only.\n%%EOF\n"


@pytest.fixture
def world(monkeypatch):
    scope = ProgrammeAnswerReferenceRequest(
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), transport._SOURCE
    )
    intent = ProgrammeAnswerReferenceIntent(3, 2, 1, uuid4())
    upload, result = Mock(), Mock(return_value=object())
    monkeypatch.setattr(transport.commands, "upload_and_use_programme_file", upload)
    monkeypatch.setattr(transport.commands, "get_programme_file_upload_result", result)
    return SimpleNamespace(
        scope=scope,
        intent=intent,
        token=forms._encode(scope, intent, purpose="upload"),
        upload=upload,
        result=result,
    )


def incoming(world, *, method="PUT", data=PDF, csrf=True, **headers):
    request = RequestFactory().generic(
        method, "/synthetic-file/", data=data, content_type="application/pdf"
    )
    request.user = SimpleNamespace(pk=world.scope.actor_id, is_authenticated=True)
    request.META["HTTP_X_MARU_FILE_INTENT"] = world.token
    if csrf:
        request.META["HTTP_X_CSRFTOKEN"] = get_token(request)
        request.COOKIES["csrftoken"] = request.META["CSRF_COOKIE"]
    request.META.update(headers)
    # Match the normal WSGI construction for tests changing the declared media type.
    request._set_content_type_params(request.META)
    reader = Mock(wraps=request.read)
    request.read = reader
    response = transport.programme_file_intake(
        request,
        world.scope.organization_id,
        world.scope.edition_id,
        world.scope.proposal_id,
        world.scope.question_id,
    )
    return response, reader, request


def test_csrf_header_allows_put_without_framework_parsing_body(world):
    world.upload.side_effect = lambda **kwargs: kwargs["read_bytes"]()
    response, reader, request = incoming(world)
    assert response.status_code == 200
    assert b'"saved"' in response.content
    reader.assert_called_once_with(transport.MAX_PROGRAMME_FILE_BYTES + 1)
    assert not request.POST
    assert not request.FILES
    assert world.upload.call_args.kwargs["intent"] == world.intent
    assert "no-store" in response["Cache-Control"]
    assert response["X-Content-Type-Options"] == "nosniff"
    assert transport.programme_file_intake._non_atomic_requests == {"default"}


@pytest.mark.parametrize(
    "options",
    [
        {"csrf": False},
        {"HTTP_X_CSRFTOKEN": "invalid"},
        {"HTTP_ORIGIN": "https://foreign.invalid"},
    ],
)
def test_real_csrf_rejects_before_command_or_body(world, options):
    response, reader, _ = incoming(world, **options)
    assert response.status_code == 403
    reader.assert_not_called()
    world.upload.assert_not_called()


@pytest.mark.parametrize(
    "headers",
    [
        {"QUERY_STRING": "receipt=untrusted"},
        {"HTTP_CONTENT_ENCODING": "gzip"},
        {"CONTENT_TYPE": "multipart/form-data; boundary=private"},
        {"CONTENT_TYPE": "application/pdf; filename=secret.pdf"},
        {"CONTENT_TYPE": "text/plain"},
        {"CONTENT_LENGTH": ""},
        {"CONTENT_LENGTH": "-1"},
        {"CONTENT_LENGTH": "0"},
        {"CONTENT_LENGTH": "99999999999999999999999"},
        {"CONTENT_LENGTH": str(transport.MAX_PROGRAMME_FILE_BYTES + 1)},
        {"HTTP_X_MARU_FILE_INTENT": ""},
        {"HTTP_X_MARU_FILE_INTENT": "tampered"},
    ],
)
def test_transport_refuses_before_command_body(world, headers):
    response, reader, _ = incoming(world, **headers)
    assert response.status_code in {400, 404}
    reader.assert_not_called()
    world.upload.assert_not_called()


@pytest.mark.parametrize("method", ["POST", "DELETE", "PATCH", "HEAD"])
def test_unsupported_methods_never_reach_upload(world, method):
    response, reader, _ = incoming(world, method=method)
    assert response.status_code == 405
    reader.assert_not_called()
    world.upload.assert_not_called()


@pytest.mark.parametrize("length", [1, len(PDF) + 1])
def test_actual_body_must_equal_declared_bound(world, length):
    world.upload.side_effect = lambda **kwargs: kwargs["read_bytes"]()
    response, reader, _ = incoming(world, CONTENT_LENGTH=str(length))
    assert response.status_code == 400
    reader.assert_called_once()


@pytest.mark.parametrize("recorded", [False, True])
def test_recovery_is_body_free_original_intent_without_new_write(world, recorded):
    world.result.return_value = object() if recorded else None
    response, reader, _ = incoming(world, method="GET", data=b"")
    assert response.status_code == 200
    assert (b'"saved"' if recorded else b'"pending"') in response.content
    reader.assert_not_called()
    world.upload.assert_not_called()
    assert world.result.call_args.kwargs["intent"] == world.intent
    assert world.result.call_args.kwargs["request"].source_channel == transport._SOURCE


def test_get_with_declared_body_is_not_recovery(world):
    response, reader, _ = incoming(world, method="GET")
    assert response.status_code == 400
    reader.assert_not_called()
    world.result.assert_not_called()


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (transport.Denied, 404),
        (transport._CONFLICTS[0], 409),
        (transport.ProgrammeFileUnavailableError, 503),
        (DatabaseError, 503),
        (transport.ProgrammeFileRejectedError, 400),
    ],
)
def test_owner_failure_is_minimized_and_does_not_imply_no_commit(world, error, status):
    world.upload.side_effect = error("DO NOT DISCLOSE scanner or custody detail")
    response, reader, _ = incoming(world)
    assert response.status_code == status
    assert b"DO NOT DISCLOSE" not in response.content
    assert b'"unconfirmed"' in response.content
    reader.assert_not_called()


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "edition_id", "proposal_id", "question_id"]
)
def test_original_proof_is_scope_bound(world, field):
    with pytest.raises(forms.Denied):
        forms._decode(
            replace(world.scope, **{field: uuid4()}), world.token, purpose="upload"
        )


def test_proof_does_not_bind_new_correlation_or_claim_permission(world):
    assert (
        forms._decode(
            replace(world.scope, correlation_id=uuid4()), world.token, purpose="upload"
        )
        == world.intent
    )
    with pytest.raises(forms.Denied):
        forms._decode(world.scope, world.token, purpose="clear")


@pytest.mark.parametrize("token", ["", ".compressed", "x" * 2049, "\N{SNOWMAN}", None])
def test_invalid_proof_refused(world, token):
    with pytest.raises(forms.Denied):
        forms._decode(world.scope, token, purpose="upload")


@pytest.mark.parametrize("version", [True, 0, -1, 2**63, "3", None])
def test_signed_but_invalid_version_is_not_accepted(world, version):
    payload = signing.loads(world.token, salt=forms._salt("upload"))
    payload["intent"]["expected_version"] = version
    token = signing.dumps(payload, salt=forms._salt("upload"))
    with pytest.raises(forms.Denied):
        forms._decode(world.scope, token, purpose="upload")


def test_clear_requires_deliberate_confirmation_and_bounded_proof(world):
    assert not forms.ProgrammeFileClearForm({"token": world.token}).is_valid()
    assert forms.ProgrammeFileClearForm(
        {"token": world.token, "confirm": "on"}
    ).is_valid()
