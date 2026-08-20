"""Fail-closed evidence for the retired public-roster rehearsal command."""

from __future__ import annotations

from io import StringIO
from typing import TYPE_CHECKING

import pytest
from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError

from maru.demo.management.commands.seed_marucon_rehearsal import (
    RETIRED_COMMAND_MESSAGE,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

TRACKED_APP_LABELS = (
    "identity",
    "organizations",
    "events",
    "authorization",
    "participation",
    "workforce",
    "registration",
    "audit",
    "effects",
)


def _tracked_row_counts() -> dict[str, int]:
    return {
        model._meta.label_lower: model._default_manager.count()
        for app_label in TRACKED_APP_LABELS
        for model in apps.get_app_config(app_label).get_models()
    }


def _assert_retired_without_writes(
    arguments: Iterable[str] = (),
    **options: object,
) -> None:
    before = _tracked_row_counts()

    with pytest.raises(CommandError) as caught:
        call_command(
            "seed_marucon_rehearsal",
            *arguments,
            stdout=StringIO(),
            **options,
        )

    assert str(caught.value) == RETIRED_COMMAND_MESSAGE
    assert _tracked_row_counts() == before


def test_retired_marucon_rehearsal_rejects_every_legacy_invocation_without_writes(
    tmp_path: Path,
) -> None:
    missing_roster = tmp_path / "must-not-be-read.html"

    _assert_retired_without_writes()
    _assert_retired_without_writes(("--accept-public-roster",))
    _assert_retired_without_writes(
        (
            "--accept-public-roster",
            "--roster-url",
            "https://awoostria.at/about-us/our-volunteers",
        )
    )
    _assert_retired_without_writes(
        (
            "--roster-file",
            str(missing_roster),
            "--password",
            "weak",
        )
    )
    _assert_retired_without_writes(
        roster_file=missing_roster,
        roster_url="https://awoostria.at/about-us/our-volunteers",
        accept_public_roster=True,
        password="weak",
    )

    assert not missing_roster.exists()
