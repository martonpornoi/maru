"""Genuine-login native invalidation without Scheduling or witness table DML."""

import secrets
from uuid import uuid4

import pytest
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import override_settings
from psycopg import sql

from maru.authorization.database_role_safety import probe_runtime_database_role_safety
from maru.core.database_integrity_readiness import inspect_database_integrity_catalog
from maru.events.services import transition_edition
from maru.identity.services import deactivate_person_account_for_platform_emergency
from maru.programme.readiness import PROGRAMME_INTEGRITY_CONTRACT
from maru.scheduling.models import (
    SchedulingReleaseDependencyChange,
    SchedulingReleaseDependencyKey,
)
from maru.scheduling.readiness import SCHEDULING_INTEGRITY_CONTRACT
from maru.scheduling.writer_boundary import scheduling_writer
from maru.venues.models import VenueBooking
from maru.venues.readiness import VENUES_INTEGRITY_CONTRACT
from maru.venues.services import cancel_venue_booking
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.integration import test_scheduling_release_venue_changes as venue_changes
from tests.integration import test_workforce_shifts as shifts
from tests.integration.test_database_role_safety import (
    _create_role,
    _password_authenticated_default_database,
    _prepare_least_privilege_boundary,
    _provision_runtime_role,
    _public_privilege_snapshot,
    _restore_public_privileges,
    _table_privilege_matrix,
)
from tests.integration.test_venues import (
    _configure_schedule,
    _create_booking,
    _scope,
    _selected_space,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def _native_case(kind):
    if kind == "identity_account":
        actor = AccountFactory(is_superuser=True, is_staff=True)
        account = AccountFactory()
        scope = {"source_id": account.id}

        def change():
            deactivate_person_account_for_platform_emergency(
                actor=actor,
                account_id=account.id,
                reason="Synthetic runtime deactivation",
                correlation_id=uuid4(),
            )
    elif kind == "edition_operational":
        actor, edition = AccountFactory(), EventEditionFactory()
        CapabilityGrantFactory(
            principal=actor,
            organization=edition.organization,
            edition=edition,
            capability_code="events.transition",
        )
        scope = {
            "source_id": edition.id,
            "organization_id": edition.organization_id,
            "edition_id": edition.id,
        }

        def change():
            transition_edition(
                actor=actor,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                to_state="cancelled",
                reason="Synthetic runtime cancellation",
                correlation_id=uuid4(),
                source_channel="test",
            )
    elif kind in {"venue_property", "venue_booking"}:
        venue_scope = _scope()
        space = _selected_space(venue_scope)
        if kind == "venue_property":
            scope = {
                "source_id": space.venue_selection.property_id,
                "organization_id": venue_scope.edition.organization_id,
            }

            def change():
                venue_changes._property_change(
                    (venue_scope, space, None),
                    location_name="Synthetic runtime move",
                )
        else:
            start = _configure_schedule(venue_scope, space)
            created = _create_booking(venue_scope, space, start=start)
            booking = VenueBooking.objects.get(pk=created.object_id)
            scope = {
                "source_id": booking.id,
                "organization_id": venue_scope.edition.organization_id,
                "edition_id": venue_scope.edition.id,
            }

            def change():
                venue_changes._booking_action(
                    (venue_scope, space, start),
                    booking,
                    cancel_venue_booking,
                    venue_scope.scheduler,
                )
    elif kind == "workforce_person_obligations":
        world = shifts._shift_world()
        demand = shifts._create_demand(world)
        shifts._open(world, demand)
        scope = {"source_id": world.person.id}

        def change():
            shifts._claim(world, demand)
    else:
        assert kind == "workforce_demand"
        world = shifts._shift_world()
        demand = shifts._create_demand(world)
        scope = {
            "source_id": demand.id,
            "organization_id": world.edition.organization_id,
            "edition_id": world.edition.id,
        }

        def change():
            shifts._open(world, demand)

    with transaction.atomic(), scheduling_writer():
        key = SchedulingReleaseDependencyKey.objects.create(kind=kind, **scope)
    return key, change


@pytest.mark.parametrize(
    "kind",
    [
        "identity_account",
        "edition_operational",
        "venue_property",
        "venue_booking",
        "workforce_demand",
        "workforce_person_obligations",
    ],
)
def test_authenticated_native_owner_can_invalidate_but_cannot_write_release_tables(
    kind,
):
    key, change = _native_case(kind)
    public_snapshot = _public_privilege_snapshot()
    password = secrets.token_urlsafe(36)
    role = _create_role(password=password)
    try:
        with transaction.atomic():
            _prepare_least_privilege_boundary()
            _provision_runtime_role(role)
        with _password_authenticated_default_database(
            role_name=role, password=password
        ):
            report = probe_runtime_database_role_safety(role_name=role)
            assert report.current_session_is_safe
            with override_settings(RUNTIME_DATABASE_ROLE=role):
                for contract in (
                    PROGRAMME_INTEGRITY_CONTRACT,
                    SCHEDULING_INTEGRITY_CONTRACT,
                    VENUES_INTEGRITY_CONTRACT,
                ):
                    catalog = inspect_database_integrity_catalog(contract)
                    assert catalog.ready
                    assert catalog.function_execute_boundary_closed
                    assert not catalog.function_execute_owner_only
            for table in (
                "public.audit_auditnativemutationwitness",
                "public.scheduling_schedulingreleasedependencykey",
                "public.scheduling_schedulingreleasedependencychange",
                "public.scheduling_schedulingreleasewarningacknowledgement",
                "public.scheduling_schedulingreleaseapproval",
                "public.scheduling_schedulingreleaseapprovalplacement",
                "public.scheduling_schedulingreleaseapprovaldependency",
                "public.scheduling_schedulingrelease",
                "public.scheduling_schedulingreleaseartifact",
                "public.scheduling_schedulingreleasepointer",
                "public.scheduling_schedulingreleasewithdrawal",
                "public.programme_programmepublicrenditionwithdrawal",
            ):
                assert _table_privilege_matrix(role_name=role, identity=table) == (
                    True,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                )
                with (
                    pytest.raises(DatabaseError),
                    transaction.atomic(),
                    connection.cursor() as cursor,
                ):
                    cursor.execute(
                        sql.SQL("DELETE FROM {} WHERE false").format(
                            sql.Identifier(*table.split("."))
                        )
                    )

            with (
                pytest.raises(IntegrityError, match="exact current native mutation"),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    "SELECT public.maru_scheduling_record_native_release_change"
                    "(%s, %s, %s)",
                    [kind, key.source_id, uuid4()],
                )
            change()
            key.refresh_from_db()
            assert key.generation == 2
            recorded = SchedulingReleaseDependencyChange.objects.get(dependency=key)
            # The real command committed. Replaying its retained UUID in another
            # transaction cannot create a new or even pretend-current mutation.
            with (
                pytest.raises(IntegrityError, match="exact current native mutation"),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    "SELECT public.maru_scheduling_record_native_release_change"
                    "(%s, %s, %s)",
                    [kind, key.source_id, recorded.source_audit_id],
                )
            assert (
                SchedulingReleaseDependencyChange.objects.filter(dependency=key).count()
                == 1
            )
    finally:
        # This exact synthetic role owns no objects; remove its test grants and
        # login, then restore the pre-test PUBLIC ACL snapshot, even on failure.
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
            _restore_public_privileges(public_snapshot)
