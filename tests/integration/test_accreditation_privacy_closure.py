import hashlib
import hmac
from datetime import date, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from maru.accreditation.models import (
    Credential,
    CredentialEvent,
    OfflineCheckInOperation,
    RelayDevice,
)
from maru.accreditation.services import (
    generate_offline_manifest,
    issue_credential,
    reconcile_offline_check_in,
    revoke_credential,
)
from maru.events.closure import (
    assert_archive_ready,
    closure_counts,
    generate_closure_manifest,
    review_readiness_gate,
)
from maru.events.models import EditionReadinessGate, EventEdition
from maru.privacyops.models import (
    DisposalReceipt,
    PostEditionCorrection,
    RetentionPolicy,
    SubjectRightsRequest,
)
from maru.privacyops.services import (
    build_subject_export,
    decide_profile_correction,
    minimize_registration_profile,
    propose_profile_correction,
)
from maru.registration.models import (
    AdmissionProduct,
    ConfigurationStatus,
    RegistrationQuestion,
)
from maru.registration.services import AttendeeProfileInput, submit_public_registration
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RegistrationConfigurationFactory,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _profile() -> AttendeeProfileInput:
    return AttendeeProfileInput(
        real_name="Historical Person",
        date_of_birth=date(1990, 1, 1),
        address_line_1="1 Historical Street",
        address_line_2="",
        locality="Old City",
        postal_code="1000",
        region="Region",
        country_code="HU",
        emergency_contact_name="Emergency Person",
        emergency_contact_phone="+361234567",
        phone_number="+361234568",
        telegram_handle="history_user",
        pronoun_code="they_them",
        other_pronouns="",
        bio="Before minimization.",
        spoken_language_codes=("en",),
        profile_photo=None,
        reuse_profile_photo_id=None,
        keep_profile_photo=False,
        brings_fursuits=False,
        fursuits=(),
        directory_visible=False,
    )


def _confirmed_world():
    now = timezone.now()
    edition = EventEditionFactory()
    configuration = RegistrationConfigurationFactory(
        edition=edition,
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=30),
    )
    RegistrationQuestion.objects.create(
        configuration=configuration,
        key="badge-name",
        label="Badge name",
        field_type="short_text",
        required=True,
        position=10,
        purpose="Print a credential.",
    )
    product = AdmissionProduct.objects.create(
        configuration=configuration,
        code="free",
        name="Free admission",
        price_minor=0,
        capacity=20,
        position=10,
        entitlement_code="admission",
        entitlement_name="Admission",
    )
    configuration.status = ConfigurationStatus.ACTIVE
    configuration.review_required = False
    configuration.review_note = "Reviewed."
    configuration.activated_at = now
    configuration.save(
        update_fields=(
            "status",
            "review_required",
            "review_note",
            "activated_at",
            "updated_at",
        )
    )
    attendee = AccountFactory()
    result = submit_public_registration(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        product_id=product.id,
        answers={"badge-name": "Historical"},
        profile_input=_profile(),
        correlation_id=uuid4(),
        account=attendee,
    )
    return edition, attendee, result.registration, result.profile, now


def _grant_accreditation(operator, edition) -> None:
    for code in (
        "accreditation.issue",
        "accreditation.revoke",
        "accreditation.manage_offline",
    ):
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            principal=operator,
            capability_code=code,
        )


def _offline_signature(
    *,
    secret: str,
    operation_id,
    device_sequence: int,
    manifest_sequence: int,
    token: str,
    occurred_at,
) -> str:
    canonical = (
        f"{operation_id}|{device_sequence}|{manifest_sequence}|"
        f"{token}|{occurred_at.isoformat()}"
    )
    return hmac.new(
        secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()


def test_credentials_reprint_revoke_and_signed_offline_reconciliation(
    monkeypatch,
) -> None:
    edition, _attendee, registration, _profile_item, _now = _confirmed_world()
    operator = AccountFactory()
    _grant_accreditation(operator, edition)
    first = issue_credential(
        actor=operator,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        registration_id=registration.id,
        reason="Print attendee credential.",
        correlation_id=uuid4(),
    )
    assert first.raw_token
    manifest = generate_offline_manifest(
        actor=operator,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        correlation_id=uuid4(),
    )
    device = RelayDevice.objects.create(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        code="front-desk-1",
        label="Front Desk 1",
        signing_secret_env_var="OFFLINE_DEVICE_TEST_SECRET",
    )
    monkeypatch.setenv("OFFLINE_DEVICE_TEST_SECRET", "device-secret")
    occurred_at = timezone.now()
    operation_id = uuid4()
    applied = reconcile_offline_check_in(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        device_code=device.code,
        operation_id=operation_id,
        device_sequence=1,
        manifest_sequence=manifest.sequence,
        raw_credential_token=first.raw_token or "",
        occurred_at=occurred_at,
        signature=_offline_signature(
            secret="device-secret",
            operation_id=operation_id,
            device_sequence=1,
            manifest_sequence=manifest.sequence,
            token=first.raw_token or "",
            occurred_at=occurred_at,
        ),
    )
    assert applied.outcome == OfflineCheckInOperation.Outcome.APPLIED
    assert (
        reconcile_offline_check_in(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            device_code=device.code,
            operation_id=operation_id,
            device_sequence=1,
            manifest_sequence=manifest.sequence,
            raw_credential_token=first.raw_token or "",
            occurred_at=occurred_at,
            signature="ignored-on-idempotent-replay",
        ).id
        == applied.id
    )

    duplicate_id = uuid4()
    duplicate = reconcile_offline_check_in(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        device_code=device.code,
        operation_id=duplicate_id,
        device_sequence=2,
        manifest_sequence=manifest.sequence,
        raw_credential_token=first.raw_token or "",
        occurred_at=occurred_at,
        signature=_offline_signature(
            secret="device-secret",
            operation_id=duplicate_id,
            device_sequence=2,
            manifest_sequence=manifest.sequence,
            token=first.raw_token or "",
            occurred_at=occurred_at,
        ),
    )
    assert duplicate.outcome == OfflineCheckInOperation.Outcome.DUPLICATE

    second = issue_credential(
        actor=operator,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        registration_id=registration.id,
        reason="Damaged credential reprint.",
        correlation_id=uuid4(),
    )
    first.credential.refresh_from_db()
    assert first.credential.status == Credential.Status.REPLACED
    assert second.credential.issue_sequence == 2
    revoked = revoke_credential(
        actor=operator,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        credential_id=second.credential.id,
        reason="Credential reported lost.",
        correlation_id=uuid4(),
    )
    assert revoked.status == Credential.Status.REVOKED
    assert CredentialEvent.objects.filter(
        credential=revoked,
        kind=CredentialEvent.Kind.REVOKED,
    ).exists()
    event = CredentialEvent.objects.filter(credential=revoked).first()
    assert event is not None
    with pytest.raises(IntegrityError), transaction.atomic():
        CredentialEvent.objects.filter(id=event.id).update(reason_code="rewritten")

    with pytest.raises(ValidationError, match="signature"):
        reconcile_offline_check_in(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            device_code=device.code,
            operation_id=uuid4(),
            device_sequence=3,
            manifest_sequence=manifest.sequence,
            raw_credential_token="unknown",
            occurred_at=occurred_at,
            signature="invalid",
        )


def test_accreditation_api_issues_lists_uses_offline_and_revokes(
    monkeypatch,
) -> None:
    edition, attendee, registration, _profile_item, _now = _confirmed_world()
    operator = AccountFactory()
    _grant_accreditation(operator, edition)
    staff = APIClient()
    staff.force_authenticate(operator)
    base = f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}"

    issued = staff.post(
        f"{base}/registrations/{registration.id}/credentials",
        {"reason": "Issue the attendee credential."},
        format="json",
    )
    assert issued.status_code == 201
    credential_id = issued.data["credential"]["id"]
    raw_token = issued.data["credential_token"]

    attendee_client = APIClient()
    attendee_client.force_authenticate(attendee)
    mine = attendee_client.get(f"{base}/accreditation/me/credentials")
    assert mine.status_code == 200
    assert mine.data[0]["id"] == credential_id

    manifest_response = staff.post(f"{base}/offline/manifests")
    assert manifest_response.status_code == 201
    manifest_sequence = manifest_response.data["sequence"]
    RelayDevice.objects.create(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        code="api-front-desk",
        label="API Front Desk",
        signing_secret_env_var="OFFLINE_API_DEVICE_SECRET",
    )
    monkeypatch.setenv("OFFLINE_API_DEVICE_SECRET", "api-device-secret")
    operation_id = uuid4()
    occurred_at = timezone.now()
    signature = _offline_signature(
        secret="api-device-secret",
        operation_id=operation_id,
        device_sequence=1,
        manifest_sequence=manifest_sequence,
        token=raw_token,
        occurred_at=occurred_at,
    )
    ingested = APIClient().post(
        (
            f"/api/v1/public/organizations/{edition.organization_id}/editions/"
            f"{edition.id}/offline/devices/api-front-desk/check-ins"
        ),
        {
            "operation_id": operation_id,
            "device_sequence": 1,
            "manifest_sequence": manifest_sequence,
            "credential_token": raw_token,
            "occurred_at": occurred_at.isoformat(),
            "signature": signature,
        },
        format="json",
    )
    assert ingested.status_code == 200
    assert ingested.data["outcome"] == OfflineCheckInOperation.Outcome.APPLIED

    conflicts = staff.get(f"{base}/offline/conflicts")
    assert conflicts.status_code == 200
    assert conflicts.data == []
    revoked = staff.post(
        f"{base}/credentials/{credential_id}/revoke",
        {"reason": "Credential was returned after check-in rehearsal."},
        format="json",
    )
    assert revoked.status_code == 200
    assert revoked.data["status"] == Credential.Status.REVOKED


def test_accreditation_api_denies_unscoped_and_invalid_operations() -> None:
    edition, _attendee, registration, _profile_item, _now = _confirmed_world()
    unprivileged = AccountFactory()
    client = APIClient()
    client.force_authenticate(unprivileged)
    base = f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}"
    denied_issue = client.post(
        f"{base}/registrations/{registration.id}/credentials",
        {"reason": "This actor has no accreditation authority."},
        format="json",
    )
    assert denied_issue.status_code == 403
    denied_manifest = client.post(f"{base}/offline/manifests")
    assert denied_manifest.status_code == 403
    denied_conflicts = client.get(f"{base}/offline/conflicts")
    assert denied_conflicts.status_code == 403

    missing_device = APIClient().post(
        (
            f"/api/v1/public/organizations/{edition.organization_id}/editions/"
            f"{edition.id}/offline/devices/missing/check-ins"
        ),
        {
            "operation_id": uuid4(),
            "device_sequence": 1,
            "manifest_sequence": 1,
            "credential_token": "synthetic-token",
            "occurred_at": timezone.now().isoformat(),
            "signature": "invalid",
        },
        format="json",
    )
    assert missing_device.status_code == 404


def test_post_edition_correction_export_and_retention_minimization() -> None:
    edition, attendee, _registration, profile, now = _confirmed_world()
    privacy_operator = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=privacy_operator,
        capability_code="privacy.manage_requests",
    )
    EventEdition.objects.filter(id=edition.id).update(
        starts_on=date(2020, 1, 1),
        ends_on=date(2020, 1, 3),
    )
    correction = propose_profile_correction(
        account=attendee,
        profile_id=profile.id,
        changed_fields={"locality": "Corrected City"},
        reason="The archived address contains a transcription error.",
    )
    correction = decide_profile_correction(
        actor=privacy_operator,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        correction_id=correction.id,
        approve=True,
        reason="Verified against attendee correspondence.",
    )
    assert correction.status == PostEditionCorrection.Status.APPROVED

    policy = RetentionPolicy.objects.create(
        organization_id=edition.organization_id,
        jurisdiction_code="synthetic",
        data_category="registration_profile",
        version=1,
        retention_days=30,
        disposition=RetentionPolicy.Disposition.MINIMIZE,
        lawful_basis="Synthetic approved retention schedule.",
        approved_by_id=privacy_operator.id,
        approved_at=now,
        active=True,
    )
    receipt = minimize_registration_profile(
        actor=privacy_operator,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        profile_id=profile.id,
        policy_id=policy.id,
        correlation_id=uuid4(),
        today=date(2021, 1, 1),
    )
    assert receipt.disposition == RetentionPolicy.Disposition.MINIMIZE
    profile.refresh_from_db()
    assert profile.real_name == "[minimized]"
    assert profile.directory_visible is False
    assert DisposalReceipt.objects.count() == 1
    with pytest.raises(IntegrityError), transaction.atomic():
        DisposalReceipt.objects.filter(id=receipt.id).update(
            safe_result_code="rewritten"
        )
    assert (
        minimize_registration_profile(
            actor=privacy_operator,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            profile_id=profile.id,
            policy_id=policy.id,
            correlation_id=uuid4(),
            today=date(2021, 1, 1),
        ).id
        == receipt.id
    )

    exported = build_subject_export(
        account=attendee,
        organization_id=edition.organization_id,
    )
    assert exported["registrations"]
    assert exported["historical_corrections"]
    client = APIClient()
    client.force_authenticate(attendee)
    response = client.get(
        f"/api/v1/me/privacy-export?organization_id={edition.organization_id}"
    )
    assert response.status_code == 200
    assert response.data["platform_identity"]["email"] == attendee.email


def test_privacy_correction_and_minimization_api_workflow() -> None:
    edition, attendee, _registration, profile, now = _confirmed_world()
    EventEdition.objects.filter(id=edition.id).update(
        starts_on=date(2020, 1, 1),
        ends_on=date(2020, 1, 3),
    )
    operator = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=operator,
        capability_code="privacy.manage_requests",
    )
    attendee_client = APIClient()
    attendee_client.force_authenticate(attendee)
    proposed = attendee_client.post(
        "/api/v1/me/post-edition-corrections",
        {
            "profile_id": profile.id,
            "changed_fields": {"bio": "Corrected retained biography."},
            "reason": "The historical profile needs an accuracy correction.",
        },
        format="json",
    )
    assert proposed.status_code == 201
    correction_id = proposed.data["id"]
    listed = attendee_client.get("/api/v1/me/post-edition-corrections")
    assert listed.status_code == 200
    assert listed.data[0]["id"] == correction_id
    invalid_export = attendee_client.get(
        "/api/v1/me/privacy-export?organization_id=invalid"
    )
    assert invalid_export.status_code == 400

    staff = APIClient()
    staff.force_authenticate(operator)
    decided = staff.post(
        (
            f"/api/v1/organizations/{edition.organization_id}/editions/"
            f"{edition.id}/privacy/corrections/{correction_id}/decision"
        ),
        {
            "approve": True,
            "reason": "The attendee correspondence verifies the correction.",
        },
        format="json",
    )
    assert decided.status_code == 200
    assert decided.data["status"] == PostEditionCorrection.Status.APPROVED

    policy = RetentionPolicy.objects.create(
        organization_id=edition.organization_id,
        jurisdiction_code="synthetic",
        data_category="registration_profile",
        version=2,
        retention_days=30,
        disposition=RetentionPolicy.Disposition.MINIMIZE,
        lawful_basis="Synthetic approved retention schedule.",
        approved_by_id=operator.id,
        approved_at=now,
        active=True,
    )
    minimized = staff.post(
        (
            f"/api/v1/organizations/{edition.organization_id}/editions/"
            f"{edition.id}/privacy/registration-profile-minimization"
        ),
        {
            "profile_id": profile.id,
            "policy_id": policy.id,
        },
        format="json",
    )
    assert minimized.status_code == 201
    assert minimized.data["safe_result_code"] == "registration_profile_minimized"


def test_privacy_api_denies_cross_scope_and_hides_missing_targets() -> None:
    edition, attendee, _registration, profile, _now = _confirmed_world()
    EventEdition.objects.filter(id=edition.id).update(
        starts_on=date(2020, 1, 1),
        ends_on=date(2020, 1, 3),
    )
    unprivileged = AccountFactory()
    staff = APIClient()
    staff.force_authenticate(unprivileged)
    assert (
        staff.get(
            f"/api/v1/organizations/{edition.organization_id}/privacy-requests"
        ).status_code
        == 403
    )
    assert (
        staff.post(
            (
                f"/api/v1/organizations/{edition.organization_id}/privacy-requests/"
                f"{uuid4()}/transition"
            ),
            {"action": "begin_identity_check"},
            format="json",
        ).status_code
        == 403
    )

    attendee_client = APIClient()
    attendee_client.force_authenticate(attendee)
    missing_profile = attendee_client.post(
        "/api/v1/me/post-edition-corrections",
        {
            "profile_id": uuid4(),
            "changed_fields": {"bio": "Unavailable target."},
            "reason": "Synthetic missing target.",
        },
        format="json",
    )
    assert missing_profile.status_code == 404
    proposed = propose_profile_correction(
        account=attendee,
        profile_id=profile.id,
        changed_fields={"bio": "A valid correction awaiting review."},
        reason="Synthetic correction.",
    )
    denied_decision = staff.post(
        (
            f"/api/v1/organizations/{edition.organization_id}/editions/"
            f"{edition.id}/privacy/corrections/{proposed.id}/decision"
        ),
        {"approve": False, "reason": "No authority."},
        format="json",
    )
    assert denied_decision.status_code == 403
    denied_minimization = staff.post(
        (
            f"/api/v1/organizations/{edition.organization_id}/editions/"
            f"{edition.id}/privacy/registration-profile-minimization"
        ),
        {"profile_id": profile.id, "policy_id": uuid4()},
        format="json",
    )
    assert denied_minimization.status_code == 403


def test_closure_gates_block_then_generate_immutable_manifest() -> None:
    edition = EventEditionFactory()
    for version, lifecycle in enumerate(
        (
            EventEdition.Lifecycle.PREPARING,
            EventEdition.Lifecycle.READY,
            EventEdition.Lifecycle.LIVE,
            EventEdition.Lifecycle.CLOSING,
        ),
        start=1,
    ):
        EventEdition.objects.filter(id=edition.id).update(
            lifecycle=lifecycle,
            lifecycle_version=version,
        )
    edition.refresh_from_db()
    operator = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=operator,
        capability_code="events.transition",
    )
    assert all(
        value == 0
        for value in closure_counts(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ).values()
    )
    with pytest.raises(ValidationError, match="approved gates"):
        generate_closure_manifest(
            edition=edition,
            actor=operator,
            recovery_reference="RESTORE-TEST-1",
        )
    for code in EditionReadinessGate.Code.values:
        gate = review_readiness_gate(
            actor=operator,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            code=code,
            approve=True,
            evidence_reference=f"EVIDENCE-{code}",
            summary=f"Synthetic {code} reviewer approved readiness.",
            correlation_id=uuid4(),
        )
        assert gate.status == EditionReadinessGate.Status.APPROVED
    attendee = AccountFactory()
    correction = PostEditionCorrection.objects.create(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        account_id=attendee.id,
        target_type="registration.attendee_profile",
        target_id=uuid4(),
        changed_fields={"bio": "Corrected historical bio."},
        reason="The retained public description is inaccurate.",
        requested_by_id=attendee.id,
        requested_at=timezone.now(),
    )
    counts = closure_counts(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    assert counts["historical_corrections_open"] == 1
    with pytest.raises(ValidationError, match="historical_corrections_open"):
        generate_closure_manifest(
            edition=edition,
            actor=operator,
            recovery_reference="RESTORE-TEST-1",
        )
    PostEditionCorrection.objects.filter(id=correction.id).update(
        status=PostEditionCorrection.Status.REJECTED,
        decided_by_id=operator.id,
        decided_at=timezone.now(),
        decision_reason="The source record was verified as accurate.",
        updated_at=timezone.now(),
    )
    manifest = generate_closure_manifest(
        edition=edition,
        actor=operator,
        recovery_reference="RESTORE-TEST-1",
    )
    assert manifest.manifest_digest
    assert_archive_ready(edition)
    with pytest.raises(ValidationError, match="already exists"):
        generate_closure_manifest(
            edition=edition,
            actor=operator,
            recovery_reference="RESTORE-TEST-2",
        )


def test_closure_readiness_and_manifest_api_workflow() -> None:
    edition = EventEditionFactory()
    for version, lifecycle in enumerate(
        (
            EventEdition.Lifecycle.PREPARING,
            EventEdition.Lifecycle.READY,
            EventEdition.Lifecycle.LIVE,
            EventEdition.Lifecycle.CLOSING,
        ),
        start=1,
    ):
        EventEdition.objects.filter(id=edition.id).update(
            lifecycle=lifecycle,
            lifecycle_version=version,
        )
    operator = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=operator,
        capability_code="events.transition",
    )
    client = APIClient()
    client.force_authenticate(operator)
    base = f"/api/v1/organizations/{edition.organization_id}/editions/{edition.id}"
    readiness = client.get(f"{base}/closure-readiness")
    assert readiness.status_code == 200
    assert readiness.data["manifest"] is None
    assert readiness.data["gates"] == []

    invalid = client.post(
        f"{base}/closure-gates/unknown",
        {
            "approve": True,
            "evidence_reference": "UNKNOWN",
            "summary": "This gate does not exist.",
        },
        format="json",
    )
    assert invalid.status_code == 400
    for code in EditionReadinessGate.Code.values:
        reviewed = client.post(
            f"{base}/closure-gates/{code}",
            {
                "approve": True,
                "evidence_reference": f"EVIDENCE-{code}",
                "summary": f"Synthetic {code} approval evidence.",
            },
            format="json",
        )
        assert reviewed.status_code == 200
        assert reviewed.data["status"] == EditionReadinessGate.Status.APPROVED

    generated = client.post(
        f"{base}/closure-manifest",
        {"recovery_reference": "RESTORE-API-1"},
        format="json",
    )
    assert generated.status_code == 201
    assert generated.data["manifest_digest"]
    final_readiness = client.get(f"{base}/closure-readiness")
    assert final_readiness.status_code == 200
    assert final_readiness.data["manifest"]["id"] == generated.data["id"]


def test_subject_rights_request_has_scoped_operator_state_machine() -> None:
    edition = EventEditionFactory()
    attendee = AccountFactory()
    operator = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        principal=operator,
        capability_code="privacy.manage_requests",
    )
    attendee_client = APIClient()
    attendee_client.force_authenticate(attendee)
    created = attendee_client.post(
        "/api/v1/me/privacy-requests",
        {
            "organization_id": edition.organization_id,
            "kind": "access",
            "summary": "Please provide my organizer-scoped information.",
        },
        format="json",
    )
    assert created.status_code == 201
    request_id = created.data["id"]
    attendee_queue = attendee_client.get("/api/v1/me/privacy-requests")
    assert attendee_queue.status_code == 200
    assert attendee_queue.data[0]["id"] == request_id

    operator_client = APIClient()
    operator_client.force_authenticate(operator)
    queue = operator_client.get(
        f"/api/v1/organizations/{edition.organization_id}/privacy-requests"
    )
    assert queue.status_code == 200
    assert queue.data[0]["account_email"] == attendee.email
    transition_url = (
        f"/api/v1/organizations/{edition.organization_id}/privacy-requests/"
        f"{request_id}/transition"
    )
    identity_check = operator_client.post(
        transition_url,
        {"action": "begin_identity_check"},
        format="json",
    )
    assert identity_check.status_code == 200
    verified = operator_client.post(
        transition_url,
        {"action": "verify_identity"},
        format="json",
    )
    assert verified.status_code == 200
    assert verified.data["identity_verified_at"]
    completed = operator_client.post(
        transition_url,
        {
            "action": "complete",
            "outcome_summary": "The scoped export was provided securely.",
        },
        format="json",
    )
    assert completed.status_code == 200
    assert completed.data["status"] == SubjectRightsRequest.Status.COMPLETED
    repeated = operator_client.post(
        transition_url,
        {"action": "complete", "outcome_summary": "Repeated."},
        format="json",
    )
    assert repeated.status_code == 400
