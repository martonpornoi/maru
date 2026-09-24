"""Execute current stop receipt admission and ACL checks against PostgreSQL."""

from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def test_native_stop_receipt_insertion_requires_complete_bounded_intent():
    # The BEFORE guard must refuse before even invalid references can be written.
    # This is intentionally not a fabricated completed stop fixture.
    with transaction.atomic(), connection.cursor() as cursor:
        with (
            pytest.raises(IntegrityError, match="exact bounded intent"),
            transaction.atomic(),
        ):
            cursor.execute(
                "INSERT INTO public.events_programmestopreceipt (id) VALUES (%s)",
                [uuid4()],
            )
        cursor.execute("SELECT count(*) FROM public.events_programmestopreceipt")
        assert cursor.fetchone() == (0,)


def test_stop_storage_native_functions_are_invoker_only_with_closed_public_acl():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT p.proname, p.prosecdef, p.proconfig, "
            "EXISTS (SELECT 1 FROM aclexplode("
            "coalesce(p.proacl, acldefault('f', p.proowner))) a "
            "WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE') "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' AND p.proname IN "
            "('maru_programme_stop_receipt_guard', "
            "'maru_programme_stop_refuse_truncate') "
            "ORDER BY p.proname"
        )
        assert cursor.fetchall() == [
            (name, False, ["search_path=pg_catalog, public, pg_temp"], False)
            for name in (
                "maru_programme_stop_receipt_guard",
                "maru_programme_stop_refuse_truncate",
            )
        ]
