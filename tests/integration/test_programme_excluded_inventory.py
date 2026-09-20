"""Native observer mechanics with synthetic rows, not a real Programme journey."""

import pytest
from django.db import connection

from maru.participation.models import Participation
from tests.factories import (
    CapabilityGrantFactory,
    EventEditionFactory,
    ParticipationFactory,
    RoleBundleFactory,
)
from tests.rehearsals.programme_excluded_state import (
    ProgrammeExcludedStateError,
    _fingerprint,
    _require_closed_effects,
    excluded_tables,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def test_native_inventory_hashes_detect_added_edited_and_removed_rows():
    connection.ensure_connection()
    native = connection.connection
    before = _fingerprint(native, "participation_participation")
    person = ParticipationFactory()
    added = _fingerprint(native, "participation_participation")
    assert added[1] == before[1] + 1
    assert added[2] != before[2]
    Participation.objects.filter(id=person.id).update(public_history_visible=True)
    edited = _fingerprint(native, "participation_participation")
    assert edited[1] == added[1]
    assert edited[2] != added[2]
    person.delete()
    assert _fingerprint(native, "participation_participation") == before


def test_every_excluded_owner_table_can_be_read_without_returning_private_rows():
    connection.ensure_connection()
    native = connection.connection
    for table in excluded_tables():
        identity, count, digest = _fingerprint(native, table)
        assert identity == table
        assert count >= 0
        assert len(digest) == 64
    _require_closed_effects(native)


@pytest.mark.parametrize("kind", ["grant", "bundle"])
def test_native_inventory_refuses_real_excluded_authority(kind):
    if kind == "grant":
        edition = EventEditionFactory()
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            capability_code="registration.manage_configuration",
        )
    else:
        RoleBundleFactory(capability_codes=["registration.manage_configuration"])
    with pytest.raises(ProgrammeExcludedStateError, match="excluded_authority_created"):
        _require_closed_effects(connection.connection)
