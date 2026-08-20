import io
from typing import Never
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import override_settings
from PIL import Image

from maru.registration.media import (
    _clamav_scan,
    copy_media_safety,
    dispose_storage_if_unreferenced,
    media_is_safe,
    process_image,
    record_media_safety,
)
from maru.registration.models import MediaSafetyReceipt
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


@pytest.mark.django_db(transaction=True)
def test_media_safety_receipt_copy_lookup_and_reference_aware_disposal() -> None:
    processed = process_image(io.BytesIO(_image_bytes()))
    source_id = uuid4()
    source = record_media_safety(
        processed=processed,
        organization_id=uuid4(),
        edition_id=uuid4(),
        account_id=uuid4(),
        media_kind=MediaSafetyReceipt.MediaKind.PROFILE_PHOTO,
        media_id=source_id,
        storage_name="private/source.jpg",
    )
    assert source.scanner_code == "test_clean"
    with pytest.raises(ValidationError, match="retention"):
        source.delete()
    with override_settings(MEDIA_REQUIRE_SAFETY_RECEIPT=True):
        assert media_is_safe(
            media_kind=source.media_kind,
            media_id=source.media_id,
            storage_name=source.storage_name,
        )
        assert not media_is_safe(
            media_kind=source.media_kind,
            media_id=uuid4(),
            storage_name=source.storage_name,
        )

    copied = copy_media_safety(
        source_kind=source.media_kind,
        source_id=source.media_id,
        source_storage_name=source.storage_name,
        target_kind=MediaSafetyReceipt.MediaKind.FURSUIT_PHOTO,
        target_id=uuid4(),
        target_storage_name="private/target.jpg",
        organization_id=source.organization_id,
        edition_id=source.edition_id,
        account_id=source.account_id,
    )
    assert copied is not None
    assert copied.scanner_code == "approved_reuse:test_clean"
    assert (
        copy_media_safety(
            source_kind=source.media_kind,
            source_id=uuid4(),
            source_storage_name=source.storage_name,
            target_kind=source.media_kind,
            target_id=uuid4(),
            target_storage_name="private/missing.jpg",
            organization_id=source.organization_id,
            edition_id=source.edition_id,
            account_id=source.account_id,
        )
        is None
    )

    assert not dispose_storage_if_unreferenced("")
    storage_name = default_storage.save(
        f"test-media/{uuid4()}.bin",
        ContentFile(b"temporary"),
    )
    assert dispose_storage_if_unreferenced(storage_name)
    assert not default_storage.exists(storage_name)
    assert not dispose_storage_if_unreferenced(storage_name)
