"""Fail-closed malware scanning and safe raster re-encoding."""

from __future__ import annotations

import hashlib
import io
import socket
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError
from PIL import __version__ as pillow_version

from maru.registration.models import (
    AttendeeFursuit,
    AttendeeRegistrationProfile,
    MediaSafetyReceipt,
)
from maru.registration.profile_policy import MAX_FURSUIT_PHOTO_BYTES

MAX_IMAGE_PIXELS = 20_000_000
MAX_RENDER_DIMENSION = 2048
CLAMAV_CHUNK_SIZE = 64 * 1024
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


class ReadableUpload(Protocol):
    def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True, slots=True)
class ProcessedImage:
    content: ContentFile[bytes]
    original_sha256: str
    sanitized_sha256: str
    scanner_code: str
    content_type: str
    width: int
    height: int
    byte_count: int


def _clamav_scan(data: bytes) -> str:
    host = settings.MARU_MEDIA_SCANNER_HOST
    port = settings.MARU_MEDIA_SCANNER_PORT
    if not host:
        raise ValidationError(
            "Media scanning is unavailable.",
            code="media_scanner_unavailable",
        )
    try:
        with socket.create_connection(
            (host, port),
            timeout=settings.MARU_MEDIA_SCANNER_TIMEOUT_SECONDS,
        ) as connection:
            connection.sendall(b"zINSTREAM\0")
            for offset in range(0, len(data), CLAMAV_CHUNK_SIZE):
                chunk = data[offset : offset + CLAMAV_CHUNK_SIZE]
                connection.sendall(len(chunk).to_bytes(4, "big") + chunk)
            connection.sendall((0).to_bytes(4, "big"))
            response = connection.recv(4096)
    except OSError as error:
        raise ValidationError(
            "Media scanning is temporarily unavailable.",
            code="media_scanner_unavailable",
        ) from error
    if b" FOUND" in response:
        raise ValidationError(
            "The uploaded file was rejected by the safety scanner.",
            code="media_malware_detected",
        )
    if b" OK" not in response:
        raise ValidationError(
            "Media scanning did not return a safe result.",
            code="media_scanner_uncertain",
        )
    return "clamav_clean"


def _scan(data: bytes) -> str:
    scanner = settings.MARU_MEDIA_SCANNER
    if scanner == "test_clean" and settings.DEBUG is False:
        return "test_clean"
    if scanner == "local_rehearsal_clean" and settings.DEBUG is True:
        return "local_rehearsal_clean_unscanned"
    if scanner == "clamav":
        return _clamav_scan(data)
    raise ValidationError(
        "Media uploads are disabled until a malware scanner is configured.",
        code="media_scanner_unavailable",
    )


def process_image(upload: ReadableUpload) -> ProcessedImage:
    data = upload.read(MAX_FURSUIT_PHOTO_BYTES + 1)
    if len(data) > MAX_FURSUIT_PHOTO_BYTES:
        raise ValidationError(
            "Use an image no larger than 5 MB.",
            code="media_file_too_large",
        )
    scanner_code = _scan(data)
    original_sha256 = hashlib.sha256(data).hexdigest()
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.load()
            safe = ImageOps.exif_transpose(source)
            if safe.width * safe.height > MAX_IMAGE_PIXELS:
                raise ValidationError(
                    "The image dimensions are too large.",
                    code="media_dimensions_too_large",
                )
            safe.thumbnail(
                (MAX_RENDER_DIMENSION, MAX_RENDER_DIMENSION),
                Image.Resampling.LANCZOS,
            )
            if safe.mode not in ("RGB", "L"):
                background = Image.new("RGB", safe.size, "white")
                if "A" in safe.getbands():
                    background.paste(safe, mask=safe.getchannel("A"))
                else:
                    background.paste(safe.convert("RGB"))
                safe = background
            else:
                safe = safe.convert("RGB")
            width, height = safe.size
            output = io.BytesIO()
            safe.save(
                output,
                format="JPEG",
                quality=88,
                optimize=True,
                progressive=True,
            )
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValidationError(
            "The upload is not a safely decodable image.",
            code="media_decode_failed",
        ) from error
    sanitized = output.getvalue()
    return ProcessedImage(
        content=ContentFile(sanitized, name="sanitized.jpg"),
        original_sha256=original_sha256,
        sanitized_sha256=hashlib.sha256(sanitized).hexdigest(),
        scanner_code=scanner_code,
        content_type="image/jpeg",
        width=width,
        height=height,
        byte_count=len(sanitized),
    )


def record_media_safety(
    *,
    processed: ProcessedImage,
    organization_id: UUID,
    edition_id: UUID,
    account_id: UUID,
    media_kind: str,
    media_id: UUID,
    storage_name: str,
) -> MediaSafetyReceipt:
    return MediaSafetyReceipt.objects.create(
        organization_id=organization_id,
        edition_id=edition_id,
        account_id=account_id,
        media_kind=media_kind,
        media_id=media_id,
        storage_name=storage_name,
        original_sha256=processed.original_sha256,
        sanitized_sha256=processed.sanitized_sha256,
        scanner_code=processed.scanner_code,
        decoder_version=f"Pillow {pillow_version}",
        content_type=processed.content_type,
        width=processed.width,
        height=processed.height,
        byte_count=processed.byte_count,
        scanned_at=timezone.now(),
    )


def copy_media_safety(
    *,
    source_kind: str,
    source_id: UUID,
    source_storage_name: str,
    target_kind: str,
    target_id: UUID,
    target_storage_name: str,
    organization_id: UUID,
    edition_id: UUID,
    account_id: UUID,
) -> MediaSafetyReceipt | None:
    source = (
        MediaSafetyReceipt.objects.filter(
            media_kind=source_kind,
            media_id=source_id,
            storage_name=source_storage_name,
        )
        .order_by("-scanned_at", "-id")
        .first()
    )
    if source is None:
        return None
    return MediaSafetyReceipt.objects.create(
        organization_id=organization_id,
        edition_id=edition_id,
        account_id=account_id,
        media_kind=target_kind,
        media_id=target_id,
        storage_name=target_storage_name,
        original_sha256=source.original_sha256,
        sanitized_sha256=source.sanitized_sha256,
        scanner_code=f"approved_reuse:{source.scanner_code}",
        decoder_version=source.decoder_version,
        content_type=source.content_type,
        width=source.width,
        height=source.height,
        byte_count=source.byte_count,
        scanned_at=timezone.now(),
    )


def media_is_safe(*, media_kind: str, media_id: UUID, storage_name: str) -> bool:
    if not settings.MEDIA_REQUIRE_SAFETY_RECEIPT:
        return True
    return MediaSafetyReceipt.objects.filter(
        media_kind=media_kind,
        media_id=media_id,
        storage_name=storage_name,
    ).exists()


def dispose_storage_if_unreferenced(storage_name: str) -> bool:
    """Delete a media object only after every profile/fursuit reference is gone."""

    if not storage_name:
        return False
    referenced = (
        AttendeeRegistrationProfile.objects.filter(profile_photo=storage_name).exists()
        or AttendeeFursuit.objects.filter(photo=storage_name).exists()
    )
    if referenced or not default_storage.exists(storage_name):
        return False
    default_storage.delete(storage_name)
    return True
