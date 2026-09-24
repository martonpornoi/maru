"""Native stopped Venue admission and retained physical-obligation correction."""

from contextlib import contextmanager
from dataclasses import replace
from functools import partial
from importlib import import_module
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from psycopg import sql

from maru.events import adoption
from maru.events.programme_stop_readiness import programme_stop_preparation_is_ready
from maru.venues import services
from maru.venues.models import VenueBooking, VenueBookingOccupancy
from maru.venues.services import (
    approve_venue_booking,
    cancel_venue_booking,
    publish_venue_booking,
    withdraw_venue_booking_publication,
)
from tests.factories import EventEditionFactory
from tests.integration import test_venues as scenarios
from tests.integration.test_scheduling_programme_stop import _terminal
from tests.rehearsals.programme_candidate import PROGRAMME_REHEARSAL_PROFILE
from tests.support.programme_schema import admit_transaction_local_schema_candidate

pytestmark = [pytest.mark.django_db, pytest.mark.integration]
GUARDS = import_module("maru.venues.migrations.0009_programme_stop_boundary")


@pytest.fixture
def booked(monkeypatch):
    admit_transaction_local_schema_candidate(monkeypatch)
    monkeypatch.setattr(
        adoption,
        "ADOPTION_PROFILES",
        {
            **adoption.ADOPTION_PROFILES,
            ("programme_operations", 1): PROGRAMME_REHEARSAL_PROFILE,
        },
    )
    monkeypatch.setattr(
        scenarios,
        "EventEditionFactory",
        partial(EventEditionFactory, adoption_profile_code="programme_operations"),
    )
    scope = scenarios._scope()
    space = scenarios._selected_space(scope)
    start = scenarios._configure_schedule(scope, space)
    booking = scenarios._create_booking(scope, space, start=start)
    request = {
        "organization_id": scope.edition.organization_id,
        "edition_id": scope.edition.id,
        "space_selection_id": space.id,
        "booking_id": booking.object_id,
        "reason": "Synthetic retained “terem” obligation.",
        "source_channel": "test",
    }
    approval = approve_venue_booking(
        actor=scope.approver,
        expected_version=booking.resulting_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        **request,
    )
    published = publish_venue_booking(
        actor=scope.publisher,
        expected_version=approval.resulting_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        **request,
    )
    _terminal(scope.edition, "archived")
    return scope, request, published


@pytest.mark.parametrize("operation", ["cancel", "withdraw"])
def test_actual_retained_venue_correction_keeps_exact_history_and_receipt(
    booked, operation
):
    scope, request, published = booked
    command = (
        cancel_venue_booking
        if operation == "cancel"
        else withdraw_venue_booking_publication
    )
    actor = scope.scheduler if operation == "cancel" else scope.publisher
    key = uuid4()
    result = command(
        actor=actor,
        expected_version=published.resulting_version,
        idempotency_key=key,
        correlation_id=uuid4(),
        **request,
    )
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    booking = VenueBooking.objects.get(id=result.object_id)
    assert booking.publication_state == "withdrawn"
    assert booking.lifecycle == ("cancelled" if operation == "cancel" else "active")
    assert VenueBookingOccupancy.objects.filter(
        booking=booking, active=True
    ).exists() is (operation == "withdraw")
    replay = command(
        actor=actor,
        expected_version=published.resulting_version,
        idempotency_key=key,
        correlation_id=uuid4(),
        **request,
    )
    assert replay.replayed


def test_withdraw_then_cancel_in_one_transaction_preserves_both_receipts(booked):
    scope, request, published = booked
    first = withdraw_venue_booking_publication(
        actor=scope.publisher,
        expected_version=published.resulting_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        **request,
    )
    second = cancel_venue_booking(
        actor=scope.scheduler,
        expected_version=first.resulting_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        **request,
    )
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert second.resulting_version == published.resulting_version + 2


@pytest.mark.parametrize("model", GUARDS.GUARDED_MODELS)
def test_native_fresh_venue_work_is_refused_in_stopped_scope(monkeypatch, model):
    admit_transaction_local_schema_candidate(monkeypatch)
    edition = EventEditionFactory(adoption_profile_code="programme_operations")
    _terminal(edition, "archived")
    with (
        connection.cursor() as cursor,
        pytest.raises(IntegrityError, match="Stopped Programme refuses"),
        transaction.atomic(),
    ):
        cursor.execute(
            sql.SQL(
                "INSERT INTO {} (id, organization_id, edition_id) VALUES (%s, %s, %s)"
            ).format(sql.Identifier("public", f"venues_{model}")),
            [uuid4(), edition.organization_id, edition.id],
        )


def test_exact_venue_preparation_catalog_is_ready():
    assert programme_stop_preparation_is_ready()


@pytest.mark.parametrize(
    "extra",
    [
        "expected_attendance = expected_attendance + 1",
        "review_state = 'draft'",
        "setup_starts_at = setup_starts_at - interval '1 minute'",
    ],
)
def test_cancellation_cannot_smuggle_other_booking_changes(booked, extra):
    _, request, _ = booked
    with (
        connection.cursor() as cursor,
        pytest.raises(IntegrityError, match="Stopped Programme refuses"),
        transaction.atomic(),
    ):
        cursor.execute(
            sql.SQL(
                "UPDATE public.venues_venuebooking SET lifecycle = 'cancelled', "
                "publication_state = 'withdrawn', "
                "aggregate_version = aggregate_version + 1, {} WHERE id = %s"
            ).format(sql.SQL(extra)),
            [request["booking_id"]],
        )


def test_raw_correction_without_retained_history_rolls_back(booked):
    _, request, _ = booked
    with (  # noqa: PT012 -- exercise mutation then deferred enforcement atomically.
        connection.cursor() as cursor,
        pytest.raises(IntegrityError, match="requires exact retained history"),
        transaction.atomic(),
    ):
        cursor.execute(
            "UPDATE public.venues_venuebooking SET publication_state = 'withdrawn', "
            "aggregate_version = aggregate_version + 1 WHERE id = %s",
            [request["booking_id"]],
        )
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert (
        VenueBooking.objects.get(id=request["booking_id"]).publication_state
        == "published"
    )


def test_cancelled_occupancy_cannot_be_reactivated(booked):
    scope, request, published = booked
    cancel_venue_booking(
        actor=scope.scheduler,
        expected_version=published.resulting_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        **request,
    )
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with (
        connection.cursor() as cursor,
        pytest.raises(IntegrityError, match="Stopped Programme refuses"),
        transaction.atomic(),
    ):
        cursor.execute(
            "UPDATE public.venues_venuebookingoccupancy SET active = TRUE "
            "WHERE booking_id = %s",
            [request["booking_id"]],
        )


@pytest.mark.parametrize("model", GUARDS.GUARDED_MODELS)
def test_disabling_any_venue_stop_guard_fails_readiness(model):
    index = GUARDS.GUARDED_MODELS.index(model)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER TABLE {} DISABLE TRIGGER {}").format(
                sql.Identifier("public", f"venues_{model}"),
                sql.Identifier(f"a00_venues_programme_stop_{index}"),
            )
        )
    assert not programme_stop_preparation_is_ready()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capability_code", "venues.manage_space_schedule"),
        ("changed_fields", ("lifecycle",)),
        ("idempotency_key_hash", "0" * 64),
        ("retention_class", "security-extended"),
    ],
)
def test_valid_native_audit_for_different_intent_cannot_authorize_withdrawal(
    booked, monkeypatch, field, value
):
    scope, request, published = booked
    original = services.audited_mutation

    @contextmanager
    def mismatched(record, **kwargs):
        with original(replace(record, **{field: value}), **kwargs) as mutation:
            yield mutation

    monkeypatch.setattr(services, "audited_mutation", mismatched)
    with (  # noqa: PT012 -- test rollback at the actual deferred evidence boundary.
        pytest.raises(IntegrityError, match="requires native receipt and audit"),
        transaction.atomic(),
    ):
        withdraw_venue_booking_publication(
            actor=scope.publisher,
            expected_version=published.resulting_version,
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            **request,
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert (
        VenueBooking.objects.get(id=request["booking_id"]).publication_state
        == "published"
    )
