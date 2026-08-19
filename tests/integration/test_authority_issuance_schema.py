"""Additive schema and database-boundary evidence for ADR 0044."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import (
    IntegrityError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.models import AuthorityControl, AuthorityIssuance
from maru.organizations.models import Organization
from maru.organizations.representation import (
    invite_representation_controller,
    provision_executive_board,
    respond_to_representation_invitation,
)
from tests.factories import (
    AccountFactory,
    AuthorityControlFactory,
    AuthorityIssuanceFactory,
    CapabilityGrantFactory,
    ConventionSeriesFactory,
    EventEditionFactory,
    OrganizationFactory,
    RoleBundleFactory,
)
from tests.support.migrations import restore_current_migration_graph

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

AUTHORIZATION_BEFORE_ISSUANCE = ("authorization", "0005_scope_v2_activation")
AUTHORIZATION_AFTER_ISSUANCE = ("authorization", "0006_authority_issuance_schema")


def _migrate(*targets: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(list(targets))
    return executor


def _historical_grant(executor: MigrationExecutor):  # type: ignore[no-untyped-def]
    apps = executor.loader.project_state([AUTHORIZATION_BEFORE_ISSUANCE]).apps
    account_model = apps.get_model("identity", "Account")
    organization_model = apps.get_model("organizations", "Organization")
    grant_model = apps.get_model("authorization", "CapabilityGrant")
    organization = organization_model.objects.create(
        slug=f"issuance-legacy-{uuid4().hex[:12]}",
        name="Synthetic issuance compatibility organization",
    )
    principal = account_model.objects.create(
        email=f"issuance-principal-{uuid4().hex}@example.invalid",
        password="!synthetic-unusable",
        display_name="Synthetic issuance principal",
        email_verified_at=timezone.now(),
    )
    actor = account_model.objects.create(
        email=f"issuance-actor-{uuid4().hex}@example.invalid",
        password="!synthetic-unusable",
        display_name="Synthetic issuance actor",
        email_verified_at=timezone.now(),
    )
    approver = account_model.objects.create(
        email=f"issuance-approver-{uuid4().hex}@example.invalid",
        password="!synthetic-unusable",
        display_name="Synthetic issuance approver",
        email_verified_at=timezone.now(),
    )
    return grant_model.objects.create(
        organization_id=organization.id,
        principal_id=principal.id,
        capability_code="events.view_basic",
        effective_from=timezone.now(),
        granted_by_id=actor.id,
        approved_by_id=approver.id,
        reason="Synthetic legacy authority without inferred provenance.",
    )


def _persistent_control_scope(
    *,
    source_capability: str = "authorization.grant_direct",
    source_edition=None,  # type: ignore[no-untyped-def]
    target_edition=None,  # type: ignore[no-untyped-def]
    source_expires_at=None,  # type: ignore[no-untyped-def]
    target_expires_at=None,  # type: ignore[no-untyped-def]
):
    organization = (
        source_edition.organization
        if source_edition is not None
        else target_edition.organization
        if target_edition is not None
        else OrganizationFactory()
    )
    actor = AccountFactory()
    approver = AccountFactory()
    evaluated_at = timezone.now()
    source_grant = CapabilityGrantFactory(
        organization=organization,
        edition=source_edition,
        principal=actor,
        capability_code=source_capability,
        effective_from=evaluated_at - timedelta(minutes=1),
        expires_at=source_expires_at,
    )
    source_issuance = AuthorityIssuanceFactory(
        capability_grant=source_grant,
        evaluated_at=evaluated_at,
    )
    target_grant = CapabilityGrantFactory(
        organization=organization,
        edition=target_edition,
        granted_by=actor,
        approved_by=approver,
        effective_from=evaluated_at,
        expires_at=target_expires_at,
    )
    target_issuance = AuthorityIssuanceFactory(
        capability_grant=target_grant,
        evaluated_at=evaluated_at,
    )
    return source_issuance, target_issuance, actor


def _raw_persistent_actor_control(
    *,
    source: AuthorityIssuance,
    target: AuthorityIssuance,
    principal=None,  # type: ignore[no-untyped-def]
    policy_version: str | None = None,
    evaluated_at=None,  # type: ignore[no-untyped-def]
) -> AuthorityControl:
    return AuthorityControl(
        issuance=target,
        role=AuthorityControl.Role.ACTOR,
        principal=principal or source.capability_grant.principal,
        basis=AuthorityControl.Basis.PERSISTENT_AUTHORITY,
        source_issuance=source,
        policy_version=policy_version or target.policy_version,
        evaluated_at=evaluated_at or target.evaluated_at,
    )


def test_additive_forward_preserves_legacy_authority_without_inference() -> None:
    executor = _migrate(AUTHORIZATION_BEFORE_ISSUANCE)
    grant = _historical_grant(executor)

    executor = _migrate(AUTHORIZATION_AFTER_ISSUANCE)
    apps = executor.loader.project_state([AUTHORIZATION_AFTER_ISSUANCE]).apps
    assert (
        apps.get_model("authorization", "CapabilityGrant")
        .objects.filter(pk=grant.pk)
        .exists()
    )
    assert not apps.get_model("authorization", "AuthorityIssuance").objects.exists()
    assert not apps.get_model("authorization", "AuthorityControl").objects.exists()


def test_fresh_forward_and_clean_reverse_are_symmetric() -> None:
    _migrate(AUTHORIZATION_BEFORE_ISSUANCE)
    try:
        _migrate(AUTHORIZATION_AFTER_ISSUANCE)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass('authorization_authorityissuance'), "
                "to_regclass('authorization_authoritycontrol')"
            )
            assert cursor.fetchone() == (
                "authorization_authorityissuance",
                "authorization_authoritycontrol",
            )

        _migrate(AUTHORIZATION_BEFORE_ISSUANCE)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass('authorization_authorityissuance'), "
                "to_regclass('authorization_authoritycontrol')"
            )
            assert cursor.fetchone() == (None, None)
    finally:
        restore_current_migration_graph()


def test_nonempty_ledger_refuses_schema_downgrade() -> None:
    AuthorityIssuanceFactory()

    with pytest.raises(
        RuntimeError,
        match="Cannot reverse authority issuance schema",
    ):
        _migrate(AUTHORIZATION_BEFORE_ISSUANCE)


def test_ordinal_public_identity_and_additive_zero_control_compatibility() -> None:
    legacy_grant = CapabilityGrantFactory()
    first = AuthorityIssuanceFactory(capability_grant=legacy_grant)
    second = AuthorityIssuanceFactory()

    assert first.ordinal < second.ordinal
    assert first.public_id != second.public_id
    assert not first.controls.exists()
    assert not AuthorityIssuance.objects.filter(
        capability_grant=CapabilityGrantFactory()
    ).exists()


def test_delegated_issuance_requires_earlier_parent_and_zero_controls() -> None:
    organization = OrganizationFactory()
    parent_principal = AccountFactory()
    parent = CapabilityGrantFactory(
        organization=organization,
        principal=parent_principal,
        capability_code="events.view_basic",
    )
    child = CapabilityGrantFactory(
        organization=organization,
        principal=AccountFactory(),
        capability_code=parent.capability_code,
        effective_from=parent.effective_from,
        granted_by=parent_principal,
        delegated_from=parent,
    )

    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="earlier parent issuance"),
    ):
        AuthorityIssuance.objects.bulk_create(
            [
                AuthorityIssuance(
                    capability_grant=child,
                    policy_version=POLICY_VERSION,
                    evaluated_at=timezone.now(),
                )
            ]
        )

    parent_issuance = AuthorityIssuanceFactory(capability_grant=parent)
    child_issuance = AuthorityIssuanceFactory(capability_grant=child)
    assert parent_issuance.ordinal < child_issuance.ordinal
    assert not child_issuance.controls.exists()

    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="must have zero controls"),
    ):
        AuthorityControl.objects.bulk_create(
            [
                AuthorityControl(
                    issuance=child_issuance,
                    role=AuthorityControl.Role.ACTOR,
                    principal=child.granted_by,
                    basis=AuthorityControl.Basis.PERSISTENT_AUTHORITY,
                    source_issuance=parent_issuance,
                    policy_version=child_issuance.policy_version,
                    evaluated_at=child_issuance.evaluated_at,
                )
            ]
        )


def test_model_and_database_keep_issuance_and_controls_append_only() -> None:
    control = AuthorityControlFactory()
    issuance = control.issuance
    uncontrolled_issuance = AuthorityIssuanceFactory()

    issuance.policy_version = "rewritten"
    with pytest.raises(ValidationError, match="immutable"):
        issuance.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        issuance.delete()
    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="authority issuances are immutable"),
    ):
        AuthorityIssuance.objects.filter(pk=issuance.pk).update(
            policy_version="rewritten"
        )
    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="authority issuances cannot be deleted"),
    ):
        AuthorityIssuance.objects.filter(pk=uncontrolled_issuance.pk).delete()

    control.policy_version = "rewritten"
    with pytest.raises(ValidationError, match="immutable"):
        control.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        control.delete()
    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="authority controls are immutable"),
    ):
        AuthorityControl.objects.filter(pk=control.pk).update(
            policy_version="rewritten"
        )
    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="authority controls cannot be deleted"),
    ):
        AuthorityControl.objects.filter(pk=control.pk).delete()


def test_database_rejects_missing_multiple_and_duplicate_typed_targets() -> None:
    grant = CapabilityGrantFactory()
    bundle = RoleBundleFactory(organization=grant.organization)
    evaluated_at = timezone.now()

    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="authorization_issuance_exact_target"),
    ):
        AuthorityIssuance.objects.bulk_create(
            [
                AuthorityIssuance(
                    policy_version=POLICY_VERSION,
                    evaluated_at=evaluated_at,
                )
            ]
        )
    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="authorization_issuance_exact_target"),
    ):
        AuthorityIssuance.objects.bulk_create(
            [
                AuthorityIssuance(
                    capability_grant=grant,
                    role_bundle=bundle,
                    policy_version=POLICY_VERSION,
                    evaluated_at=evaluated_at,
                )
            ]
        )
    AuthorityIssuanceFactory(capability_grant=grant)
    with transaction.atomic(), pytest.raises(IntegrityError, match="unique"):
        AuthorityIssuance.objects.bulk_create(
            [
                AuthorityIssuance(
                    capability_grant=grant,
                    policy_version=POLICY_VERSION,
                    evaluated_at=evaluated_at,
                )
            ]
        )


def test_persistent_controls_accept_exact_earlier_dual_sources() -> None:
    organization = OrganizationFactory()
    actor = AccountFactory()
    approver = AccountFactory()
    evaluated_at = timezone.now()
    actor_source = AuthorityIssuanceFactory(
        capability_grant=CapabilityGrantFactory(
            organization=organization,
            principal=actor,
            capability_code="authorization.grant_direct",
            effective_from=evaluated_at - timedelta(minutes=1),
        ),
        evaluated_at=evaluated_at,
    )
    approver_source = AuthorityIssuanceFactory(
        capability_grant=CapabilityGrantFactory(
            organization=organization,
            principal=approver,
            capability_code="authorization.grant_direct",
            effective_from=evaluated_at - timedelta(minutes=1),
        ),
        evaluated_at=evaluated_at,
    )
    target = AuthorityIssuanceFactory(
        capability_grant=CapabilityGrantFactory(
            organization=organization,
            granted_by=actor,
            approved_by=approver,
            effective_from=evaluated_at,
        ),
        evaluated_at=evaluated_at,
    )

    actor_control = _raw_persistent_actor_control(
        source=actor_source,
        target=target,
    )
    approver_control = AuthorityControl(
        issuance=target,
        role=AuthorityControl.Role.APPROVER,
        principal=approver,
        basis=AuthorityControl.Basis.PERSISTENT_AUTHORITY,
        source_issuance=approver_source,
        policy_version=target.policy_version,
        evaluated_at=target.evaluated_at,
    )
    actor_control.save()
    approver_control.save()

    assert list(target.controls.order_by("role").values_list("role", flat=True)) == [
        AuthorityControl.Role.ACTOR,
        AuthorityControl.Role.APPROVER,
    ]


def test_concurrent_controls_cannot_commit_the_same_principal_twice() -> None:
    organization = OrganizationFactory()
    controller = AccountFactory()
    evaluated_at = timezone.now()
    source = AuthorityIssuanceFactory(
        capability_grant=CapabilityGrantFactory(
            organization=organization,
            principal=controller,
            capability_code="authorization.grant_direct",
            effective_from=evaluated_at - timedelta(minutes=1),
        ),
        evaluated_at=evaluated_at,
    )
    target = AuthorityIssuanceFactory(
        capability_grant=CapabilityGrantFactory(
            organization=organization,
            principal=AccountFactory(),
            granted_by=controller,
            approved_by=controller,
            effective_from=evaluated_at,
        ),
        evaluated_at=evaluated_at,
    )
    first_inserted = Event()
    release_first = Event()
    second_backend_pid: Queue[int] = Queue(maxsize=1)

    def insert_control(*, role: str, hold_open: bool) -> str:
        close_old_connections()
        try:
            with transaction.atomic():
                if not hold_open:
                    assert first_inserted.wait(timeout=10)
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_backend_pid()")
                        row = cursor.fetchone()
                    assert row is not None
                    second_backend_pid.put(int(row[0]), timeout=10)
                AuthorityControl.objects.bulk_create(
                    [
                        AuthorityControl(
                            issuance_id=target.ordinal,
                            role=role,
                            principal_id=controller.id,
                            basis=AuthorityControl.Basis.PERSISTENT_AUTHORITY,
                            source_issuance_id=source.ordinal,
                            policy_version=target.policy_version,
                            evaluated_at=target.evaluated_at,
                        )
                    ]
                )
                if hold_open:
                    first_inserted.set()
                    assert release_first.wait(timeout=10)
        except IntegrityError:
            return "rejected"
        else:
            return "committed"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        actor_future = executor.submit(
            insert_control,
            role=AuthorityControl.Role.ACTOR,
            hold_open=True,
        )
        approver_future = executor.submit(
            insert_control,
            role=AuthorityControl.Role.APPROVER,
            hold_open=False,
        )
        backend_pid = second_backend_pid.get(timeout=10)
        deadline = monotonic() + 10
        try:
            while monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                        [backend_pid],
                    )
                    row = cursor.fetchone()
                if row is not None and row[0] == "Lock":
                    break
                sleep(0.01)
            else:
                raise AssertionError(
                    "The competing control insert did not wait on uniqueness."
                )
        finally:
            release_first.set()

        outcomes = sorted(
            (actor_future.result(timeout=10), approver_future.result(timeout=10))
        )

    assert outcomes == ["committed", "rejected"]
    assert AuthorityControl.objects.filter(issuance=target).count() == 1


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("attribution", "target attribution mismatch"),
        ("evaluation", "evaluation does not match issuance"),
        ("policy", "evaluation does not match issuance"),
        ("capability", "source capability mismatch"),
        ("revoked", "source is not current"),
        ("inactive", "source is not current"),
    ],
)
def test_database_rejects_invalid_persistent_control_evidence(
    mutation: str,
    message: str,
) -> None:
    source_capability = (
        "events.view_basic"
        if mutation == "capability"
        else "authorization.grant_direct"
    )
    source, target, actor = _persistent_control_scope(
        source_capability=source_capability
    )
    principal = AccountFactory() if mutation == "attribution" else actor
    evaluated_at = (
        target.evaluated_at + timedelta(seconds=1)
        if mutation == "evaluation"
        else target.evaluated_at
    )
    policy_version = "synthetic-mismatched-policy" if mutation == "policy" else None
    if mutation == "revoked":
        source.capability_grant.__class__.objects.filter(
            pk=source.capability_grant_id
        ).update(
            revoked_at=timezone.now(),
            revoked_by=AccountFactory(),
            revocation_reason="Synthetic revocation before control insertion.",
        )
    if mutation == "inactive":
        actor.is_active = False
        actor.save(update_fields=("is_active",))

    with transaction.atomic(), pytest.raises(IntegrityError, match=message):
        AuthorityControl.objects.bulk_create(
            [
                _raw_persistent_actor_control(
                    source=source,
                    target=target,
                    principal=principal,
                    policy_version=policy_version,
                    evaluated_at=evaluated_at,
                )
            ]
        )


def test_database_rejects_unknown_control_role_and_incomplete_basis() -> None:
    source, target, actor = _persistent_control_scope()

    with transaction.atomic(), pytest.raises(IntegrityError, match="role is unknown"):
        AuthorityControl.objects.bulk_create(
            [
                AuthorityControl(
                    issuance=target,
                    role="invented",
                    principal=actor,
                    basis=AuthorityControl.Basis.PERSISTENT_AUTHORITY,
                    source_issuance=source,
                    policy_version=target.policy_version,
                    evaluated_at=target.evaluated_at,
                )
            ]
        )
    with (
        transaction.atomic(),
        pytest.raises(
            IntegrityError,
            match=r"earlier issuance|authorization_control_basis_shape",
        ),
    ):
        AuthorityControl.objects.bulk_create(
            [
                AuthorityControl(
                    issuance=target,
                    role=AuthorityControl.Role.ACTOR,
                    principal=actor,
                    basis=AuthorityControl.Basis.PERSISTENT_AUTHORITY,
                    policy_version=target.policy_version,
                    evaluated_at=target.evaluated_at,
                )
            ]
        )


def test_database_rejects_later_sideways_and_shorter_sources() -> None:
    organization = OrganizationFactory()
    series = ConventionSeriesFactory(organization=organization)
    first_edition = EventEditionFactory(
        organization=organization,
        series=series,
    )
    second_edition = EventEditionFactory(
        organization=organization,
        series=series,
    )

    sideways_source, sideways_target, _ = _persistent_control_scope(
        source_edition=first_edition,
        target_edition=second_edition,
    )
    with transaction.atomic(), pytest.raises(IntegrityError, match="scope mismatch"):
        AuthorityControl.objects.bulk_create(
            [
                _raw_persistent_actor_control(
                    source=sideways_source,
                    target=sideways_target,
                )
            ]
        )

    now = timezone.now()
    short_source, long_target, _ = _persistent_control_scope(
        source_expires_at=now + timedelta(days=1),
        target_expires_at=now + timedelta(days=2),
    )
    with transaction.atomic(), pytest.raises(IntegrityError, match="source horizon"):
        AuthorityControl.objects.bulk_create(
            [
                _raw_persistent_actor_control(
                    source=short_source,
                    target=long_target,
                )
            ]
        )

    actor = AccountFactory()
    approver = AccountFactory()
    target_grant = CapabilityGrantFactory(
        organization=organization,
        granted_by=actor,
        approved_by=approver,
    )
    earlier_target = AuthorityIssuanceFactory(capability_grant=target_grant)
    later_source = AuthorityIssuanceFactory(
        capability_grant=CapabilityGrantFactory(
            organization=organization,
            principal=actor,
            capability_code="authorization.grant_direct",
            effective_from=target_grant.effective_from - timedelta(minutes=1),
        ),
        evaluated_at=earlier_target.evaluated_at,
    )
    with transaction.atomic(), pytest.raises(IntegrityError, match="earlier issuance"):
        AuthorityControl.objects.bulk_create(
            [
                _raw_persistent_actor_control(
                    source=later_source,
                    target=earlier_target,
                )
            ]
        )


def test_representation_bases_require_exact_activated_ceremony() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = provision_executive_board(
        actor=administrator,
        organization_id=organization.id,
        reason="Create synthetic provenance basis evidence.",
        correlation_id=uuid4(),
    )
    controller = AccountFactory()
    appointment = invite_representation_controller(
        actor=administrator,
        representation_id=representation.id,
        account_id=controller.id,
        reason="Invite a synthetic provenance controller.",
        correlation_id=uuid4(),
    )
    respond_to_representation_invitation(
        actor=controller,
        appointment_id=appointment.id,
        expected_version=appointment.invitation_version,
        accept=True,
        correlation_id=uuid4(),
    )
    board_bundle = RoleBundleFactory(
        organization=organization,
        code="executive-board",
        name="Executive Board",
        created_by=administrator,
        approved_by=controller,
    )
    issuance = AuthorityIssuanceFactory(
        capability_grant=None,
        role_bundle=board_bundle,
    )

    for control in (
        AuthorityControl(
            issuance=issuance,
            role=AuthorityControl.Role.ACTOR,
            principal=administrator,
            basis=AuthorityControl.Basis.PLATFORM_REPRESENTATION_BOOTSTRAP,
            representation=representation,
            policy_version=issuance.policy_version,
            evaluated_at=issuance.evaluated_at,
        ),
        AuthorityControl(
            issuance=issuance,
            role=AuthorityControl.Role.APPROVER,
            principal=controller,
            basis=AuthorityControl.Basis.REPRESENTATION_ACCEPTANCE,
            appointment=appointment,
            policy_version=issuance.policy_version,
            evaluated_at=issuance.evaluated_at,
        ),
    ):
        with (
            transaction.atomic(),
            pytest.raises(
                IntegrityError,
                match=r"representation mismatch|appointment mismatch",
            ),
        ):
            AuthorityControl.objects.bulk_create([control])
