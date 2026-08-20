"""Reporting minimization and guardian-consent lifecycle edge contracts."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction as django_transaction
from django.utils import timezone as django_timezone

from maru.accreditation.models import Credential, CredentialEvent
from maru.identity.models import Account, AccountRestriction
from maru.registration import guardians, reporting, restrictions
from maru.registration.models import (
    AttendeeRegistrationProfile,
    FinancialOperation,
    GuardianConsent,
    MediaReviewStatus,
    Registration,
)


def _report_row(
    *,
    reference: str,
    badge_name: str,
    display_name: str,
    country_code: str,
    state: str,
    labels: list[dict[str, str]],
    photo_status: str = MediaReviewStatus.NONE,
) -> dict[str, object]:
    return {
        "reference": reference,
        "badge_name": badge_name,
        "display_name": display_name,
        "country_code": country_code,
        "registration_state": state,
        "attendance_labels": labels,
        "profile_photo_status": photo_status,
    }


def test_badge_name_discovers_a_semantically_labeled_snapshot_answer() -> None:
    submission = SimpleNamespace(
        answers={"ordinary": "ignored", "chosen": "  Star Tail  "},
        schema_snapshot=(
            "ignore non-object legacy evidence",
            {"key": "ordinary", "label": "Biography", "purpose": "public"},
            {"key": "chosen", "label": "Badge name", "purpose": "printing"},
        ),
    )
    registration = cast(
        "Registration",
        SimpleNamespace(
            submission=submission,
            account=SimpleNamespace(display_name="Platform Name"),
        ),
    )

    assert reporting._badge_name(registration) == (
        "Star Tail",
        "registration_answer",
    )


def test_badge_name_falls_back_when_snapshot_answers_are_not_usable() -> None:
    submission = SimpleNamespace(
        answers={"badge-name": "   ", "chosen": 42},
        schema_snapshot=(
            {"key": "chosen", "label": "Badge name", "purpose": "printing"},
        ),
    )
    registration = cast(
        "Registration",
        SimpleNamespace(
            submission=submission,
            account=SimpleNamespace(display_name="Platform Name"),
        ),
    )

    assert reporting._badge_name(registration) == (
        "Platform Name",
        "platform_display_name",
    )


def test_attendee_report_filters_apply_unknown_country_level_and_search() -> None:
    volunteer = {"code": "volunteer", "label": "Volunteer", "tone": "positive"}
    attendee = {"code": "attendee", "label": "Attendee", "tone": "neutral"}
    rows = [
        _report_row(
            reference="REG-HU",
            badge_name="River Fox",
            display_name="River Person",
            country_code="HU",
            state=Registration.State.CONFIRMED,
            labels=[volunteer],
        ),
        _report_row(
            reference="REG-UNKNOWN",
            badge_name="Sky Wolf",
            display_name="Sky Person",
            country_code="",
            state=Registration.State.CHECKED_IN,
            labels=[attendee],
        ),
        _report_row(
            reference="REG-DE",
            badge_name="Forest Lynx",
            display_name="Forest Person",
            country_code="DE",
            state=Registration.State.CONFIRMED,
            labels=[attendee],
        ),
    ]

    assert reporting.filter_attendee_report_rows(
        rows,
        reporting.AttendeeReportFilters(country_code="unknown"),
    ) == [rows[1]]
    assert reporting.filter_attendee_report_rows(
        rows,
        reporting.AttendeeReportFilters(country_code="hu"),
    ) == [rows[0]]
    assert reporting.filter_attendee_report_rows(
        rows,
        reporting.AttendeeReportFilters(level="volunteer"),
    ) == [rows[0]]
    assert reporting.filter_attendee_report_rows(
        rows,
        reporting.AttendeeReportFilters(search="forest person"),
    ) == [rows[2]]
    assert not reporting.filter_attendee_report_rows(
        rows,
        reporting.AttendeeReportFilters(search="not present"),
    )


def test_attendee_report_summary_counts_minimized_categories() -> None:
    volunteer = {"code": "volunteer", "label": "Volunteer", "tone": "positive"}
    attendee = {"code": "attendee", "label": "Attendee", "tone": "neutral"}
    rows = [
        _report_row(
            reference="REG-1",
            badge_name="River",
            display_name="River Person",
            country_code="HU",
            state=Registration.State.CONFIRMED,
            labels=[volunteer, attendee],
            photo_status=MediaReviewStatus.APPROVED,
        ),
        _report_row(
            reference="REG-2",
            badge_name="Sky",
            display_name="Sky Person",
            country_code="",
            state=Registration.State.CHECKED_IN,
            labels=[attendee],
        ),
    ]

    summary = reporting.attendee_report_summary(rows)

    assert summary["coming"] == 2
    assert summary["confirmed"] == 1
    assert summary["checked_in"] == 1
    assert summary["countries"] == 1
    assert summary["volunteers"] == 1
    assert summary["approved_profile_photos"] == 1
    assert summary["country_breakdown"] == [
        {"country_code": "HU", "count": 1, "percentage": 50.0},
        {"country_code": "unknown", "count": 1, "percentage": 50.0},
    ]
    assert reporting.attendee_report_summary([])["country_breakdown"] == []


def _consent_query(consent: object) -> SimpleNamespace:
    return SimpleNamespace(
        select_related=lambda *_args: SimpleNamespace(
            filter=lambda **_kwargs: SimpleNamespace(first=lambda: consent)
        )
    )


def _prepare_guardian_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    *,
    registration_state: str = Registration.State.GUARDIAN_PENDING,
    price_minor: int = 0,
    product_count: int = 0,
    total_count: int = 0,
) -> tuple[SimpleNamespace, SimpleNamespace, MagicMock, MagicMock]:
    accepted_at = datetime(2031, 8, 10, 9, tzinfo=UTC)
    configuration = SimpleNamespace(capacity=100)
    product = SimpleNamespace(capacity=50)
    registration = SimpleNamespace(
        id=uuid4(),
        state=registration_state,
        configuration=configuration,
        product=product,
        price_minor_snapshot=price_minor,
        aggregate_version=4,
        save=MagicMock(),
    )
    consent = SimpleNamespace(
        id=uuid4(),
        registration_id=registration.id,
        status=GuardianConsent.Status.PENDING,
        expires_at=accepted_at + timedelta(days=1),
        save=MagicMock(),
    )
    monkeypatch.setattr(django_timezone, "now", lambda: accepted_at)
    monkeypatch.setattr(django_transaction, "atomic", nullcontext)
    monkeypatch.setattr(
        GuardianConsent.objects,
        "select_for_update",
        lambda: _consent_query(consent),
    )
    monkeypatch.setattr(
        Registration.objects,
        "select_for_update",
        lambda: SimpleNamespace(get=lambda **_kwargs: registration),
    )
    counts = iter((product_count, total_count))
    monkeypatch.setattr(
        Registration.objects,
        "filter",
        lambda **_kwargs: SimpleNamespace(count=lambda: next(counts)),
    )
    timeline = MagicMock()
    transition = MagicMock()
    monkeypatch.setattr(guardians, "_append_timeline", timeline)
    monkeypatch.setattr(guardians, "_publish_registration_transition", transition)
    monkeypatch.setattr(guardians, "_grant_product_entitlement", MagicMock())
    monkeypatch.setattr(
        guardians,
        "_payment_deadline",
        lambda **_kwargs: accepted_at + timedelta(hours=2),
    )
    return registration, consent, timeline, transition


def test_guardian_acceptance_requires_a_nonblank_decision_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_guardian_acceptance(monkeypatch)

    with pytest.raises(ValidationError) as raised:
        guardians.accept_guardian_consent(raw_token="valid-token", guardian_name="  ")

    assert raised.value.code == "guardian_name_required"


def test_guardian_acceptance_refuses_a_registration_that_already_moved_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_guardian_acceptance(
        monkeypatch,
        registration_state=Registration.State.CANCELLED,
    )

    with pytest.raises(ValidationError) as raised:
        guardians.accept_guardian_consent(
            raw_token="valid-token",
            guardian_name="Guardian Person",
        )

    assert raised.value.code == "guardian_consent_not_pending"


@pytest.mark.parametrize(
    ("price_minor", "product_count", "expected_state", "summary_fragment"),
    [
        (0, 50, Registration.State.WAITLISTED, "joined the waitlist"),
        (0, 0, Registration.State.CONFIRMED, "Admission is confirmed"),
        (2_500, 0, Registration.State.PAYMENT_PENDING, "Payment is the next step"),
    ],
)
def test_guardian_acceptance_selects_the_bounded_next_state(
    monkeypatch: pytest.MonkeyPatch,
    price_minor: int,
    product_count: int,
    expected_state: str,
    summary_fragment: str,
) -> None:
    registration, consent, timeline, transition = _prepare_guardian_acceptance(
        monkeypatch,
        price_minor=price_minor,
        product_count=product_count,
    )

    result = guardians.accept_guardian_consent(
        raw_token="valid-token",
        guardian_name="  Guardian Person  ",
    )

    assert result.id == registration.id
    assert registration.state == expected_state
    assert registration.aggregate_version == 5
    assert consent.status == GuardianConsent.Status.ACCEPTED
    assert consent.guardian_name_at_decision == "Guardian Person"
    assert summary_fragment in timeline.call_args.kwargs["summary"]
    transition.assert_called_once()


def _restriction_objects(kind: str) -> tuple[AccountRestriction, Account]:
    account = cast("Account", SimpleNamespace(id=uuid4()))
    actor = cast("Account", SimpleNamespace(id=uuid4()))
    restriction = cast(
        "AccountRestriction",
        SimpleNamespace(
            organization_id=uuid4(),
            edition_id=uuid4(),
            account=account,
            kind=kind,
            reason_code="bounded-policy",
            attendee_message="Attendance is unavailable under organizer policy.",
        ),
    )
    return restriction, actor


def _prepare_restriction_registrations(
    monkeypatch: pytest.MonkeyPatch,
    registrations: list[object],
) -> None:
    rows = MagicMock()
    rows.filter.return_value = rows
    rows.select_related.return_value = registrations
    locked = MagicMock()
    locked.filter.return_value = rows
    monkeypatch.setattr(
        Registration.objects,
        "select_for_update",
        lambda: locked,
    )
    monkeypatch.setattr(django_transaction, "atomic", nullcontext)
    monkeypatch.setattr(
        django_timezone,
        "now",
        lambda: datetime(2031, 8, 10, 9, tzinfo=UTC),
    )


def _prepare_empty_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    credentials = MagicMock()
    credentials.filter.return_value = credentials
    credentials.select_for_update.return_value = []
    monkeypatch.setattr(Credential.objects, "filter", lambda **_kwargs: credentials)


def test_public_profile_restriction_hides_directory_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restriction, actor = _restriction_objects(AccountRestriction.Kind.PUBLIC_PROFILE)
    profile = SimpleNamespace(
        directory_visible=True,
        directory_country_code="HU",
        directory_consent_version="directory-v1",
        directory_consent_at=datetime(2031, 1, 1, tzinfo=UTC),
        aggregate_version=2,
        save=MagicMock(),
    )
    registration = SimpleNamespace(state=Registration.State.CANCELLED)
    _prepare_restriction_registrations(monkeypatch, [registration])
    monkeypatch.setattr(
        AttendeeRegistrationProfile.objects,
        "filter",
        lambda **_kwargs: SimpleNamespace(first=lambda: profile),
    )

    assert restrictions.apply_restriction_consequences(
        restriction=restriction,
        actor=actor,
    ) == (0, 1)
    assert profile.directory_visible is False
    assert profile.directory_country_code == ""
    assert profile.directory_consent_version == ""
    assert profile.directory_consent_at is None
    assert profile.aggregate_version == 3
    profile.save.assert_called_once()


def test_attendance_restriction_revokes_checked_in_entitlements_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restriction, actor = _restriction_objects(AccountRestriction.Kind.ATTENDANCE)
    entitlements = MagicMock()
    registration = SimpleNamespace(
        state=Registration.State.CHECKED_IN,
        entitlements=entitlements,
    )
    _prepare_restriction_registrations(monkeypatch, [registration])
    _prepare_empty_credentials(monkeypatch)
    monkeypatch.setattr(
        AttendeeRegistrationProfile.objects,
        "filter",
        lambda **_kwargs: SimpleNamespace(first=lambda: None),
    )

    assert restrictions.apply_restriction_consequences(
        restriction=restriction,
        actor=actor,
    ) == (0, 0)
    entitlements.filter.assert_called_once_with(status="active")
    entitlements.filter.return_value.update.assert_called_once()


def test_attendance_restriction_cancels_and_opens_a_refund_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restriction, actor = _restriction_objects(AccountRestriction.Kind.ATTENDANCE)
    entitlements = MagicMock()
    registration = SimpleNamespace(
        state=Registration.State.CONFIRMED,
        cancelled_at=None,
        aggregate_version=7,
        entitlements=entitlements,
        save=MagicMock(),
        organization_id=restriction.organization_id,
        edition_id=restriction.edition_id,
        currency_snapshot="EUR",
        product=SimpleNamespace(id=uuid4()),
    )
    _prepare_restriction_registrations(monkeypatch, [registration])
    _prepare_empty_credentials(monkeypatch)
    monkeypatch.setattr(
        AttendeeRegistrationProfile.objects,
        "filter",
        lambda **_kwargs: SimpleNamespace(first=lambda: None),
    )
    monkeypatch.setattr(restrictions, "_record_adjustment", MagicMock())
    monkeypatch.setattr(restrictions, "_append_timeline", MagicMock())
    monkeypatch.setattr(restrictions, "_publish_registration_transition", MagicMock())
    monkeypatch.setattr(restrictions, "_promote_waitlist_for_product", MagicMock())
    monkeypatch.setattr(restrictions, "available_refund_minor", lambda _item: 2_500)
    financial_create = MagicMock()
    monkeypatch.setattr(FinancialOperation.objects, "create", financial_create)

    assert restrictions.apply_restriction_consequences(
        restriction=restriction,
        actor=actor,
    ) == (1, 0)
    assert registration.state == Registration.State.CANCELLED
    assert registration.aggregate_version == 8
    registration.save.assert_called_once()
    financial_create.assert_called_once()


def test_credential_restriction_revokes_issued_credential_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restriction, actor = _restriction_objects(AccountRestriction.Kind.CREDENTIAL)
    _prepare_restriction_registrations(monkeypatch, [])
    credential = SimpleNamespace(
        organization_id=restriction.organization_id,
        edition_id=restriction.edition_id,
        status=Credential.Status.ISSUED,
        revoked_at=None,
        revoked_by_id=None,
        revocation_reason="",
        save=MagicMock(),
    )
    credentials = MagicMock()
    credentials.filter.return_value = credentials
    credentials.select_for_update.return_value = [credential]
    monkeypatch.setattr(Credential.objects, "filter", lambda **_kwargs: credentials)
    event_create = MagicMock()
    monkeypatch.setattr(CredentialEvent.objects, "create", event_create)

    assert restrictions.apply_restriction_consequences(
        restriction=restriction,
        actor=actor,
    ) == (0, 0)
    assert credential.status == Credential.Status.REVOKED
    assert credential.revoked_by_id == actor.id
    assert credential.revocation_reason == restriction.attendee_message
    credential.save.assert_called_once()
    event_create.assert_called_once()
