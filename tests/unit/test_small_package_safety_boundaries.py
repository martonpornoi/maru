"""Focused safety boundaries for the small accreditation, events, and demo apps."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError

from maru.accreditation.models import (
    Credential,
    CredentialEvent,
    OfflineCheckInOperation,
    OfflineCredentialManifest,
)
from maru.demo import fixture as demo_fixture
from maru.demo.fixture import DemoDataConflictError
from maru.demo.management.commands import seed_demo_data as seed_command
from maru.events.forms import EventEditionDetailsForm
from maru.events.models import (
    ARCHIVE_AMENDMENT_CONTENT_LENGTH,
    ArchiveAmendment,
    EditionClosureManifest,
    EditionCreationReceipt,
    EditionLifecycleTransition,
    EventEdition,
)
from maru.identity.models import Account

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.mark.parametrize(
    ("model_factory", "operation", "expected_code"),
    [
        (Credential, "delete", "protected_credential"),
        (CredentialEvent, "save", "immutable_credential_event"),
        (CredentialEvent, "delete", "protected_credential_event"),
        (OfflineCredentialManifest, "save", "immutable_offline_manifest"),
        (OfflineCredentialManifest, "delete", "protected_offline_manifest"),
        (OfflineCheckInOperation, "save", "immutable_offline_operation"),
        (OfflineCheckInOperation, "delete", "protected_offline_operation"),
    ],
)
def test_accreditation_evidence_cannot_be_mutated_or_deleted(
    model_factory: Callable[[], object],
    operation: str,
    expected_code: str,
) -> None:
    evidence = model_factory()
    if operation == "save":
        evidence._state.adding = False  # type: ignore[attr-defined]

    with pytest.raises(ValidationError) as raised:
        getattr(evidence, operation)()

    assert raised.value.code == expected_code


@pytest.mark.parametrize(
    ("model_factory", "operation", "expected_code"),
    [
        (EditionCreationReceipt, "save", "immutable_edition_creation_receipt"),
        (EditionCreationReceipt, "delete", "protected_edition_creation_receipt"),
        (EditionLifecycleTransition, "save", "immutable_lifecycle_transition"),
        (EditionLifecycleTransition, "delete", "immutable_lifecycle_transition"),
        (EditionClosureManifest, "save", "immutable_edition_closure_manifest"),
        (EditionClosureManifest, "delete", "protected_edition_closure_manifest"),
    ],
)
def test_event_lifecycle_evidence_cannot_be_mutated_or_deleted(
    model_factory: Callable[[], object],
    operation: str,
    expected_code: str,
) -> None:
    evidence = model_factory()
    if operation == "save":
        evidence._state.adding = False  # type: ignore[attr-defined]

    with pytest.raises(ValidationError) as raised:
        getattr(evidence, operation)()

    assert raised.value.code == expected_code


def test_archive_amendment_label_is_bounded_and_has_a_blank_fallback() -> None:
    edition = EventEdition(name="Aurora Tails 2027")
    long_summary = "x" * (ARCHIVE_AMENDMENT_CONTENT_LENGTH + 20)

    assert str(ArchiveAmendment(edition=edition, summary=long_summary)).endswith(
        f"{long_summary[:ARCHIVE_AMENDMENT_CONTENT_LENGTH]}…"
    )
    assert str(ArchiveAmendment(edition=edition, summary="   ")).endswith(
        "Archive amendment"
    )


@pytest.mark.parametrize(
    ("starts_on", "ends_on", "message"),
    [
        ("2027-08-10", "2027-08-09", "cannot be before"),
        ("2027-08-01", "2027-09-02", "cannot exceed 31 days"),
    ],
)
def test_edition_details_form_rejects_invalid_date_windows(
    starts_on: str,
    ends_on: str,
    message: str,
) -> None:
    form = EventEditionDetailsForm(
        data={
            "name": "Aurora Tails 2027",
            "starts_on": starts_on,
            "ends_on": ends_on,
            "time_zone": "Europe/Budapest",
            "language_codes": ["en"],
            "currency_codes": "eur",
        }
    )

    assert not form.is_valid()
    assert message in form.errors["ends_on"][0]
    with pytest.raises(ValueError, match="Validate the edition form"):
        form.edition_details()


def test_demo_seed_command_maps_password_validation_to_a_safe_command_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "maru.settings.test")

    def reject_password(_password: str) -> None:
        raise ValidationError("The password is too weak.")

    monkeypatch.setattr(seed_command, "validate_password", reject_password)

    with pytest.raises(CommandError, match="does not satisfy password validation"):
        seed_command.Command().handle(password="weak", reset_passwords=False)


def test_demo_seed_rejects_an_email_owned_by_non_fixture_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeder = demo_fixture._DemoSeeder(
        password="Z7!maru-demo-fixture-2026",
        reset_passwords=False,
    )
    collision = SimpleNamespace(id=uuid4())
    queryset = SimpleNamespace(first=lambda: collision)
    monkeypatch.setattr(
        Account.objects,
        "filter",
        lambda **_kwargs: queryset,
    )

    with pytest.raises(DemoDataConflictError, match="non-demo account"):
        seeder._account(
            key="bounded-collision",
            email="existing.person@example.invalid",
            display_name="Existing Person",
            language="en",
        )


def test_demo_seed_rejects_a_stable_id_owned_by_another_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = "stable-id-collision"
    expected_id = demo_fixture._stable_id("account", key)
    email_match = SimpleNamespace(id=expected_id)
    id_match = SimpleNamespace(email="different.person@example.invalid")

    def account_filter(**kwargs: object) -> SimpleNamespace:
        match = email_match if "email__iexact" in kwargs else id_match
        return SimpleNamespace(first=lambda: match)

    monkeypatch.setattr(Account.objects, "filter", account_filter)
    seeder = demo_fixture._DemoSeeder(
        password="Z7!maru-demo-fixture-2026",
        reset_passwords=False,
    )

    with pytest.raises(DemoDataConflictError, match="Stable demo account ID"):
        seeder._account(
            key=key,
            email="expected.person@example.invalid",
            display_name="Expected Person",
            language="en",
        )


def test_demo_seed_command_maps_fixture_conflicts_to_a_safe_command_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "maru.settings.test")
    monkeypatch.setattr(seed_command, "validate_password", lambda _password: None)

    def reject_conflicting_fixture(**_kwargs: object) -> None:
        raise DemoDataConflictError("The synthetic fixture conflicts with local data.")

    monkeypatch.setattr(seed_command, "seed_demo_data", reject_conflicting_fixture)

    with pytest.raises(CommandError, match="conflicts with local data"):
        seed_command.Command().handle(
            password="Z7!maru-demo-fixture-2026",
            reset_passwords=False,
        )
