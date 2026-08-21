"""PostgreSQL contracts for Registration media-safety evidence."""

from __future__ import annotations

import io
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import override_settings
from PIL import Image

from maru.registration.media import (
    copy_media_safety,
    dispose_storage_if_unreferenced,
    media_is_safe,
    process_image,
    record_media_safety,
)
from maru.registration.models import MediaSafetyReceipt

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _image_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", (30, 20), (255, 0, 0, 120)).save(output, format="PNG")
    return output.getvalue()


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
