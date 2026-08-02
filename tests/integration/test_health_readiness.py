"""Real PostgreSQL evidence for the minimized public readiness queries."""

import pytest
from django.db import connection
from django.test import override_settings
from rest_framework.test import APIClient

from maru.authorization.models import (
    AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
    AUTHORITY_PROVENANCE_ACTIVE_GENERATION,
    AUTHORITY_PROVENANCE_CONTRACT_VERSION,
    AUTHORITY_PROVENANCE_INACTIVE_GENERATION,
)
from maru.core import views

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=True)
def test_exact_readiness_queries_execute_against_real_postgresql() -> None:
    with connection.cursor() as cursor:
        cursor.execute(views._AUTHORITY_PROVENANCE_TABLE_HEALTH_QUERY)
        assert cursor.fetchone() == (True, True)

        cursor.execute(
            views._DORMANT_AUTHORITY_PROVENANCE_HEALTH_QUERY,
            (AUTHORITY_PROVENANCE_INACTIVE_GENERATION,),
        )
        assert cursor.fetchone() == (True, True)

        cursor.execute(
            views._EXACT_AUTHORITY_PROVENANCE_HEALTH_QUERY,
            (
                AUTHORITY_PROVENANCE_ACTIVE_GENERATION,
                AUTHORITY_PROVENANCE_CONTRACT_VERSION,
                AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
            ),
        )
        exact_contract = cursor.fetchone()

    assert exact_contract is not None
    assert len(exact_contract) == 5
    assert exact_contract[0] == 17
    assert exact_contract[2] is True
    assert exact_contract[3:] == (False, False)

    response = APIClient().get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {
            "database": "ok",
            "authority_provenance": "unavailable",
        },
    }
