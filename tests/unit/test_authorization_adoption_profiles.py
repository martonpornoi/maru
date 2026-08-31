from collections.abc import Collection
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest

import maru.authorization.api as authorization_api
import maru.authorization.policy as authorization_policy
from maru.authorization import page_access_workspace
from maru.authorization.models import RoleAssignment, RoleBundle
from maru.authorization.policy import (
    AuthorizedScopeProjection,
    ResolvedAuthorizationTarget,
)
from maru.events.adoption import (
    FULL_CONVENTION_PROFILE_VERSION,
    WORKFORCE_ONLY_PROFILE_VERSION,
    AdoptionProfileCode,
)


def _role(*capability_codes: str) -> RoleBundle:
    return RoleBundle(
        code="synthetic-access-group",
        capability_codes=list(capability_codes),
    )


def _target(
    *,
    edition_id: object,
    profile_code: str | None,
    profile_version: int | None,
) -> ResolvedAuthorizationTarget:
    return cast(
        "ResolvedAuthorizationTarget",
        SimpleNamespace(
            edition_id=edition_id,
            adoption_profile_code=profile_code,
            adoption_profile_version=profile_version,
        ),
    )


def test_api_access_group_filter_checks_every_capability_against_exact_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int, tuple[str, ...]]] = []

    def allows(
        profile_code: str,
        profile_version: int,
        capability_codes: Collection[str],
    ) -> bool:
        calls.append((profile_code, profile_version, tuple(capability_codes)))
        return True

    monkeypatch.setattr(authorization_api, "profile_allows_capabilities", allows)

    assert authorization_api._role_matches_profile(
        _role("events.view_basic", "authorization.manage_roles"),
        "full_convention",
        7,
    )
    assert calls == [
        (
            "full_convention",
            7,
            ("events.view_basic", "authorization.manage_roles"),
        )
    ]


def test_page_access_filter_requires_version_for_edition_but_not_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int, tuple[str, ...]]] = []

    def allows(
        profile_code: str,
        profile_version: int,
        capability_codes: Collection[str],
    ) -> bool:
        calls.append((profile_code, profile_version, tuple(capability_codes)))
        return True

    monkeypatch.setattr(
        page_access_workspace,
        "profile_allows_capabilities",
        allows,
    )
    role = _role("workforce.view_structure")

    assert page_access_workspace._role_matches_target(
        role=role,
        target=_target(
            edition_id=object(),
            profile_code="workforce_only",
            profile_version=3,
        ),
    )
    assert calls == [("workforce_only", 3, ("workforce.view_structure",))]

    calls.clear()
    assert not page_access_workspace._role_matches_target(
        role=role,
        target=_target(
            edition_id=object(),
            profile_code="workforce_only",
            profile_version=None,
        ),
    )
    assert page_access_workspace._role_matches_target(
        role=role,
        target=_target(
            edition_id=None,
            profile_code=None,
            profile_version=None,
        ),
    )
    assert calls == []


def test_reserved_root_filter_uses_exact_profile_pair_and_role_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int, str]] = []

    def allows(
        profile_code: str,
        profile_version: int,
        role_code: str,
    ) -> bool:
        calls.append((profile_code, profile_version, role_code))
        return True

    monkeypatch.setattr(
        authorization_policy,
        "representation_definition_for_role",
        lambda _role_code: object(),
    )
    monkeypatch.setattr(authorization_policy, "profile_allows_role", allows)
    assignment = cast(
        "RoleAssignment",
        SimpleNamespace(
            role_bundle=SimpleNamespace(
                code="synthetic-reserved-root",
                capability_codes=["events.view_basic"],
            )
        ),
    )
    target = _target(
        edition_id=object(),
        profile_code="full_convention",
        profile_version=11,
    )

    assert authorization_policy._purpose_bounded_role_matches_target(
        assignment,
        target,
    )
    assert calls == [("full_convention", 11, "synthetic-reserved-root")]


def test_projected_scope_preserves_source_specific_profile_contracts() -> None:
    scope = AuthorizedScopeProjection(
        organization_id=uuid4(),
        edition_id=None,
        department_id=None,
        resource_binding_id=None,
        capability_codes=frozenset(
            {
                "events.view_basic",
                "registration.manage_configuration",
                "workforce.view_structure",
            }
        ),
        direct_capability_codes=frozenset({"registration.manage_configuration"}),
        ordinary_role_capability_sets=(
            frozenset({"events.view_basic", "registration.manage_configuration"}),
            frozenset({"workforce.view_structure"}),
        ),
        purpose_bound_role_capabilities=(),
    )

    assert not authorization_policy.projected_scope_allows_profile(
        scope,
        profile_code=AdoptionProfileCode.WORKFORCE_ONLY,
        profile_version=WORKFORCE_ONLY_PROFILE_VERSION,
        capability_codes={"registration.manage_configuration"},
    )
    assert not authorization_policy.projected_scope_allows_profile(
        scope,
        profile_code=AdoptionProfileCode.WORKFORCE_ONLY,
        profile_version=WORKFORCE_ONLY_PROFILE_VERSION,
        capability_codes={"events.view_basic"},
    )
    assert authorization_policy.projected_scope_allows_profile(
        scope,
        profile_code=AdoptionProfileCode.WORKFORCE_ONLY,
        profile_version=WORKFORCE_ONLY_PROFILE_VERSION,
        capability_codes={"workforce.view_structure"},
    )
    assert authorization_policy.projected_scope_allows_profile(
        scope,
        profile_code=AdoptionProfileCode.FULL_CONVENTION,
        profile_version=FULL_CONVENTION_PROFILE_VERSION,
        capability_codes={"events.view_basic"},
    )
    assert not authorization_policy.projected_scope_allows_profile(
        scope,
        profile_code=AdoptionProfileCode.WORKFORCE_ONLY,
        profile_version=WORKFORCE_ONLY_PROFILE_VERSION + 1,
        capability_codes={"workforce.view_structure"},
    )

    root_only_scope = AuthorizedScopeProjection(
        organization_id=scope.organization_id,
        edition_id=None,
        department_id=None,
        resource_binding_id=None,
        capability_codes=frozenset({"events.view_basic"}),
        direct_capability_codes=frozenset(),
        ordinary_role_capability_sets=(),
        purpose_bound_role_capabilities=(
            ("maru-operators", frozenset({"events.view_basic"})),
        ),
    )
    assert authorization_policy.projected_scope_allows_profile(
        root_only_scope,
        profile_code=AdoptionProfileCode.WORKFORCE_ONLY,
        profile_version=WORKFORCE_ONLY_PROFILE_VERSION,
        capability_codes={"events.view_basic"},
    )
    assert not authorization_policy.projected_scope_allows_profile(
        root_only_scope,
        profile_code=AdoptionProfileCode.FULL_CONVENTION,
        profile_version=FULL_CONVENTION_PROFILE_VERSION,
        capability_codes={"events.view_basic"},
    )
