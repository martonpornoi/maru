"""Fail-closed PDF processing behavior for workforce onboarding."""

from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from maru.workforce.services import process_pdf


def _pdf(
    content: bytes = b"%PDF-1.4\nsynthetic\n%%EOF\n",
    *,
    content_type: str = "application/pdf",
) -> SimpleUploadedFile:
    return SimpleUploadedFile(
        "signed.pdf",
        content,
        content_type=content_type,
    )


def test_pdf_processing_rejects_size_type_and_missing_scanner() -> None:
    with pytest.raises(ValidationError, match="no larger"):
        process_pdf(_pdf(b"%PDF-" + b"x" * 1_100), max_bytes=1_024)
    with pytest.raises(ValidationError, match="Upload a PDF"):
        process_pdf(_pdf(b"not a pdf"), max_bytes=10_000)
    with pytest.raises(ValidationError, match="Upload a PDF"):
        process_pdf(
            _pdf(content_type="application/octet-stream"),
            max_bytes=10_000,
        )
    with (
        override_settings(MARU_MEDIA_SCANNER="disabled", DEBUG=False),
        pytest.raises(ValidationError, match="disabled"),
    ):
        process_pdf(_pdf(), max_bytes=10_000)


@override_settings(
    MARU_MEDIA_SCANNER="clamav",
    MARU_MEDIA_SCANNER_HOST="scanner.internal",
    MARU_MEDIA_SCANNER_PORT=3310,
    MARU_MEDIA_SCANNER_TIMEOUT_SECONDS=1,
)
def test_pdf_processing_classifies_clamav_results() -> None:
    connection = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = connection

    connection.recv.return_value = b"stream: OK"
    with patch(
        "maru.workforce.services.socket.create_connection",
        return_value=context,
    ):
        processed = process_pdf(_pdf(), max_bytes=10_000)
    assert processed.scanner_code == "clamav_clean"
    assert processed.original_filename == "signed.pdf"
    assert processed.sha256

    connection.recv.return_value = b"stream: Eicar-Test-Signature FOUND"
    with (
        patch(
            "maru.workforce.services.socket.create_connection",
            return_value=context,
        ),
        pytest.raises(ValidationError, match="safety scanner"),
    ):
        process_pdf(_pdf(), max_bytes=10_000)

    connection.recv.return_value = b"stream: UNKNOWN"
    with (
        patch(
            "maru.workforce.services.socket.create_connection",
            return_value=context,
        ),
        pytest.raises(ValidationError, match="safe result"),
    ):
        process_pdf(_pdf(), max_bytes=10_000)

    with (
        patch(
            "maru.workforce.services.socket.create_connection",
            side_effect=OSError("scanner unavailable"),
        ),
        pytest.raises(ValidationError, match="temporarily unavailable"),
    ):
        process_pdf(_pdf(), max_bytes=10_000)


@override_settings(
    MARU_MEDIA_SCANNER="clamav",
    MARU_MEDIA_SCANNER_HOST="",
)
def test_pdf_processing_requires_clamav_host() -> None:
    with pytest.raises(ValidationError, match="unavailable"):
        process_pdf(_pdf(), max_bytes=10_000)
