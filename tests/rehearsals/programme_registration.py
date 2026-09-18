"""Explicit isolated pre-model registration; importing this module changes nothing.

This is not a server, readiness check or production activation switch. Owner
dormancy checks remain intact and still reject adoption until the joined fixture
has its separately reviewed compatibility boundary.
"""

import sys
from enum import StrEnum
from types import MappingProxyType

from django.apps import apps

from maru.events import adoption, adoption_persistence
from tests.rehearsals.programme_candidate import PROGRAMME_REHEARSAL_PROFILE
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)

_CURRENT_KEYS = (("full_convention", 1), ("workforce_only", 1))
# Capture the real immutable objects before explicit child registration. The
# startup verifier must compare installed baseline entries by identity as well
# as validate their owner contracts; it must not infer safety from candidate errors.
BASELINE_PROFILES = MappingProxyType(dict(adoption.ADOPTION_PROFILES))


class IsolatedAdoptionProfileCode(StrEnum):
    """Preserve both current code values alongside one explicit isolated candidate."""

    FULL_CONVENTION = "full_convention"
    WORKFORCE_ONLY = "workforce_only"
    PROGRAMME_OPERATIONS = "programme_operations"


class ProgrammeRegistrationError(RuntimeError):
    """Refuse stale import state or an unreviewed production registry shape."""


def register_isolated_programme_candidate() -> None:
    """Extend a fresh policy-fenced child registry before any Events consumers load.

    Raises
    ------
    ProgrammeRegistrationError
        If model/application/Events consumers already loaded or current profile
        keys, choices, selectors or persistence declarations changed. Environment
        errors propagate before any mutation. Repeated installation is refused.

    Notes
    -----
    No database, route, handler, authority, role or check is altered. Existing
    manifest objects are retained by identity. Schema installation and independent
    catalog/owner compatibility validation remain separate mandatory boundaries;
    successful registration must never be reported as startup acceptance.
    """
    require_programme_runtime_environment()
    safe_events_imports = {
        "maru.events",
        "maru.events.adoption",
        "maru.events.adoption_persistence",
    }
    if apps.apps_ready or any(
        (name.startswith("maru.events.") and name not in safe_events_imports)
        or (name.startswith("maru.") and ".models" in name)
        for name in sys.modules
    ):
        raise ProgrammeRegistrationError("candidate_registration_too_late")
    profiles = adoption.ADOPTION_PROFILES
    choices = tuple(
        (key[0], profiles[key].label) for key in _CURRENT_KEYS if key in profiles
    )
    if (
        tuple(profiles) != _CURRENT_KEYS
        or tuple(adoption_persistence.PERSISTED_ADOPTION_PROFILE_KEYS) != _CURRENT_KEYS
        or tuple(code.value for code in adoption.AdoptionProfileCode)
        != tuple(key[0] for key in _CURRENT_KEYS)
        or dict(adoption.SELECTABLE_ADOPTION_PROFILE_KEYS)
        != {key[0]: key for key in _CURRENT_KEYS}
        or tuple(adoption.PERSISTED_ADOPTION_PROFILE_CHOICES) != choices
        or tuple(adoption.SELECTABLE_ADOPTION_PROFILE_CHOICES) != choices
        or any(profiles[key].key != key for key in _CURRENT_KEYS)
    ):
        raise ProgrammeRegistrationError("candidate_registration_baseline_changed")
    candidate = PROGRAMME_REHEARSAL_PROFILE
    if candidate.key != ("programme_operations", 1):
        raise ProgrammeRegistrationError("candidate_registration_version_changed")
    # Build every replacement before the first assignment. Only a fresh child
    # process may install these; no running application hot-reload is supported.
    extended = MappingProxyType({**profiles, candidate.key: candidate})
    selectors = MappingProxyType(
        {
            IsolatedAdoptionProfileCode(code): key
            for code, key in (
                *adoption.SELECTABLE_ADOPTION_PROFILE_KEYS.items(),
                (candidate.code, candidate.key),
            )
        }
    )
    extended_choices = (*choices, (candidate.code.value, candidate.label))
    adoption.AdoptionProfileCode = IsolatedAdoptionProfileCode
    adoption.ADOPTION_PROFILES = extended
    adoption.SELECTABLE_ADOPTION_PROFILE_KEYS = selectors
    adoption.PERSISTED_ADOPTION_PROFILE_CHOICES = extended_choices
    adoption.SELECTABLE_ADOPTION_PROFILE_CHOICES = extended_choices
    adoption_persistence.PERSISTED_ADOPTION_PROFILE_KEYS = (
        *_CURRENT_KEYS,
        candidate.key,
    )
