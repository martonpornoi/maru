import io
from typing import Never

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings
from PIL import Image

from maru.registration.media import (
    _clamav_scan,
    process_image,
)
from maru.registration.profile_policy import MAX_FURSUIT_PHOTO_BYTES


def _image_bytes(*, mode: str = "RGBA", size: tuple[int, int] = (30, 20)) -> bytes:
    output = io.BytesIO()
    color: object = (255, 0, 0, 120) if mode == "RGBA" else 128
    Image.new(mode, size, color).save(output, format="PNG")
    return output.getvalue()


def test_process_image_reencodes_supported_modes_and_rejects_bad_input() -> None:
    processed = process_image(io.BytesIO(_image_bytes()))
    assert processed.content_type == "image/jpeg"
    assert processed.width == 30
    assert processed.height == 20
    assert processed.original_sha256 != processed.sanitized_sha256

    grayscale = process_image(io.BytesIO(_image_bytes(mode="L")))
    assert grayscale.content.read(2) == b"\xff\xd8"
    with pytest.raises(ValidationError, match="decodable"):
        process_image(io.BytesIO(b"not-an-image"))
    with pytest.raises(ValidationError, match="5 MB"):
        process_image(io.BytesIO(b"x" * (MAX_FURSUIT_PHOTO_BYTES + 1)))


class _FakeSocket:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.sent: list[bytes] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def sendall(self, value: bytes) -> None:
        self.sent.append(value)

    def recv(self, size: int) -> bytes:
        assert size == 4096
        return self.response


@override_settings(
    MARU_MEDIA_SCANNER_HOST="scanner.internal",
    MARU_MEDIA_SCANNER_PORT=3310,
    MARU_MEDIA_SCANNER_TIMEOUT_SECONDS=2,
)
def test_clamav_protocol_distinguishes_clean_infected_uncertain_and_outage(
    monkeypatch,
) -> None:
    clean = _FakeSocket(b"stream: OK")
    monkeypatch.setattr(
        "maru.registration.media.socket.create_connection",
        lambda *_args, **_kwargs: clean,
    )
    assert _clamav_scan(b"safe") == "clamav_clean"
    assert clean.sent[0] == b"zINSTREAM\0"
    assert clean.sent[-1] == b"\x00\x00\x00\x00"

    monkeypatch.setattr(
        "maru.registration.media.socket.create_connection",
        lambda *_args, **_kwargs: _FakeSocket(b"stream: Eicar FOUND"),
    )
    with pytest.raises(ValidationError, match="rejected"):
        _clamav_scan(b"unsafe")
    monkeypatch.setattr(
        "maru.registration.media.socket.create_connection",
        lambda *_args, **_kwargs: _FakeSocket(b"UNKNOWN"),
    )
    with pytest.raises(ValidationError, match="safe result"):
        _clamav_scan(b"uncertain")

    def unavailable(*args, **kwargs) -> Never:
        raise OSError("scanner unavailable")

    monkeypatch.setattr(
        "maru.registration.media.socket.create_connection",
        unavailable,
    )
    with pytest.raises(ValidationError, match="temporarily unavailable"):
        _clamav_scan(b"safe")
