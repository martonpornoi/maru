"""Unit coverage for exact-profile Registration-owned adoption catalogs."""

from maru.registration.adoption import (
    IDENTITY_RESTRICTION_CONSEQUENCE_ADAPTER,
    REGISTRATION_ADOPTION_ADAPTERS,
    profile_allows_identity_restriction_consequence,
)
from maru.registration.starter_catalog import (
    platform_registration_starter_for_profile,
    platform_registration_starters,
    platform_registration_starters_for_profile,
)


def test_identity_restriction_consequence_requires_its_exact_adapter() -> None:
    """Do not infer a Registration consequence from Identity adoption alone."""
    descriptor = REGISTRATION_ADOPTION_ADAPTERS[
        IDENTITY_RESTRICTION_CONSEQUENCE_ADAPTER
    ]

    assert descriptor.kind == "identity-restriction-consequence"
    assert profile_allows_identity_restriction_consequence("full_convention", 1)
    assert not profile_allows_identity_restriction_consequence("workforce_only", 1)
    assert not profile_allows_identity_restriction_consequence("full_convention", 2)


def test_registration_starter_catalog_requires_the_exact_profile_pair() -> None:
    """Expose the current starter only through the pinned full manifest."""
    starter = platform_registration_starters()[0]

    assert platform_registration_starters_for_profile(
        profile_code="full_convention",
        profile_version=1,
    ) == (starter,)
    assert (
        platform_registration_starter_for_profile(
            profile_code="full_convention",
            profile_version=1,
            source_id=starter.source_id,
        )
        == starter
    )
    assert (
        platform_registration_starters_for_profile(
            profile_code="workforce_only",
            profile_version=1,
        )
        == ()
    )
    assert (
        platform_registration_starter_for_profile(
            profile_code="full_convention",
            profile_version=2,
            source_id=starter.source_id,
        )
        is None
    )
