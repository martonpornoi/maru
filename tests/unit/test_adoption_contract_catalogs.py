"""Unit coverage for module-owned adoption adapter catalogs."""

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from maru.accreditation.adoption import (
    ACCREDITATION_ADOPTION_ADAPTERS,
    ACCREDITATION_ADOPTION_CONFLICT_SOURCES,
    IDENTITY_RESTRICTION_CREDENTIAL_CONSEQUENCE_ADAPTER,
    OFFLINE_CHECK_IN_RELAY_ADAPTER,
)
from maru.applications.adoption import (
    APPLICATION_SELF_ADAPTER,
    APPLICATIONS_ADOPTION_ADAPTERS,
    APPLICATIONS_ADOPTION_CONFLICT_SOURCES,
    ELIGIBILITY_ADAPTER_CODES,
    SOURCE_ADAPTER_CODES,
    TARGET_ADAPTER_CODES,
)
from maru.events.adoption_contracts import (
    FOUNDATION_ADOPTION_ADAPTERS,
    FOUNDATION_ADOPTION_CONFLICT_SOURCES,
    AdoptionAdapterDescriptor,
    AdoptionConflictSourceDescriptor,
    build_adoption_adapter_registry,
    build_adoption_conflict_source_registry,
)
from maru.participation.adoption import (
    PARTICIPATION_ADOPTION_ADAPTERS,
    PARTICIPATION_ADOPTION_CONFLICT_SOURCES,
    PARTICIPATION_ATTENDEE_ADAPTER_CODE,
)
from maru.participation.queries import (
    PARTICIPATION_ATTENDEE_ADAPTER_CODE as QUERY_PARTICIPATION_ADAPTER_CODE,
)
from maru.registration.adoption import (
    IDENTITY_RESTRICTION_CONSEQUENCE_ADAPTER,
    REGISTRATION_ADOPTION_ADAPTERS,
    REGISTRATION_ADOPTION_CONFLICT_SOURCES,
)
from maru.venues.adoption import (
    VENUES_ADOPTION_ADAPTERS,
    VENUES_ADOPTION_CONFLICT_SOURCES,
    VENUES_ATTENDEE_SCHEDULE_ADAPTER_CODE,
)
from maru.venues.queries import (
    VENUES_ATTENDEE_SCHEDULE_ADAPTER_CODE as QUERY_VENUES_ADAPTER_CODE,
)
from maru.workforce.adoption import (
    ASSIGNMENT_PARTICIPATION_EXCLUDED_ADAPTER,
    ASSIGNMENT_PARTICIPATION_REQUIRED_ADAPTER,
    WORKFORCE_ADOPTION_ADAPTERS,
    WORKFORCE_ADOPTION_CONFLICT_SOURCES,
    WORKFORCE_SELF_ADAPTER,
)

_OWNER_ADAPTER_REGISTRIES = (
    ACCREDITATION_ADOPTION_ADAPTERS,
    APPLICATIONS_ADOPTION_ADAPTERS,
    PARTICIPATION_ADOPTION_ADAPTERS,
    REGISTRATION_ADOPTION_ADAPTERS,
    VENUES_ADOPTION_ADAPTERS,
    WORKFORCE_ADOPTION_ADAPTERS,
)
_EMPTY_CONFLICT_SOURCE_REGISTRIES = (
    FOUNDATION_ADOPTION_CONFLICT_SOURCES,
    ACCREDITATION_ADOPTION_CONFLICT_SOURCES,
    APPLICATIONS_ADOPTION_CONFLICT_SOURCES,
    PARTICIPATION_ADOPTION_CONFLICT_SOURCES,
    REGISTRATION_ADOPTION_CONFLICT_SOURCES,
    VENUES_ADOPTION_CONFLICT_SOURCES,
    WORKFORCE_ADOPTION_CONFLICT_SOURCES,
)


def _adapter(
    code: str = "applications.test@1",
    *,
    owner_module: str = "applications",
    kind: str = "test-kind",
    result_semantics: str = "Returns one bounded test result.",
    failure_semantics: str = "Fails closed without returning a test result.",
) -> AdoptionAdapterDescriptor:
    """Build one valid adapter descriptor for validation tests."""
    return AdoptionAdapterDescriptor(
        code=code,
        owner_module=owner_module,
        kind=kind,
        result_semantics=result_semantics,
        failure_semantics=failure_semantics,
    )


def test_owner_adapter_registries_are_complete_and_nonduplicating() -> None:
    """Expose every currently declared owner adapter exactly once."""
    expected_applications = {
        APPLICATION_SELF_ADAPTER,
        *ELIGIBILITY_ADAPTER_CODES.values(),
        *SOURCE_ADAPTER_CODES.values(),
        *TARGET_ADAPTER_CODES.values(),
    }
    assert set(ACCREDITATION_ADOPTION_ADAPTERS) == {
        IDENTITY_RESTRICTION_CREDENTIAL_CONSEQUENCE_ADAPTER,
        OFFLINE_CHECK_IN_RELAY_ADAPTER,
    }
    assert set(APPLICATIONS_ADOPTION_ADAPTERS) == expected_applications
    assert set(PARTICIPATION_ADOPTION_ADAPTERS) == {PARTICIPATION_ATTENDEE_ADAPTER_CODE}
    assert set(REGISTRATION_ADOPTION_ADAPTERS) == {
        IDENTITY_RESTRICTION_CONSEQUENCE_ADAPTER
    }
    assert set(VENUES_ADOPTION_ADAPTERS) == {VENUES_ATTENDEE_SCHEDULE_ADAPTER_CODE}
    assert set(WORKFORCE_ADOPTION_ADAPTERS) == {
        ASSIGNMENT_PARTICIPATION_REQUIRED_ADAPTER,
        ASSIGNMENT_PARTICIPATION_EXCLUDED_ADAPTER,
        WORKFORCE_SELF_ADAPTER,
    }

    all_codes = [code for registry in _OWNER_ADAPTER_REGISTRIES for code in registry]
    assert len(all_codes) == 26
    assert len(set(all_codes)) == len(all_codes)
    assert all(
        code == descriptor.code
        and descriptor.kind
        and descriptor.result_semantics
        and descriptor.failure_semantics
        and descriptor.version > 0
        for registry in _OWNER_ADAPTER_REGISTRIES
        for code, descriptor in registry.items()
    )


def test_foundation_and_owner_catalogs_are_explicitly_immutable() -> None:
    """Keep empty and populated catalogs read-only at runtime."""
    assert isinstance(FOUNDATION_ADOPTION_ADAPTERS, MappingProxyType)
    assert not FOUNDATION_ADOPTION_ADAPTERS
    assert all(
        isinstance(registry, MappingProxyType) and not registry
        for registry in _EMPTY_CONFLICT_SOURCE_REGISTRIES
    )

    descriptor = next(iter(APPLICATIONS_ADOPTION_ADAPTERS.values()))
    with pytest.raises(TypeError):
        APPLICATIONS_ADOPTION_ADAPTERS["applications.future@1"] = descriptor  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        descriptor.kind = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "code",
    [
        "applications.test",
        "applications.test@0",
        "applications.test@-1",
        "applications.test@01",
        "applications.test@v1",
        "applications..test@1",
    ],
)
def test_adapter_descriptor_rejects_malformed_or_nonpositive_versions(
    code: str,
) -> None:
    """Require a canonical positive integer version in every adapter code."""
    with pytest.raises(ValueError, match="positive canonical @version"):
        _adapter(code)


def test_descriptors_reject_owner_prefix_mismatch() -> None:
    """Keep descriptor codes in their declaring module namespace."""
    with pytest.raises(ValueError, match="owner module prefix"):
        _adapter("participation.attendee@1")


@pytest.mark.parametrize(
    ("kind", "result_semantics", "failure_semantics", "message"),
    [
        ("", "Returns a result.", "Fails closed.", "kind must not be empty"),
        ("   ", "Returns a result.", "Fails closed.", "kind must not be empty"),
        ("test-kind", "", "Fails closed.", "result_semantics must not be empty"),
        ("test-kind", "  ", "Fails closed.", "result_semantics must not be empty"),
        (
            "test-kind",
            "Returns a result.",
            "",
            "failure_semantics must not be empty",
        ),
        (
            "test-kind",
            "Returns a result.",
            "  ",
            "failure_semantics must not be empty",
        ),
    ],
)
def test_descriptors_reject_empty_kind_or_semantics(
    kind: str,
    result_semantics: str,
    failure_semantics: str,
    message: str,
) -> None:
    """Require every typed adapter to explain success and failure boundaries."""
    with pytest.raises(ValueError, match=message):
        _adapter(
            kind=kind,
            result_semantics=result_semantics,
            failure_semantics=failure_semantics,
        )


def test_registry_builders_reject_duplicate_codes_and_mixed_owners() -> None:
    """Reject declarations hidden by immutable mapping normalization."""
    descriptor = _adapter()
    with pytest.raises(ValueError, match="codes must be unique"):
        build_adoption_adapter_registry(
            owner_module="applications",
            descriptors=(descriptor, descriptor),
        )
    with pytest.raises(ValueError, match="another owner"):
        build_adoption_adapter_registry(
            owner_module="participation",
            descriptors=(descriptor,),
        )


def test_conflict_source_contract_uses_the_same_closed_validation() -> None:
    """Keep future conflict-source catalogs typed, versioned, and immutable."""
    source = AdoptionConflictSourceDescriptor(
        code="workforce.shift-commitments@2",
        owner_module="workforce",
        kind="time-overlap",
        result_semantics="Returns complete overlapping Shift commitments.",
        failure_semantics=(
            "Reports the source as unavailable and makes no completeness claim."
        ),
    )
    registry = build_adoption_conflict_source_registry(
        owner_module="workforce",
        descriptors=(source,),
    )

    assert isinstance(registry, MappingProxyType)
    assert registry == {source.code: source}
    assert source.version == 2
    with pytest.raises(ValueError, match="codes must be unique"):
        build_adoption_conflict_source_registry(
            owner_module="workforce",
            descriptors=(source, source),
        )
    with pytest.raises(ValueError, match="result_semantics must not be empty"):
        AdoptionConflictSourceDescriptor(
            code="workforce.shift-commitments@1",
            owner_module="workforce",
            kind="time-overlap",
            result_semantics="",
            failure_semantics="Reports the source as unavailable.",
        )
    with pytest.raises(ValueError, match="failure_semantics must not be empty"):
        AdoptionConflictSourceDescriptor(
            code="workforce.shift-commitments@1",
            owner_module="workforce",
            kind="time-overlap",
            result_semantics="Returns complete overlapping Shift commitments.",
            failure_semantics="",
        )


def test_moved_query_constants_preserve_their_public_values() -> None:
    """Keep existing query-module constant imports compatible."""
    assert QUERY_PARTICIPATION_ADAPTER_CODE == PARTICIPATION_ATTENDEE_ADAPTER_CODE
    assert QUERY_VENUES_ADAPTER_CODE == VENUES_ATTENDEE_SCHEDULE_ADAPTER_CODE
