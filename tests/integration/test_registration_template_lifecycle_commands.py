from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)

from maru.effects.models import DomainEvent
from maru.identity.models import Account
from maru.registration.models import (
    RegistrationProvenanceStatus,
    RegistrationTemplate,
    RegistrationTemplateCatalogCommandReceipt,
    RegistrationTemplateCatalogCommandTarget,
    RegistrationTemplateCatalogControl,
    RegistrationTemplateProduct,
    TemplateStatus,
)
from maru.registration.template_lifecycle import (
    RegistrationTemplateAuthorizationDeniedError,
    RegistrationTemplateRetryConflictError,
    publish_registration_template,
)
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RegistrationTemplateFactory,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _grant(actor: Account, edition: object) -> None:
    CapabilityGrantFactory(
        organization=edition.organization,  # type: ignore[attr-defined]
        edition=edition,
        principal=actor,
        capability_code="registration.manage_configuration",
    )


def _draft_template(edition: object, actor: Account, *, global_scope: bool = False):
    template = RegistrationTemplateFactory(
        organization=edition.organization,  # type: ignore[attr-defined]
        series=None if global_scope else edition.series,  # type: ignore[attr-defined]
        code=f"synthetic-{uuid4().hex[:12]}",
        created_by_id=actor.id,
    )
    RegistrationTemplateProduct.objects.create(
        template=template,
        code="weekend",
        name="Synthetic weekend admission",
        description="Bounded synthetic reusable admission.",
        price_minor=12_000,
        capacity=400,
        position=10,
        entitlement_code="weekend-admission",
        entitlement_name="Weekend admission",
    )
    return template


def _values(actor: Account, edition: object, template: RegistrationTemplate, **changes):
    values = {
        "actor": actor,
        "organization_id": edition.organization_id,  # type: ignore[attr-defined]
        "series_id": edition.series_id,  # type: ignore[attr-defined]
        "edition_id": edition.id,  # type: ignore[attr-defined]
        "template_id": template.id,
        "expected_version": 0,
        "reason": "Publish a bounded synthetic reusable registration template.",
        "retry_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }
    values.update(changes)
    return values


def _force_raw_complete_promotion(
    template: RegistrationTemplate, published_at: object
) -> None:
    with transaction.atomic():
        RegistrationTemplate.objects.filter(pk=template.id).update(
            status=TemplateStatus.PUBLISHED,
            published_at=published_at,
            provenance_status=RegistrationProvenanceStatus.COMPLETE,
            content_digest="f" * 64,
            created_in_catalog_version=1,
            last_changed_in_catalog_version=1,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SET CONSTRAINTS registration_template_publication_v2_exact IMMEDIATE"
            )


def _truncate_catalog_receipts_with_reset_disabled() -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL maru.authority_provenance_test_reset = 'off'")
        cursor.execute(
            "TRUNCATE registration_registrationtemplatecatalogcommandreceipt CASCADE"
        )


def test_publication_writes_exact_graph_and_replays_only_exact_payload() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    template = _draft_template(edition, actor)
    values = _values(actor, edition, template)

    first = publish_registration_template(**values)  # type: ignore[arg-type]
    replay = publish_registration_template(
        **{**values, "correlation_id": uuid4()}  # type: ignore[arg-type]
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.receipt_id == first.receipt_id
    template.refresh_from_db()
    assert template.status == TemplateStatus.PUBLISHED
    assert template.provenance_status == RegistrationProvenanceStatus.COMPLETE
    assert template.created_in_catalog_version == first.resulting_version == 1
    assert template.last_changed_in_catalog_version == 1
    assert template.sections.count() == 0
    assert template.questions.count() == 0
    assert (
        template.products.exclude(
            created_in_catalog_version=1,
            last_changed_in_catalog_version=1,
        ).count()
        == 0
    )
    receipt = RegistrationTemplateCatalogCommandReceipt.objects.get(pk=first.receipt_id)
    assert receipt.targets.count() == 1
    assert (
        DomainEvent.objects.filter(
            aggregate_type="registration.template_catalog",
            aggregate_id=first.catalog_id,
            aggregate_version=1,
            event_name="registration.template.published.v1",
        ).count()
        == 1
    )
    with pytest.raises(RegistrationTemplateRetryConflictError):
        publish_registration_template(
            **{**values, "reason": "Changed retry payload."}  # type: ignore[arg-type]
        )


def test_publication_authorization_is_exact_and_global_scope_is_platform_only() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    other = AccountFactory()
    _grant(actor, edition)
    template = _draft_template(edition, actor)
    with pytest.raises(RegistrationTemplateAuthorizationDeniedError):
        publish_registration_template(
            **_values(other, edition, template)  # type: ignore[arg-type]
        )

    global_template = _draft_template(edition, actor, global_scope=True)
    with pytest.raises(RegistrationTemplateAuthorizationDeniedError):
        publish_registration_template(
            **_values(actor, edition, global_template)  # type: ignore[arg-type]
        )
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    result = publish_registration_template(
        **_values(administrator, edition, global_template)  # type: ignore[arg-type]
    )
    assert result.template_id == global_template.id


def test_publication_dependency_failure_rolls_back_catalog_and_template() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    template = _draft_template(edition, actor)
    with (
        patch(
            "maru.registration.template_lifecycle.append_audit",
            side_effect=RuntimeError("synthetic audit outage"),
        ),
        pytest.raises(RuntimeError, match="synthetic audit outage"),
    ):
        publish_registration_template(
            **_values(actor, edition, template)  # type: ignore[arg-type]
        )
    template.refresh_from_db()
    assert template.status == TemplateStatus.DRAFT
    assert template.provenance_status == RegistrationProvenanceStatus.LEGACY_UNKNOWN
    assert template.created_in_catalog_version is None
    assert not RegistrationTemplateCatalogControl.objects.filter(
        organization=edition.organization
    ).exists()
    assert not RegistrationTemplateCatalogCommandReceipt.objects.exists()
    assert not DomainEvent.objects.filter(
        event_name="registration.template.published.v1"
    ).exists()


def test_raw_complete_promotion_and_catalog_evidence_mutation_fail_closed() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    raw_template = _draft_template(edition, actor)
    with pytest.raises(DatabaseError, match="publication evidence is incomplete"):
        _force_raw_complete_promotion(raw_template, edition.created_at)
    raw_template.refresh_from_db()
    assert raw_template.status == TemplateStatus.DRAFT

    template = _draft_template(edition, actor)
    result = publish_registration_template(
        **_values(actor, edition, template)  # type: ignore[arg-type]
    )
    receipt = RegistrationTemplateCatalogCommandReceipt.objects.get(
        pk=result.receipt_id
    )
    target = RegistrationTemplateCatalogCommandTarget.objects.get(receipt=receipt)
    with (
        pytest.raises(DatabaseError, match="catalog evidence is immutable"),
        transaction.atomic(),
    ):
        RegistrationTemplateCatalogCommandReceipt.objects.filter(pk=receipt.id).update(
            reason="Raw rewrite"
        )
    with (
        pytest.raises(DatabaseError, match="catalog evidence is retained"),
        transaction.atomic(),
    ):
        RegistrationTemplateCatalogCommandTarget.objects.filter(pk=target.id).delete()
    with pytest.raises(DatabaseError, match="cannot be truncated"):
        _truncate_catalog_receipts_with_reset_disabled()


def test_same_retry_publication_concurrency_commits_one_graph() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant(actor, edition)
    template = _draft_template(edition, actor)
    values = _values(actor, edition, template)

    def run(_index: int):
        close_old_connections()
        try:
            return publish_registration_template(
                **{**values, "correlation_id": uuid4()}  # type: ignore[arg-type]
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (1, 2)))
    assert sorted(result.replayed for result in results) == [False, True]
    assert len({result.receipt_id for result in results}) == 1
    assert RegistrationTemplateCatalogCommandReceipt.objects.count() == 1
    assert RegistrationTemplateCatalogCommandTarget.objects.count() == 1
    assert (
        DomainEvent.objects.filter(
            event_name="registration.template.published.v1"
        ).count()
        == 1
    )


def test_template_catalog_trigger_functions_are_closed_and_pinned() -> None:
    names = (
        "maru_assert_registration_template_publication_v1",
        "maru_guard_registration_template_catalog_v2",
        "maru_guard_registration_configuration_activation_v2",
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.proname, p.proacl, p.proconfig
              FROM pg_catalog.pg_proc AS p
              JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
             WHERE n.nspname = 'public' AND p.proname = ANY(%s)
             ORDER BY p.proname
            """,
            [list(names)],
        )
        rows = cursor.fetchall()
    assert [row[0] for row in rows] == sorted(names)
    for _name, acl, settings in rows:
        assert acl is not None
        assert not any(entry.startswith("=") for entry in acl)
        assert "search_path=pg_catalog, public, pg_temp" in settings
        assert "TimeZone=UTC" in settings
