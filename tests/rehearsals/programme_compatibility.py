"""Independent isolated compatibility; never a production check exemption.

Every ordinary check is invoked. The three known owner dormancy results have an
explicit substitute contract: independently valid unchanged current profiles,
the complete literal candidate, intact catalogs and exact expected owner results.
Unknown checks, missing checks, extra messages and unknown owner problems fail.
The global Django registry and SILENCED_SYSTEM_CHECKS are never modified.
"""

from django.core.checks import ERROR, WARNING, CheckMessage
from django.core.checks.registry import registry

from maru.applications.programme_checks import (
    applications_programme_dormancy_problem_codes,
    check_applications_programme_dormancy,
)
from maru.events import adoption, adoption_persistence
from maru.events.checks import (
    adoption_manifest_catalog_problem_codes,
    current_adoption_catalog_snapshot,
)
from maru.programme.checks import (
    check_programme_dormancy,
    programme_dormancy_problem_codes,
)
from maru.scheduling.checks import (
    check_scheduling_dormancy,
    scheduling_dormancy_problem_codes,
)
from tests.rehearsals.programme_candidate import PROGRAMME_REHEARSAL_PROFILE
from tests.rehearsals.programme_registration import BASELINE_PROFILES
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)

_BASELINE_KEYS = (("full_convention", 1), ("workforce_only", 1))
_EXPECTED_KEYS = (*_BASELINE_KEYS, ("programme_operations", 1))
_OWNER_PROBLEMS = {
    check_programme_dormancy: (
        "programme.E001",
        programme_dormancy_problem_codes,
        frozenset(
            {
                "dormancy.adapter-adopted",
                "dormancy.capability-adopted",
                "dormancy.conflict-source-adopted",
                "dormancy.effect-route-adopted",
                "dormancy.module-adopted",
                "dormancy.profile-enum-active",
                "dormancy.profile-persistence-active",
            }
        ),
    ),
    check_scheduling_dormancy: (
        "scheduling.E001",
        scheduling_dormancy_problem_codes,
        frozenset(
            {
                "dormancy.adapter-adopted",
                "dormancy.capability-adopted",
                "dormancy.conflict-source-adopted",
                "dormancy.effect-route-adopted",
                "dormancy.module-adopted",
            }
        ),
    ),
    check_applications_programme_dormancy: (
        "applications.E002",
        applications_programme_dormancy_problem_codes,
        frozenset(
            {
                "dormancy.adapter-adopted",
                "dormancy.capability-adopted",
                "dormancy.effect-route-adopted",
            }
        ),
    ),
}


class ProgrammeCompatibilityError(RuntimeError):
    """Carry only a stable diagnostic code, not checker messages or private values."""


def validate_installed_candidate() -> None:
    """Check current profiles independently before considering candidate adoption."""
    profiles = adoption.ADOPTION_PROFILES
    if (
        tuple(BASELINE_PROFILES) != _BASELINE_KEYS
        or tuple(profiles) != _EXPECTED_KEYS
        or any(profiles[key] is not BASELINE_PROFILES[key] for key in _BASELINE_KEYS)
        or profiles[_EXPECTED_KEYS[-1]] is not PROGRAMME_REHEARSAL_PROFILE
        or tuple(adoption_persistence.PERSISTED_ADOPTION_PROFILE_KEYS) != _EXPECTED_KEYS
        or tuple(code.value for code in adoption.AdoptionProfileCode)
        != tuple(key[0] for key in _EXPECTED_KEYS)
        or dict(adoption.SELECTABLE_ADOPTION_PROFILE_KEYS)
        != {key[0]: key for key in _EXPECTED_KEYS}
    ):
        raise ProgrammeCompatibilityError("candidate_registry_changed")
    choices = tuple((key[0], profiles[key].label) for key in _EXPECTED_KEYS)
    if (
        choices != adoption.PERSISTED_ADOPTION_PROFILE_CHOICES
        or choices != adoption.SELECTABLE_ADOPTION_PROFILE_CHOICES
    ):
        raise ProgrammeCompatibilityError("candidate_choices_changed")
    if adoption_manifest_catalog_problem_codes(
        profiles=profiles,
        selectable_profile_keys=adoption.SELECTABLE_ADOPTION_PROFILE_KEYS,
        catalog=current_adoption_catalog_snapshot(),
    ):
        raise ProgrammeCompatibilityError("candidate_catalog_incomplete")
    baseline = tuple(BASELINE_PROFILES.values())
    if (
        programme_dormancy_problem_codes(
            profiles=baseline,
            profile_codes=tuple(key[0] for key in _BASELINE_KEYS),
            persisted_profile_keys=_BASELINE_KEYS,
        )
        or scheduling_dormancy_problem_codes(profiles=baseline)
        or applications_programme_dormancy_problem_codes(profiles=baseline)
    ):
        raise ProgrammeCompatibilityError("candidate_baseline_not_dormant")


def check_isolated_candidate() -> tuple[str, ...]:
    """Run all ordinary checks plus the independent isolated adoption contract.

    Returns
    -------
    tuple[str, ...]
        Exact owner dormancy IDs explicitly accounted for by the isolated
        contract, for honest startup reporting. These checks remain errors in
        ordinary production Django checks; they are not silently labelled green.
    """
    require_programme_runtime_environment()
    validate_installed_candidate()
    checks = registry.get_checks(include_deployment_checks=False)
    if not set(_OWNER_PROBLEMS) <= set(checks):
        raise ProgrammeCompatibilityError("candidate_owner_check_missing")
    accounted = []
    for check in checks:
        messages = check(app_configs=None, databases=["default"])
        if not isinstance(messages, (list, tuple)) or not all(
            isinstance(message, CheckMessage) for message in messages
        ):
            raise ProgrammeCompatibilityError("candidate_invalid_check_result")
        if check in _OWNER_PROBLEMS:
            identifier, problem_codes, expected = _OWNER_PROBLEMS[check]
            if (
                frozenset(problem_codes()) != expected
                or len(messages) != 1
                or messages[0].id != identifier
                or messages[0].level != ERROR
            ):
                raise ProgrammeCompatibilityError("candidate_owner_contract_changed")
            accounted.append(identifier)
        elif any(message.level >= WARNING for message in messages):
            raise ProgrammeCompatibilityError("candidate_system_check_failed")
    return tuple(sorted(accounted))
