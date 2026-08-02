"""External exact-lineage recovery-fence policy coverage."""

import pytest
from django.test import override_settings

from maru.authorization import policy
from maru.authorization.policy import (
    decide,
    resolve_organization_target,
    resolve_self_target,
)
from tests.factories import AccountFactory, CapabilityGrantFactory, OrganizationFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=True)
def test_required_exact_lineage_denies_dormant_legacy_authority() -> None:
    organization = OrganizationFactory()
    principal = AccountFactory()
    CapabilityGrantFactory(
        principal=principal,
        organization=organization,
        capability_code="events.view_basic",
    )
    target = resolve_organization_target(organization_id=organization.id)
    assert target is not None
    assert not policy.exact_lineage_policy_is_active()

    decision = decide(
        principal=principal,
        capability_code="events.view_basic",
        resource=target,
    )

    assert not decision.allowed
    assert decision.fields == frozenset()
    assert decision.obligations == frozenset()
    assert decision.reason_code == "authority_provenance_contract_invalid"


@override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=True)
def test_required_exact_lineage_uses_the_valid_exact_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = OrganizationFactory()
    principal = AccountFactory()
    CapabilityGrantFactory(
        principal=principal,
        organization=organization,
        capability_code="events.view_basic",
    )
    target = resolve_organization_target(organization_id=organization.id)
    assert target is not None
    monkeypatch.setattr(policy, "_exact_lineage_policy_state", lambda: (True, True))
    monkeypatch.setattr(policy, "_exact_issuance_allows", lambda **_kwargs: True)

    decision = decide(
        principal=principal,
        capability_code="events.view_basic",
        resource=target,
    )

    assert decision.allowed
    assert decision.reason_code == "direct_grant"


@override_settings(REQUIRE_EXACT_AUTHORITY_PROVENANCE=True)
def test_required_exact_lineage_preserves_self_and_platform_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = OrganizationFactory()
    person = AccountFactory()
    administrator = AccountFactory(is_staff=True, is_superuser=True)

    def unexpected_lineage_read() -> tuple[bool, bool]:
        raise AssertionError("self and platform policy must precede lineage reads")

    monkeypatch.setattr(policy, "_exact_lineage_policy_state", unexpected_lineage_read)
    self_target = resolve_self_target(
        principal=person,
        organization_id=organization.id,
    )
    organization_target = resolve_organization_target(organization_id=organization.id)
    assert self_target is not None
    assert organization_target is not None

    own = decide(
        principal=person,
        capability_code="participation.view_self",
        resource=self_target,
    )
    platform = decide(
        principal=administrator,
        capability_code="events.view_basic",
        resource=organization_target,
    )

    assert own.allowed
    assert own.reason_code == "self_relationship"
    assert platform.allowed
    assert platform.reason_code == "platform_administration"
