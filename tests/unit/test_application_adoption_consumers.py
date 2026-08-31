"""Focused exact-manifest tests for Applications-owned consumers."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from maru.applications import starters as application_starters_module
from maru.applications.adoption import (
    ELIGIBILITY_ADAPTER_CODES,
    SOURCE_ADAPTER_CODES,
    TARGET_ADAPTER_CODES,
    profile_allows_application_eligibility,
    profile_allows_application_reviewer_role,
    profile_allows_application_self,
    profile_allows_application_source,
    profile_allows_application_starter,
    profile_allows_application_target,
)
from maru.applications.forms import DefinitionConfigureForm
from maru.applications.models import (
    ApplicationEligibilityKind,
    ApplicationSourceBinding,
    ApplicationTargetKind,
)
from maru.applications.source_adapters import applicant_is_eligible, source_bound_value
from maru.applications.starters import (
    STARTERS,
    application_starter_for_profile,
    starter_catalog_for_profile,
)
from maru.events import adoption as event_adoption
from maru.events.adoption import (
    FULL_CONVENTION_PROFILE_VERSION,
    WORKFORCE_ONLY_PROFILE_VERSION,
    AdoptionProfileCode,
)
from maru.identity.models import Account


def _edition(profile_code: str, profile_version: int) -> SimpleNamespace:
    return SimpleNamespace(
        adoption_profile_code=profile_code,
        adoption_profile_version=profile_version,
    )


def test_exact_profile_filters_the_starter_catalog_and_unknown_versions() -> None:
    """Keep current full starters while bounded or unknown profiles expose none."""
    full = starter_catalog_for_profile(
        profile_code=AdoptionProfileCode.FULL_CONVENTION,
        profile_version=FULL_CONVENTION_PROFILE_VERSION,
    )
    workforce = starter_catalog_for_profile(
        profile_code=AdoptionProfileCode.WORKFORCE_ONLY,
        profile_version=WORKFORCE_ONLY_PROFILE_VERSION,
    )
    unknown = starter_catalog_for_profile(
        profile_code=AdoptionProfileCode.FULL_CONVENTION,
        profile_version=FULL_CONVENTION_PROFILE_VERSION + 1,
    )

    assert full == STARTERS
    assert workforce == ()
    assert unknown == ()
    assert (
        application_starter_for_profile(
            profile_code=AdoptionProfileCode.WORKFORCE_ONLY,
            profile_version=WORKFORCE_ONLY_PROFILE_VERSION,
            starter_code="volunteer-application",
        )
        is None
    )


def test_exact_profile_pins_purpose_eligibility_and_source_providers() -> None:
    """Require every Applications provider independently of its namespace."""
    full_code = AdoptionProfileCode.FULL_CONVENTION
    workforce_code = AdoptionProfileCode.WORKFORCE_ONLY

    assert profile_allows_application_self(full_code, FULL_CONVENTION_PROFILE_VERSION)
    assert not profile_allows_application_self(
        workforce_code, WORKFORCE_ONLY_PROFILE_VERSION
    )
    for eligibility_kind in ELIGIBILITY_ADAPTER_CODES:
        assert profile_allows_application_eligibility(
            full_code,
            FULL_CONVENTION_PROFILE_VERSION,
            eligibility_kind,
        )
        assert not profile_allows_application_eligibility(
            workforce_code,
            WORKFORCE_ONLY_PROFILE_VERSION,
            eligibility_kind,
        )
    for source_binding in SOURCE_ADAPTER_CODES:
        assert profile_allows_application_source(
            full_code,
            FULL_CONVENTION_PROFILE_VERSION,
            source_binding,
        )
        assert not profile_allows_application_source(
            workforce_code,
            WORKFORCE_ONLY_PROFILE_VERSION,
            source_binding,
        )
    assert not profile_allows_application_eligibility(
        full_code,
        FULL_CONVENTION_PROFILE_VERSION,
        "future_same_namespace_provider",
    )
    assert not profile_allows_application_source(
        full_code,
        FULL_CONVENTION_PROFILE_VERSION,
        "future.same_namespace_source",
    )


def test_exact_profile_pins_every_accepted_target_adapter() -> None:
    """Reject legacy or future target kinds unless the exact manifest pins them."""
    assert set(TARGET_ADAPTER_CODES) == set(ApplicationTargetKind.values)
    for target_kind in ApplicationTargetKind.values:
        assert profile_allows_application_target(
            AdoptionProfileCode.FULL_CONVENTION,
            FULL_CONVENTION_PROFILE_VERSION,
            target_kind,
        )
        assert not profile_allows_application_target(
            AdoptionProfileCode.WORKFORCE_ONLY,
            WORKFORCE_ONLY_PROFILE_VERSION,
            target_kind,
        )
    assert not profile_allows_application_target(
        AdoptionProfileCode.FULL_CONVENTION,
        FULL_CONVENTION_PROFILE_VERSION,
        "future_target",
    )
    assert not profile_allows_application_target(
        AdoptionProfileCode.FULL_CONVENTION,
        FULL_CONVENTION_PROFILE_VERSION + 1,
        ApplicationTargetKind.DJ_SET,
    )


def test_reviewer_role_requires_required_and_complete_profile_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a mixed immutable role even when its review capability is pinned."""
    profile_key = (
        AdoptionProfileCode.FULL_CONVENTION.value,
        FULL_CONVENTION_PROFILE_VERSION,
    )
    full_profile = event_adoption.ADOPTION_PROFILES[profile_key]
    monkeypatch.setattr(
        event_adoption,
        "ADOPTION_PROFILES",
        {
            **event_adoption.ADOPTION_PROFILES,
            profile_key: replace(
                full_profile,
                capability_codes=(
                    full_profile.capability_codes
                    - {"registration.manage_configuration"}
                ),
            ),
        },
    )

    assert profile_allows_application_reviewer_role(
        profile_key[0],
        profile_key[1],
        ("applications.review",),
        sensitive=False,
    )
    assert not profile_allows_application_reviewer_role(
        profile_key[0],
        profile_key[1],
        ("applications.review", "registration.manage_configuration"),
        sensitive=False,
    )
    assert not profile_allows_application_reviewer_role(
        profile_key[0],
        profile_key[1],
        ("applications.review",),
        sensitive=True,
    )
    assert profile_allows_application_reviewer_role(
        profile_key[0],
        profile_key[1],
        ("applications.review", "applications.review_sensitive"),
        sensitive=True,
    )


def test_starter_disclosure_requires_its_accepted_target_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hide a retained starter when its independent target pin is absent."""
    profile_code = AdoptionProfileCode.FULL_CONVENTION
    profile_version = FULL_CONVENTION_PROFILE_VERSION
    starter_code = "dj-application"
    original_target_check = (
        application_starters_module.profile_allows_application_target
    )

    assert profile_allows_application_starter(
        profile_code,
        profile_version,
        starter_code,
    )
    assert (
        application_starter_for_profile(
            profile_code=profile_code,
            profile_version=profile_version,
            starter_code=starter_code,
        )
        is not None
    )

    def _manifest_variant_allows_target(
        checked_profile_code: str,
        checked_profile_version: int,
        target_adapter_kind: str,
    ) -> bool:
        if target_adapter_kind == ApplicationTargetKind.DJ_SET:
            return False
        return original_target_check(
            checked_profile_code,
            checked_profile_version,
            target_adapter_kind,
        )

    monkeypatch.setattr(
        application_starters_module,
        "profile_allows_application_target",
        _manifest_variant_allows_target,
    )

    assert profile_allows_application_starter(
        profile_code,
        profile_version,
        starter_code,
    )
    assert (
        application_starter_for_profile(
            profile_code=profile_code,
            profile_version=profile_version,
            starter_code=starter_code,
        )
        is None
    )
    assert starter_code not in {
        starter.code
        for starter in starter_catalog_for_profile(
            profile_code=profile_code,
            profile_version=profile_version,
        )
    }


def test_definition_form_offers_only_exact_profile_eligibility_providers() -> None:
    """Keep contextual provider choices aligned with the persisted profile."""
    full = DefinitionConfigureForm(
        departments=(),
        roles=(),
        edition_time_zone="UTC",
        adoption_profile_code=AdoptionProfileCode.FULL_CONVENTION,
        adoption_profile_version=FULL_CONVENTION_PROFILE_VERSION,
    )
    workforce = DefinitionConfigureForm(
        departments=(),
        roles=(),
        edition_time_zone="UTC",
        adoption_profile_code=AdoptionProfileCode.WORKFORCE_ONLY,
        adoption_profile_version=WORKFORCE_ONLY_PROFILE_VERSION,
    )

    assert tuple(full.fields["eligibility_kind"].choices) == tuple(
        ApplicationEligibilityKind.choices
    )
    assert tuple(workforce.fields["eligibility_kind"].choices) == ()


def test_eligibility_and_source_consumers_fail_closed_before_provider_reads() -> None:
    """Stop disallowed providers before relationship or source disclosure."""
    account = SimpleNamespace(
        is_active=True,
        account_kind=Account.Kind.PERSON,
        display_name="Synthetic Applicant",
    )
    full_definition = SimpleNamespace(
        edition=_edition(
            AdoptionProfileCode.FULL_CONVENTION,
            FULL_CONVENTION_PROFILE_VERSION,
        ),
        eligibility_kind=ApplicationEligibilityKind.AUTHENTICATED_PERSON,
        minimum_age=0,
    )
    workforce_definition = SimpleNamespace(
        edition=_edition(
            AdoptionProfileCode.WORKFORCE_ONLY,
            WORKFORCE_ONLY_PROFILE_VERSION,
        ),
        eligibility_kind=ApplicationEligibilityKind.AUTHENTICATED_PERSON,
        minimum_age=0,
    )

    assert applicant_is_eligible(definition=full_definition, account=account)
    assert not applicant_is_eligible(
        definition=workforce_definition,
        account=account,
    )

    full_question = SimpleNamespace(
        definition=full_definition,
        source_binding=ApplicationSourceBinding.ACCOUNT_DISPLAY_NAME,
    )
    workforce_question = SimpleNamespace(
        definition=workforce_definition,
        source_binding=ApplicationSourceBinding.ACCOUNT_DISPLAY_NAME,
    )
    assert source_bound_value(question=full_question, account=account) == (
        "Synthetic Applicant"
    )
    with pytest.raises(ValueError, match="exact edition profile"):
        source_bound_value(question=workforce_question, account=account)
