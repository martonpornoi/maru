"""Closed-catalog tests for the legacy Applications workflow."""

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from maru.applications import queries
from maru.applications.legacy_targets import (
    LEGACY_APPLICATION_TARGET_KINDS,
    is_legacy_application_target,
)


def test_legacy_application_targets_are_an_explicit_closed_catalog() -> None:
    assert LEGACY_APPLICATION_TARGET_KINDS == (
        "merch_submission",
        "dj_set",
        "fursuit_dance_competition",
        "maid_cafe",
        "adult_fursuit_striptease",
        "volunteer",
        "feedback",
        "idea",
        "damage_report",
        "helper",
    )
    assert all(
        is_legacy_application_target(kind) for kind in LEGACY_APPLICATION_TARGET_KINDS
    )


def test_programme_target_is_not_admitted_by_the_legacy_workflow() -> None:
    assert not is_legacy_application_target("programme_item")
    assert not is_legacy_application_target("unregistered_future_target")


def test_legacy_starter_projection_omits_a_programme_starter() -> None:
    edition = SimpleNamespace(
        adoption_profile_code="future-profile",
        adoption_profile_version=2,
    )
    legacy = SimpleNamespace(is_external=False, target_adapter_kind="dj_set")
    programme = SimpleNamespace(
        is_external=False,
        target_adapter_kind="programme_item",
    )
    external = SimpleNamespace(is_external=True, target_adapter_kind=None)
    with (
        patch.object(queries, "_authorized_edition", return_value=edition),
        patch.object(
            queries,
            "starter_catalog_for_profile",
            return_value=(legacy, programme, external),
        ),
    ):
        result = queries.application_starters(
            actor=SimpleNamespace(),
            organization_id=uuid4(),
            edition_id=uuid4(),
        )

    assert result == (legacy, external)
