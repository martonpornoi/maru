"""Transaction-local schema candidate, not a complete Programme adoption manifest.

Only native schema tests use this fixture. It retains real policies and guards,
copies Workforce's foundation capabilities, and rolls back rows and DDL together.
It is not integrated, runtime-role, profile-promotion or workflow acceptance.
"""

from dataclasses import replace
from enum import StrEnum

from django.db import connection, models

from maru.events import adoption
from maru.events.models import EventEdition


class _SchemaCandidateCode(StrEnum):
    FULL_CONVENTION = "full_convention"
    WORKFORCE_ONLY = "workforce_only"
    PROGRAMME_OPERATIONS = "programme_operations"


def admit_transaction_local_schema_candidate(monkeypatch):
    assert connection.in_atomic_block, "Candidate DDL must roll back with its test."
    candidate = replace(
        adoption.ADOPTION_PROFILES[("workforce_only", 1)],
        code=_SchemaCandidateCode.PROGRAMME_OPERATIONS,
    )
    monkeypatch.setattr(adoption, "AdoptionProfileCode", _SchemaCandidateCode)
    monkeypatch.setattr(
        adoption,
        "ADOPTION_PROFILES",
        {**adoption.ADOPTION_PROFILES, ("programme_operations", 1): candidate},
    )
    monkeypatch.setattr(
        adoption,
        "SELECTABLE_ADOPTION_PROFILE_KEYS",
        {
            **adoption.SELECTABLE_ADOPTION_PROFILE_KEYS,
            _SchemaCandidateCode.PROGRAMME_OPERATIONS: ("programme_operations", 1),
        },
    )
    field = EventEdition._meta.get_field("adoption_profile_code")
    monkeypatch.setattr(
        field,
        "choices",
        [*field.choices, ("programme_operations", "Schema candidate only")],
    )
    constraint = next(
        value
        for value in EventEdition._meta.constraints
        if value.name == "edition_adoption_profile_supported"
    )
    monkeypatch.setattr(
        constraint,
        "condition",
        constraint.condition
        | models.Q(
            adoption_profile_code="programme_operations",
            adoption_profile_version=1,
        ),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE events_eventedition "
            "DROP CONSTRAINT edition_adoption_profile_supported"
        )
        cursor.execute("""
            ALTER TABLE events_eventedition
            ADD CONSTRAINT edition_adoption_profile_supported
            CHECK (adoption_profile_version = 1 AND adoption_profile_code IN
                   ('full_convention', 'workforce_only', 'programme_operations'))
        """)
