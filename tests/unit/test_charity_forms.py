from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError

from maru.charities.forms import CharityEditionLocalDateTimeField


def test_charity_media_expiry_requires_exact_unambiguous_edition_local_time() -> None:
    field = CharityEditionLocalDateTimeField(
        required=False,
        zone_name="Europe/Budapest",
    )

    with pytest.raises(ValidationError):
        field.clean(" 2026-08-09T12:00")
    with pytest.raises(ValidationError):
        field.clean("2026-10-25T02:30")
    with pytest.raises(ValidationError):
        field.clean("2026-03-29T02:30")

    parsed = field.clean("2026-08-09T12:00")
    assert parsed is not None
    assert parsed.utcoffset() == timedelta(hours=2)
    assert field.prepare_value(parsed) == "2026-08-09T12:00"
