"""Charity partner governance, isolation, and public projection coverage."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from django.db import DatabaseError, connection, transaction
from django.test import Client, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.models import ScopedResourceBinding
from maru.authorization.provenance_readiness import (
    _FUNCTION_DEFINITION_SHA256,
    _function_definition_fingerprint,
)
from maru.charities.authorization import resolve_charity_selection_target
from maru.charities.bindings import charity_selection_binding_id
from maru.charities.models import (
    CharityPartner,
    CharityPartnerMedia,
    CharitySelection,
    CharitySelectionTimelineEntry,
)
from maru.charities.queries import (
    load_charity_selection_review,
    public_charities_for_edition,
)
from maru.charities.services import (
    CharityAuthorizationDeniedError,
    CharityIndependentApprovalError,
    CharityPartnerProfile,
    CharityRetryConflictError,
    add_charity_partner_media,
    add_charity_selection_private_comment,
    approve_charity_partner_media,
    confirm_charity_selection,
    create_charity_partner,
    propose_charity_selection,
    publish_charity_selection,
    reject_charity_selection,
    submit_charity_selection,
    update_charity_partner,
)
from maru.effects.models import DomainEvent, OutboxMessage
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    OrganizationFactory,
)
from tests.workforce_helpers import create_department_for_test

if TYPE_CHECKING:
    from maru.events.models import EventEdition
    from maru.identity.models import Account
    from maru.workforce.models import Department

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


@dataclass(frozen=True, slots=True)
class _Scope:
    edition: EventEdition
    department: Department
    manager: Account
    media_reviewer: Account
    proposer: Account
    reviewer: Account
    publisher: Account
    private_reader: Account


def _grant_organization(actor: Account, scope: _Scope, capability: str) -> None:
    CapabilityGrantFactory(
        organization=scope.edition.organization,
        principal=actor,
        capability_code=capability,
    )


def _grant_edition(actor: Account, scope: _Scope, capability: str) -> None:
    CapabilityGrantFactory(
        organization=scope.edition.organization,
        edition=scope.edition,
        principal=actor,
        capability_code=capability,
    )


def _grant_selection(
    actor: Account,
    scope: _Scope,
    selection: CharitySelection,
    capability: str,
) -> None:
    binding = ScopedResourceBinding.objects.get(
        resource_kind=ScopedResourceBinding.ResourceKind.CHARITY_SELECTION,
        resource_id=selection.id,
    )
    CapabilityGrantFactory(
        organization=scope.edition.organization,
        edition=scope.edition,
        department=scope.department,
        resource_binding=binding,
        principal=actor,
        capability_code=capability,
    )


def _scope() -> _Scope:
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        name="Charity Relations",
        expected_code="charity-relations",
    )
    scope = _Scope(
        edition=edition,
        department=department,
        manager=AccountFactory(),
        media_reviewer=AccountFactory(),
        proposer=AccountFactory(),
        reviewer=AccountFactory(),
        publisher=AccountFactory(),
        private_reader=AccountFactory(),
    )
    _grant_organization(scope.manager, scope, "charities.manage_partners")
    _grant_organization(scope.manager, scope, "charities.view_partners")
    _grant_organization(
        scope.media_reviewer,
        scope,
        "charities.manage_partners",
    )
    _grant_edition(scope.proposer, scope, "charities.propose_selection")
    _grant_edition(scope.proposer, scope, "charities.view_review_queue")
    return scope


def _active_partner(scope: _Scope) -> CharityPartner:
    created = create_charity_partner(
        actor=scope.manager,
        organization_id=scope.edition.organization_id,
        slug="animal-aid",
        profile=CharityPartnerProfile(
            legal_name="Animal Aid Registered Association",
            imprint_name="Animal Aid e.V.",
            public_name="Animal Aid",
            short_description="Helping animals in the region.",
            description="Private organizer diligence and relationship notes.",
            location_name="Budapest",
            postal_address="Private postal address",
            country_code="HU",
            website_url="https://charity.example.invalid",
            contact_email="private-contact@example.invalid",
            contact_phone="+3612345678",
        ),
        reason="Create a reusable beneficiary record.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    update_charity_partner(
        actor=scope.manager,
        organization_id=scope.edition.organization_id,
        partner_id=created.object_id,
        expected_version=created.resulting_version,
        changes={"lifecycle": CharityPartner.Lifecycle.ACTIVE},
        reason="Diligence is complete.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return CharityPartner.objects.get(id=created.object_id)


def _proposed_selection(
    scope: _Scope,
    partner: CharityPartner,
) -> CharitySelection:
    result = propose_charity_selection(
        actor=scope.proposer,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        partner_id=partner.id,
        responsible_department_id=scope.department.id,
        reason="Propose this beneficiary for the edition.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return CharitySelection.objects.get(id=result.object_id)


def test_confirmed_publication_uses_only_approved_snapshot_fields() -> None:
    scope = _scope()
    partner = _active_partner(scope)
    media_added = add_charity_partner_media(
        actor=scope.manager,
        organization_id=scope.edition.organization_id,
        partner_id=partner.id,
        kind="logo",
        source_reference="private://original/logo-file",
        owner_name="Animal Aid",
        license_basis="Written permission retained by the organizer.",
        usage_scope="Edition website and charity report.",
        attribution="Animal Aid",
        expires_at=None,
        reason="Register the supplied logo and its usage terms.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    media_approved = approve_charity_partner_media(
        actor=scope.media_reviewer,
        organization_id=scope.edition.organization_id,
        partner_id=partner.id,
        media_id=media_added.object_id,
        expected_version=media_added.resulting_version,
        public_reference="https://media.example.invalid/approved-logo.webp",
        reason="The ownership and usage evidence is complete.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    selection = _proposed_selection(scope, partner)
    _grant_selection(scope.reviewer, scope, selection, "charities.review_selection")
    _grant_selection(scope.publisher, scope, selection, "charities.publish_selection")
    _grant_selection(scope.private_reader, scope, selection, "charities.view_selection")
    _grant_selection(
        scope.private_reader, scope, selection, "charities.comment_selection"
    )

    submitted = submit_charity_selection(
        actor=scope.proposer,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        selection_id=selection.id,
        expected_version=selection.aggregate_version,
        reason="The proposal is ready for independent review.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    confirmed = confirm_charity_selection(
        actor=scope.reviewer,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        selection_id=selection.id,
        expected_version=submitted.resulting_version,
        reason="The beneficiary is confirmed for this edition.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    commented = add_charity_selection_private_comment(
        actor=scope.private_reader,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        selection_id=selection.id,
        expected_version=confirmed.resulting_version,
        private_comment="Private payment-coordination note; never publish this.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    publish_charity_selection(
        actor=scope.publisher,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        selection_id=selection.id,
        expected_version=commented.resulting_version,
        media_ids=(media_approved.object_id,),
        reason="Approve the minimized public beneficiary card.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )

    public = public_charities_for_edition(
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
    )
    assert len(public) == 1
    payload = asdict(public[0])
    assert payload["public_name"] == "Animal Aid"
    assert payload["media"][0]["reference"].endswith("approved-logo.webp")
    serialized = repr(payload)
    assert "Registered Association" not in serialized
    assert "private-contact" not in serialized
    assert "Private postal" not in serialized
    assert "private://original" not in serialized
    assert "payment-coordination" not in serialized

    charity_events = DomainEvent.objects.filter(aggregate_type__startswith="charities.")
    assert charity_events.count() == 9
    assert OutboxMessage.objects.filter(event__in=charity_events).count() == 9
    assert AuditEvent.objects.filter(operation__startswith="charities.").count() == 9


def test_rejection_reason_and_private_comment_remain_purpose_scoped() -> None:
    scope = _scope()
    partner = _active_partner(scope)
    selection = _proposed_selection(scope, partner)
    _grant_selection(scope.reviewer, scope, selection, "charities.review_selection")
    _grant_selection(scope.private_reader, scope, selection, "charities.view_selection")
    _grant_selection(
        scope.private_reader, scope, selection, "charities.comment_selection"
    )
    submitted = submit_charity_selection(
        actor=scope.proposer,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        selection_id=selection.id,
        expected_version=1,
        reason="Submit for review.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    rejected = reject_charity_selection(
        actor=scope.reviewer,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        selection_id=selection.id,
        expected_version=submitted.resulting_version,
        reason="Rejected this year because the evidence arrived after the deadline.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    add_charity_selection_private_comment(
        actor=scope.private_reader,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        selection_id=selection.id,
        expected_version=rejected.resulting_version,
        private_comment="Invite the partner to apply earlier next year.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )

    assert (
        public_charities_for_edition(
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
        )
        == ()
    )
    review = load_charity_selection_review(
        actor=scope.private_reader,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        selection_id=selection.id,
        reason="test_private_review",
        source_channel="test",
    )
    assert any("deadline" in entry.reason for entry in review.timeline)
    assert any("next year" in entry.private_comment for entry in review.timeline)

    outsider = AccountFactory()
    with pytest.raises(CharityAuthorizationDeniedError):
        load_charity_selection_review(
            actor=outsider,
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            selection_id=selection.id,
            reason="unauthorized_probe",
        )


def test_platform_administrator_is_not_an_automatic_charity_subject() -> None:
    edition = EventEditionFactory()
    platform_admin = AccountFactory(is_staff=True, is_superuser=True)

    with pytest.raises(CharityAuthorizationDeniedError):
        create_charity_partner(
            actor=platform_admin,
            organization_id=edition.organization_id,
            slug="not-authorized",
            profile=CharityPartnerProfile(
                legal_name="No automatic authority",
                public_name="No automatic authority",
            ),
            reason="This must not use platform status as convention authority.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
        )


def test_idempotency_replays_exact_request_and_rejects_key_reuse() -> None:
    scope = _scope()
    retry_key = uuid4()
    kwargs = {
        "actor": scope.manager,
        "organization_id": scope.edition.organization_id,
        "slug": "replay-partner",
        "profile": CharityPartnerProfile(
            legal_name="Replay Partner Association",
            public_name="Replay Partner",
        ),
        "reason": "Exercise the idempotent creation boundary.",
        "idempotency_key": retry_key,
        "correlation_id": uuid4(),
        "source_channel": "test",
    }
    first = create_charity_partner(**kwargs)
    replay = create_charity_partner(**kwargs)
    assert replay.object_id == first.object_id
    assert replay.receipt_id == first.receipt_id
    assert replay.replayed is True

    with pytest.raises(CharityRetryConflictError):
        create_charity_partner(
            **{
                **kwargs,
                "slug": "different-payload",
                "correlation_id": uuid4(),
            }
        )


def test_selection_binding_and_scope_are_exact_and_immutable() -> None:
    scope = _scope()
    partner = _active_partner(scope)
    selection = _proposed_selection(scope, partner)
    target = resolve_charity_selection_target(
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        selection_id=selection.id,
    )
    assert target is not None
    assert target.resource_binding_id == charity_selection_binding_id(selection.id)
    assert target.department_id == scope.department.id

    other_organization = OrganizationFactory()
    assert (
        resolve_charity_selection_target(
            organization_id=other_organization.id,
            edition_id=scope.edition.id,
            selection_id=selection.id,
        )
        is None
    )

    other_department = create_department_for_test(
        edition=scope.edition,
        name="Other Department",
        expected_code="other-department",
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        CharitySelection.objects.filter(id=selection.id).update(
            responsible_department=other_department
        )
    timeline = CharitySelectionTimelineEntry.objects.get(
        selection=selection,
        sequence=1,
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        CharitySelectionTimelineEntry.objects.filter(id=timeline.id).update(
            reason="Rewritten history"
        )


def test_public_api_is_minimized_and_staff_api_authorizes_before_parsing() -> None:
    scope = _scope()
    platform_admin = AccountFactory(is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_authenticate(platform_admin)
    path = f"/api/v1/organizations/{scope.edition.organization_id}/charity-partners"

    with override_settings(ROOT_URLCONF="maru.charities.urls"):
        response = client.post(
            path,
            {"unknown": "body must not be parsed as authorized"},
            format="json",
        )
    assert response.status_code == 403
    assert response.data["code"] == "charity_authorization_denied"


def test_same_actor_cannot_confirm_and_publish() -> None:
    scope = _scope()
    partner = _active_partner(scope)
    selection = _proposed_selection(scope, partner)
    _grant_selection(scope.reviewer, scope, selection, "charities.review_selection")
    _grant_selection(scope.reviewer, scope, selection, "charities.publish_selection")
    submitted = submit_charity_selection(
        actor=scope.proposer,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        selection_id=selection.id,
        expected_version=1,
        reason="Submit for review.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    confirmed = confirm_charity_selection(
        actor=scope.reviewer,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        selection_id=selection.id,
        expected_version=submitted.resulting_version,
        reason="Confirm for this edition.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    with pytest.raises(CharityIndependentApprovalError):
        publish_charity_selection(
            actor=scope.reviewer,
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            selection_id=selection.id,
            expected_version=confirmed.resulting_version,
            media_ids=(),
            reason="This must require an independent publisher.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )


def test_charity_authorization_functions_match_readiness_fingerprints() -> None:
    identities = (
        "maru_authorization_capability_min_scope(text)",
        "maru_validate_scoped_resource_binding()",
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT required.identity,
                   procedure.prosrc,
                   language.lanname::text,
                   procedure.provolatile::text,
                   procedure.proparallel::text,
                   procedure.prosecdef,
                   procedure.proleakproof,
                   procedure.proisstrict,
                   procedure.proretset,
                   procedure.prokind::text,
                   procedure.proconfig,
                   pg_catalog.pg_get_function_result(procedure.oid)
              FROM pg_catalog.unnest(%s::text[]) AS required(identity)
              JOIN pg_catalog.pg_proc AS procedure
                ON procedure.oid = pg_catalog.to_regprocedure(
                    'public.' || required.identity
                )
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = procedure.pronamespace
               AND namespace.nspname = 'public'
              JOIN pg_catalog.pg_language AS language
                ON language.oid = procedure.prolang
             ORDER BY required.identity
            """,
            [list(identities)],
        )
        rows = cursor.fetchall()

    installed = {
        str(row[0]): _function_definition_fingerprint(tuple(row[1:])) for row in rows
    }
    expected = {
        identity: _FUNCTION_DEFINITION_SHA256[identity] for identity in identities
    }
    assert installed == expected


def _charity_workspace_url(edition: EventEdition) -> str:
    return reverse(
        "charity-workspace",
        args=(edition.organization.slug, edition.series.slug, edition.slug),
    )


def test_charity_workspace_rejects_an_edition_that_does_not_adopt_charities() -> None:
    edition = EventEditionFactory(
        adoption_profile_code="workforce_only",
        adoption_profile_version=1,
    )
    actor = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        principal=actor,
        capability_code="charities.manage_partners",
    )
    CapabilityGrantFactory(
        organization=edition.organization,
        principal=actor,
        capability_code="charities.view_partners",
    )
    client = Client()
    client.force_login(actor)

    assert client.get(_charity_workspace_url(edition)).status_code == 404
    create_url = reverse(
        "charity-partner-create-page",
        args=(
            edition.organization.slug,
            edition.series.slug,
            edition.slug,
        ),
    )
    assert client.post(create_url, {}).status_code == 404
    assert not CharityPartner.objects.filter(
        organization_id=edition.organization_id,
    ).exists()


def test_charity_partner_media_and_proposal_html_is_closed_and_tenant_safe() -> (  # noqa: PLR0915
    None
):
    scope = _scope()
    _grant_edition(scope.manager, scope, "charities.view_review_queue")
    _grant_edition(scope.manager, scope, "charities.propose_selection")
    client = Client()
    client.force_login(scope.manager)
    workspace_url = _charity_workspace_url(scope.edition)

    page = client.get(workspace_url)
    assert page.status_code == 200
    assert page.content.count(b'id="nav-sidebar"') == 1
    assert page.content.count(b'id="nav-filter"') == 1
    assert b"Create a reusable charity partner" in page.content

    create_payload = {
        "slug": "browser-animal-aid",
        "legal_name": "Browser Animal Aid Association",
        "imprint_name": "Browser Animal Aid",
        "public_name": "Browser Animal Aid",
        "short_description": "Local animal welfare support.",
        "description": "Restricted diligence notes.",
        "location_name": "Budapest",
        "postal_address": "Restricted postal address",
        "country_code": "HU",
        "website_url": "https://browser-charity.example.invalid",
        "contact_email": "restricted-browser@example.invalid",
        "contact_phone": "+3612345678",
        "reason": "Create the reviewed reusable partner record.",
        "idempotency_key": str(uuid4()),
    }
    create_url = reverse(
        "charity-partner-create-page",
        args=(
            scope.edition.organization.slug,
            scope.edition.series.slug,
            scope.edition.slug,
        ),
    )
    assert (
        client.post(
            create_url,
            {**create_payload, "selected_person_id": str(uuid4())},
        ).status_code
        == 302
    )
    assert not CharityPartner.objects.filter(slug="browser-animal-aid").exists()
    assert client.post(create_url, create_payload).status_code == 302
    partner = CharityPartner.objects.get(slug="browser-animal-aid")

    update_payload = {
        **create_payload,
        "expected_version": str(partner.aggregate_version),
        "lifecycle": CharityPartner.Lifecycle.ACTIVE,
        "reason": "Complete diligence and activate the reusable partner.",
        "idempotency_key": str(uuid4()),
    }
    update_url = reverse(
        "charity-partner-update-page",
        args=(
            scope.edition.organization.slug,
            scope.edition.series.slug,
            scope.edition.slug,
            partner.id,
        ),
    )
    assert client.post(update_url, update_payload).status_code == 302
    assert client.post(update_url, update_payload).status_code == 302
    partner.refresh_from_db()
    assert partner.lifecycle == CharityPartner.Lifecycle.ACTIVE
    assert partner.aggregate_version == 2
    assert (
        client.post(
            update_url,
            {**update_payload, "public_name": "Reused retry key"},
        ).status_code
        == 302
    )
    partner.refresh_from_db()
    assert partner.public_name == "Browser Animal Aid"

    foreign_edition = EventEditionFactory()
    CapabilityGrantFactory(
        organization=foreign_edition.organization,
        principal=scope.manager,
        capability_code="charities.manage_partners",
    )
    foreign_update_url = reverse(
        "charity-partner-update-page",
        args=(
            foreign_edition.organization.slug,
            foreign_edition.series.slug,
            foreign_edition.slug,
            partner.id,
        ),
    )
    assert (
        client.post(
            foreign_update_url,
            {
                **update_payload,
                "expected_version": "2",
                "idempotency_key": str(uuid4()),
            },
        ).status_code
        == 404
    )

    media_add_url = reverse(
        "charity-media-add-page",
        args=(
            scope.edition.organization.slug,
            scope.edition.series.slug,
            scope.edition.slug,
            partner.id,
        ),
    )
    assert (
        client.post(
            media_add_url,
            {
                "kind": CharityPartnerMedia.Kind.LOGO,
                "source_reference": "private://browser/original-logo",
                "owner_name": "Browser Animal Aid",
                "license_basis": "Written organizer-held permission.",
                "usage_scope": "Edition charity profile.",
                "attribution": "Browser Animal Aid",
                "expires_at": "",
                "reason": "Register the supplied governed logo.",
                "idempotency_key": str(uuid4()),
            },
        ).status_code
        == 302
    )
    media = CharityPartnerMedia.objects.get(partner=partner)
    approve_url = reverse(
        "charity-media-approve-page",
        args=(
            scope.edition.organization.slug,
            scope.edition.series.slug,
            scope.edition.slug,
            partner.id,
            media.id,
        ),
    )
    review_payload = {
        "expected_version": "1",
        "public_reference": "https://media.example.invalid/browser-logo.webp",
        "reason": "Review the retained ownership and usage evidence.",
        "idempotency_key": str(uuid4()),
    }
    assert client.post(approve_url, review_payload).status_code == 302
    media.refresh_from_db()
    assert media.review_status == CharityPartnerMedia.ReviewStatus.PENDING
    reviewer_client = Client()
    reviewer_client.force_login(scope.media_reviewer)
    assert reviewer_client.post(approve_url, review_payload).status_code == 302
    media.refresh_from_db()
    assert media.review_status == CharityPartnerMedia.ReviewStatus.APPROVED

    other_edition = EventEditionFactory(
        organization=scope.edition.organization,
        series=scope.edition.series,
    )
    other_department = create_department_for_test(
        edition=other_edition,
        name="Foreign Charity Relations",
        expected_code="foreign-charity-relations",
    )
    propose_url = reverse(
        "charity-selection-propose-page",
        args=(
            scope.edition.organization.slug,
            scope.edition.series.slug,
            scope.edition.slug,
        ),
    )
    proposal_payload = {
        "partner_id": str(partner.id),
        "responsible_department_id": str(other_department.id),
        "reason": "Propose with one exact active Department.",
        "idempotency_key": str(uuid4()),
    }
    assert client.post(propose_url, proposal_payload).status_code == 302
    assert not CharitySelection.objects.filter(partner=partner).exists()
    proposal_payload["responsible_department_id"] = str(scope.department.id)
    assert client.post(propose_url, proposal_payload).status_code == 302
    selection = CharitySelection.objects.get(partner=partner)
    assert selection.responsible_department_id == scope.department.id


def test_charity_selection_html_enforces_dual_control_and_private_projection() -> (  # noqa: PLR0915
    None
):
    scope = _scope()
    partner = _active_partner(scope)
    media_added = add_charity_partner_media(
        actor=scope.manager,
        organization_id=scope.edition.organization_id,
        partner_id=partner.id,
        kind=CharityPartnerMedia.Kind.LOGO,
        source_reference="private://html/source-logo",
        owner_name="Animal Aid",
        license_basis="Written permission retained by the organizer.",
        usage_scope="Edition charity profile.",
        attribution="Animal Aid",
        expires_at=None,
        reason="Register the media source.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    approved_media = approve_charity_partner_media(
        actor=scope.media_reviewer,
        organization_id=scope.edition.organization_id,
        partner_id=partner.id,
        media_id=media_added.object_id,
        expected_version=media_added.resulting_version,
        public_reference="https://media.example.invalid/html-logo.webp",
        reason="Approve the verified public rendition.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    selection = _proposed_selection(scope, partner)
    for actor, capabilities in (
        (scope.reviewer, ("charities.view_selection", "charities.review_selection")),
        (scope.publisher, ("charities.view_selection", "charities.publish_selection")),
        (
            scope.private_reader,
            ("charities.view_selection", "charities.comment_selection"),
        ),
    ):
        for capability in capabilities:
            _grant_selection(actor, scope, selection, capability)

    route_args = (
        scope.edition.organization.slug,
        scope.edition.series.slug,
        scope.edition.slug,
        selection.id,
    )
    proposer_client = Client()
    proposer_client.force_login(scope.proposer)
    submit_url = reverse("charity-selection-submit-page", args=route_args)
    submit_payload = {
        "expected_version": "1",
        "reason": "Submit the complete proposal for independent review.",
        "idempotency_key": str(uuid4()),
    }
    assert proposer_client.post(submit_url, submit_payload).status_code == 302
    assert proposer_client.post(submit_url, submit_payload).status_code == 302
    selection.refresh_from_db()
    assert selection.status == CharitySelection.Status.SUBMITTED
    assert selection.aggregate_version == 2

    reviewer_client = Client()
    reviewer_client.force_login(scope.reviewer)
    review_url = reverse("charity-selection-review-page", args=route_args)
    review_page = reviewer_client.get(review_url)
    assert review_page.status_code == 200
    assert review_page.content.count(b'id="nav-sidebar"') == 1
    assert b"Independently confirm" in review_page.content
    confirm_url = reverse("charity-selection-confirm-page", args=route_args)
    assert (
        reviewer_client.post(
            confirm_url,
            {
                "expected_version": "2",
                "reason": "Confirm the reviewed beneficiary for this edition.",
                "idempotency_key": str(uuid4()),
            },
        ).status_code
        == 302
    )
    selection.refresh_from_db()
    assert selection.status == CharitySelection.Status.CONFIRMED

    _grant_selection(
        scope.reviewer,
        scope,
        selection,
        "charities.publish_selection",
    )
    publish_url = reverse("charity-selection-publish-page", args=route_args)
    assert (
        reviewer_client.post(
            publish_url,
            {
                "expected_version": "3",
                "media_ids": [str(approved_media.object_id)],
                "reason": "A confirmer must not publish their own decision.",
                "idempotency_key": str(uuid4()),
            },
        ).status_code
        == 302
    )
    selection.refresh_from_db()
    assert selection.publication_state == CharitySelection.PublicationState.UNPUBLISHED

    private_client = Client()
    private_client.force_login(scope.private_reader)
    comment_url = reverse("charity-selection-comment-page", args=route_args)
    private_comment = "Private settlement coordination; never publish this phrase."
    assert (
        private_client.post(
            comment_url,
            {
                "expected_version": "3",
                "private_comment": private_comment,
                "idempotency_key": str(uuid4()),
            },
        ).status_code
        == 302
    )
    selection.refresh_from_db()
    assert selection.aggregate_version == 4

    publisher_client = Client()
    publisher_client.force_login(scope.publisher)
    publication_reason = "Approve only the minimized public charity card."
    assert (
        publisher_client.post(
            publish_url,
            {
                "expected_version": "4",
                "media_ids": [str(approved_media.object_id)],
                "reason": publication_reason,
                "idempotency_key": str(uuid4()),
            },
        ).status_code
        == 302
    )
    selection.refresh_from_db()
    assert selection.publication_state == CharitySelection.PublicationState.PUBLISHED
    public_payload = repr(
        tuple(
            asdict(item)
            for item in public_charities_for_edition(
                organization_id=scope.edition.organization_id,
                edition_id=scope.edition.id,
            )
        )
    )
    assert "Animal Aid" in public_payload
    assert private_comment not in public_payload
    assert publication_reason not in public_payload
    assert "private-contact" not in public_payload

    private_review = private_client.get(review_url)
    assert private_review.status_code == 200
    assert private_comment.encode() in private_review.content
    assert str(scope.private_reader.id).encode() not in private_review.content

    withdraw_url = reverse("charity-selection-withdraw-page", args=route_args)
    assert (
        publisher_client.post(
            withdraw_url,
            {
                "expected_version": "5",
                "reason": "Withdraw the public snapshot after the campaign closes.",
                "idempotency_key": str(uuid4()),
            },
        ).status_code
        == 302
    )
    assert (
        public_charities_for_edition(
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
        )
        == ()
    )

    second_created = create_charity_partner(
        actor=scope.manager,
        organization_id=scope.edition.organization_id,
        slug="second-browser-partner",
        profile=CharityPartnerProfile(
            legal_name="Second Browser Partner Association",
            public_name="Second Browser Partner",
        ),
        reason="Create a second candidate for the rejection adapter.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    second = CharityPartner.objects.get(id=second_created.object_id)
    update_charity_partner(
        actor=scope.manager,
        organization_id=scope.edition.organization_id,
        partner_id=second.id,
        expected_version=second.aggregate_version,
        changes={"lifecycle": CharityPartner.Lifecycle.ACTIVE},
        reason="Activate the second reviewed candidate.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    rejected_selection = _proposed_selection(scope, second)
    _grant_selection(
        scope.reviewer,
        scope,
        rejected_selection,
        "charities.view_selection",
    )
    _grant_selection(
        scope.reviewer,
        scope,
        rejected_selection,
        "charities.review_selection",
    )
    rejected_args = (*route_args[:3], rejected_selection.id)
    assert (
        proposer_client.post(
            reverse("charity-selection-submit-page", args=rejected_args),
            {
                "expected_version": "1",
                "reason": "Submit the second candidate.",
                "idempotency_key": str(uuid4()),
            },
        ).status_code
        == 302
    )
    rejection_reason = "Restricted evidence arrived after the annual deadline."
    assert (
        reviewer_client.post(
            reverse("charity-selection-reject-page", args=rejected_args),
            {
                "expected_version": "2",
                "reason": rejection_reason,
                "idempotency_key": str(uuid4()),
            },
        ).status_code
        == 302
    )
    rejected_page = reviewer_client.get(
        reverse("charity-selection-review-page", args=rejected_args)
    )
    assert rejection_reason.encode() in rejected_page.content
    assert "Second Browser Partner" not in repr(
        public_charities_for_edition(
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
        )
    )

    outsider = AccountFactory()
    outsider_client = Client()
    outsider_client.force_login(outsider)
    assert (
        outsider_client.post(
            confirm_url,
            {
                "unknown": "must not be parsed before authorization",
                "expected_version": "3",
                "reason": "Unauthorized probe.",
                "idempotency_key": str(uuid4()),
            },
        ).status_code
        == 403
    )
