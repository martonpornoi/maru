"""Deployment-readiness evidence for ADR 0041 authorization scope v2."""

from __future__ import annotations

import json
from datetime import date
from io import StringIO
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.authorization.models import RoleAssignment
from maru.workforce.models import (
    Department,
    Position,
    PositionAssignment,
    PositionTemplate,
)
from tests.factories import (
    AccountFactory,
    EventEditionFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
    ScopedResourceBindingFactory,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

AUTHORIZATION_BEFORE_ACTIVATION = ("authorization", "0004_scope_v2_schema")
AUTHORIZATION_AFTER_ACTIVATION = ("authorization", "0005_scope_v2_activation")
WORKFORCE_SCOPE_V2_INTEGRITY = ("workforce", "0004_scope_v2_integrity")

EXPECTED_BLOCKER_KEYS = (
    "binding_scope_mismatch",
    "capability_grant_scope_too_broad",
    "delegation_cycle",
    "delegation_edge_mismatch",
    "department_cycle",
    "department_scope_mismatch",
    "malformed_capability_grant_scope",
    "malformed_role_bundle",
    "malformed_role_assignment_scope",
    "missing_position_binding",
    "nonpersistable_capability_grant",
    "nonpersistable_role_bundle",
    "invalid_capability_grant_revocation",
    "invalid_role_assignment_revocation",
    "position_assignment_role_evidence_mismatch",
    "position_scope_mismatch",
    "role_assignment_scope_too_broad",
    "role_bundle_organization_mismatch",
    "unknown_capability_grant",
    "unknown_role_bundle_capability",
)


def _migrate(*targets: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(list(targets))
    return executor


def _run_readiness(*, no_fail: bool = True) -> tuple[str, dict[str, Any]]:
    output = StringIO()
    arguments = ("--no-fail",) if no_fail else ()
    call_command("check_scope_v2_readiness", *arguments, stdout=output)
    rendered = output.getvalue()
    return rendered, json.loads(rendered)


def _expected_report(
    *,
    blocker_counts: dict[str, int] | None = None,
    legacy_review_count: int = 0,
) -> dict[str, object]:
    counts = dict.fromkeys(EXPECTED_BLOCKER_KEYS, 0)
    if blocker_counts is not None:
        counts.update(blocker_counts)
    blocker_total = sum(counts.values())
    return {
        "status": "blocked" if blocker_total else "ready",
        "production_status": "blocked",
        "blocker_counts": counts,
        "blocker_total": blocker_total,
        "review_counts": {
            "legacy_edition_wide_position_role_assignment": legacy_review_count,
        },
        "known_production_gates": {
            "actor_approver_authority_source_provenance": "unresolved",
        },
    }


def _create_historical_scope(apps: Any) -> SimpleNamespace:
    account_model = apps.get_model("identity", "Account")
    organization_model = apps.get_model("organizations", "Organization")
    series_model = apps.get_model("organizations", "ConventionSeries")
    edition_model = apps.get_model("events", "EventEdition")
    role_bundle_model = apps.get_model("authorization", "RoleBundle")
    grant_model = apps.get_model("authorization", "CapabilityGrant")
    binding_model = apps.get_model("authorization", "ScopedResourceBinding")
    department_model = apps.get_model("workforce", "Department")
    template_model = apps.get_model("workforce", "PositionTemplate")
    position_model = apps.get_model("workforce", "Position")

    account = account_model.objects.create(
        email="scope-readiness-private@example.invalid",
        login_handle="scope-readiness-private",
        display_name="Private Scope Readiness Person",
        password="!synthetic-unusable",
    )
    organization = organization_model.objects.create(
        slug="scope-readiness-private",
        name="Private Scope Readiness Organization",
    )
    series = series_model.objects.create(
        organization_id=organization.id,
        slug="scope-readiness-series",
        name="Private Scope Readiness Series",
    )
    edition = edition_model.objects.create(
        organization_id=organization.id,
        series_id=series.id,
        slug="scope-readiness-2033",
        name="Private Scope Readiness Edition",
        time_zone="UTC",
        language_codes=["en"],
        currency_codes=["EUR"],
        starts_on=date(2033, 8, 1),
        ends_on=date(2033, 8, 4),
    )
    role_bundle = role_bundle_model.objects.create(
        organization_id=organization.id,
        code="scope-readiness-reader",
        name="Private Scope Readiness Reader",
        version=1,
        capability_codes=["events.view_basic"],
    )
    department = department_model.objects.create(
        organization_id=organization.id,
        edition_id=edition.id,
        code="scope-readiness-operations",
        name="Private Scope Readiness Operations",
    )
    template = template_model.objects.create(
        organization_id=organization.id,
        code="scope-readiness-lead",
        name="Private Scope Readiness Lead",
        description="Synthetic readiness fixture.",
        default_capacity_codes=["volunteer"],
        role_bundle_id=role_bundle.id,
        created_by_id=account.id,
    )
    position = position_model.objects.create(
        organization_id=organization.id,
        edition_id=edition.id,
        template_id=template.id,
        department_id=department.id,
        role_bundle_id=role_bundle.id,
        code="scope-readiness-lead",
        title="Private Scope Readiness Lead",
        description="Synthetic readiness position without a binding.",
        capacity_codes=["volunteer"],
        created_by_id=account.id,
    )
    grant = grant_model.objects.create(
        organization_id=organization.id,
        principal_id=account.id,
        capability_code="synthetic.unknown_private_capability",
        effective_from=timezone.now(),
        granted_by_id=account.id,
        reason="Synthetic readiness blocker.",
    )
    return SimpleNamespace(
        account=account,
        organization=organization,
        series=series,
        edition=edition,
        role_bundle=role_bundle,
        department=department,
        template=template,
        position=position,
        grant=grant,
        account_model=account_model,
        organization_model=organization_model,
        series_model=series_model,
        edition_model=edition_model,
        role_bundle_model=role_bundle_model,
        grant_model=grant_model,
        binding_model=binding_model,
        department_model=department_model,
        template_model=template_model,
        position_model=position_model,
    )


def _reconcile_historical_scope(scope: SimpleNamespace) -> None:
    scope.grant_model.objects.filter(pk=scope.grant.id).delete()
    scope.binding_model.objects.create(
        id=uuid4(),
        organization_id=scope.organization.id,
        edition_id=scope.edition.id,
        department_id=scope.department.id,
        resource_kind="workforce.position",
        resource_id=scope.position.id,
    )


def _create_runtime_position() -> tuple[Position, RoleAssignment]:
    edition = EventEditionFactory()
    account = AccountFactory()
    creator = AccountFactory()
    role_bundle = RoleBundleFactory(organization=edition.organization)
    department = Department.objects.create(
        organization=edition.organization,
        edition=edition,
        code="readiness-operations",
        name="Readiness Operations",
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="readiness-lead",
        name="Readiness lead",
        description="Synthetic readiness template.",
        default_capacity_codes=["volunteer"],
        role_bundle=role_bundle,
        created_by=creator,
    )
    position = Position.objects.create(
        organization=edition.organization,
        edition=edition,
        template=template,
        department=department,
        role_bundle=role_bundle,
        code="readiness-lead",
        title="Readiness lead",
        description="Synthetic readiness position.",
        capacity_codes=["volunteer"],
        created_by=creator,
    )
    ScopedResourceBindingFactory(
        department=department,
        resource_id=position.id,
    )
    role_assignment = RoleAssignmentFactory(
        organization=edition.organization,
        edition=edition,
        principal=account,
        role_bundle=role_bundle,
    )
    PositionAssignment.objects.create(
        position=position,
        organization=edition.organization,
        edition=edition,
        account=account,
        effective_from=timezone.now(),
        proposed_by=creator,
        reason="Synthetic legacy edition-wide authority evidence.",
        role_assignment=role_assignment,
    )
    return position, role_assignment


def test_empty_current_graph_emits_stable_privacy_minimized_ready_json() -> None:
    first_rendered, first_report = _run_readiness()
    second_rendered, second_report = _run_readiness()

    assert first_report == _expected_report()
    assert first_report["status"] == "ready"
    assert first_report["production_status"] == "blocked"
    assert second_report == first_report
    assert second_rendered == first_rendered
    assert "@" not in first_rendered
    assert "display_name" not in first_rendered
    assert "principal" not in first_rendered


def test_historical_blockers_are_counted_without_subject_disclosure_and_fail() -> None:
    executor = _migrate(
        AUTHORIZATION_BEFORE_ACTIVATION,
        WORKFORCE_SCOPE_V2_INTEGRITY,
    )
    historical_apps = executor.loader.project_state(
        [AUTHORIZATION_BEFORE_ACTIVATION, WORKFORCE_SCOPE_V2_INTEGRITY]
    ).apps
    scope = _create_historical_scope(historical_apps)

    try:
        rendered, report = _run_readiness()
        expected = _expected_report(
            blocker_counts={
                "missing_position_binding": 1,
                "unknown_capability_grant": 1,
            }
        )

        assert report == expected
        assert scope.account.email not in rendered
        assert scope.account.display_name not in rendered
        assert str(scope.account.id) not in rendered
        assert str(scope.position.id) not in rendered
        assert scope.organization.name not in rendered
        assert "synthetic.unknown_private_capability" not in rendered

        failing_output = StringIO()
        with pytest.raises(
            CommandError,
            match="Authorization scope-v2 blockers detected",
        ):
            call_command("check_scope_v2_readiness", stdout=failing_output)
        assert json.loads(failing_output.getvalue()) == expected
    finally:
        _reconcile_historical_scope(scope)
        _migrate(
            AUTHORIZATION_AFTER_ACTIVATION,
            WORKFORCE_SCOPE_V2_INTEGRITY,
        )

    applied_migrations = MigrationExecutor(connection).loader.applied_migrations
    assert AUTHORIZATION_AFTER_ACTIVATION in applied_migrations
    assert WORKFORCE_SCOPE_V2_INTEGRITY in applied_migrations


def test_historical_catalog_categories_and_scope_ranks_are_counted() -> None:
    executor = _migrate(
        AUTHORIZATION_BEFORE_ACTIVATION,
        WORKFORCE_SCOPE_V2_INTEGRITY,
    )
    historical_apps = executor.loader.project_state(
        [AUTHORIZATION_BEFORE_ACTIVATION, WORKFORCE_SCOPE_V2_INTEGRITY]
    ).apps
    scope = _create_historical_scope(historical_apps)
    role_assignment_model = historical_apps.get_model(
        "authorization",
        "RoleAssignment",
    )
    binding = scope.binding_model.objects.create(
        id=uuid4(),
        organization_id=scope.organization.id,
        edition_id=scope.edition.id,
        department_id=scope.department.id,
        resource_kind="workforce.position",
        resource_id=scope.position.id,
    )
    now = timezone.now()

    try:
        scope.grant_model.objects.create(
            organization_id=scope.organization.id,
            principal_id=scope.account.id,
            capability_code="registration.view_self",
            effective_from=now,
            granted_by_id=scope.account.id,
            reason="Synthetic nonpersistable readiness blocker.",
        )
        for scope_values in (
            {},
            {"edition_id": scope.edition.id},
            {
                "edition_id": scope.edition.id,
                "department_id": scope.department.id,
            },
            {
                "edition_id": scope.edition.id,
                "department_id": scope.department.id,
                "resource_binding_id": binding.id,
            },
        ):
            scope.grant_model.objects.create(
                organization_id=scope.organization.id,
                principal_id=scope.account.id,
                capability_code="workforce.view_structure",
                effective_from=now,
                granted_by_id=scope.account.id,
                reason="Synthetic scope-rank readiness evidence.",
                **scope_values,
            )

        malformed_codes = ([], [None], ["events.view_basic", "events.view_basic"])
        for index, codes in enumerate(malformed_codes, start=1):
            scope.role_bundle_model.objects.create(
                organization_id=scope.organization.id,
                code=f"malformed-{index}",
                name=f"Malformed {index}",
                version=1,
                capability_codes=codes,
            )
        scope.role_bundle_model.objects.create(
            organization_id=scope.organization.id,
            code="unknown-capability",
            name="Unknown capability",
            version=1,
            capability_codes=["synthetic.unknown_private_capability"],
        )
        scope.role_bundle_model.objects.create(
            organization_id=scope.organization.id,
            code="nonpersistable-capability",
            name="Nonpersistable capability",
            version=1,
            capability_codes=["registration.view_self"],
        )
        broad_bundle = scope.role_bundle_model.objects.create(
            organization_id=scope.organization.id,
            code="scope-ranked",
            name="Scope ranked",
            version=1,
            capability_codes=["workforce.view_structure"],
        )
        for scope_values in (
            {},
            {"edition_id": scope.edition.id},
            {
                "edition_id": scope.edition.id,
                "department_id": scope.department.id,
            },
            {
                "edition_id": scope.edition.id,
                "department_id": scope.department.id,
                "resource_binding_id": binding.id,
            },
        ):
            role_assignment_model.objects.create(
                organization_id=scope.organization.id,
                principal_id=scope.account.id,
                role_bundle_id=broad_bundle.id,
                effective_from=now,
                granted_by_id=scope.account.id,
                reason="Synthetic assignment scope-rank evidence.",
                **scope_values,
            )

        rendered, report = _run_readiness()

        assert report == _expected_report(
            blocker_counts={
                "capability_grant_scope_too_broad": 1,
                "malformed_role_bundle": 3,
                "nonpersistable_capability_grant": 1,
                "nonpersistable_role_bundle": 1,
                "role_assignment_scope_too_broad": 1,
                "unknown_capability_grant": 1,
                "unknown_role_bundle_capability": 1,
            }
        )
        assert "synthetic.unknown_private_capability" not in rendered
        assert scope.account.email not in rendered
    finally:
        role_assignment_model.objects.filter(
            organization_id=scope.organization.id
        ).delete()
        scope.grant_model.objects.filter(organization_id=scope.organization.id).delete()
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE authorization_rolebundle DISABLE TRIGGER "
                "authorization_role_bundle_immutable"
            )
        try:
            scope.role_bundle_model.objects.filter(
                organization_id=scope.organization.id
            ).exclude(pk=scope.role_bundle.id).delete()
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE authorization_rolebundle ENABLE TRIGGER "
                    "authorization_role_bundle_immutable"
                )
        _migrate(
            AUTHORIZATION_AFTER_ACTIVATION,
            WORKFORCE_SCOPE_V2_INTEGRITY,
        )


def test_legacy_edition_wide_position_role_evidence_is_review_only() -> None:
    position, role_assignment = _create_runtime_position()

    rendered, report = _run_readiness()

    assert report == _expected_report(legacy_review_count=1)
    assert report["status"] == "ready"
    assert report["blocker_total"] == 0
    assert str(position.id) not in rendered
    assert str(role_assignment.id) not in rendered
    assert "@" not in rendered
