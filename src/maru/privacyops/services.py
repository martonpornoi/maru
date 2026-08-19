"""Subject-rights intake and reasoned post-edition correction overlays."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    decide,
    resolve_edition_target,
    resolve_organization_target,
)
from maru.authorization.services import AuthorizationDenied
from maru.events.models import EventEdition
from maru.identity.models import Account, AccountSecurityEvent
from maru.privacyops.models import (
    DisposalReceipt,
    PostEditionCorrection,
    RetentionPolicy,
    SubjectRightsRequest,
)
from maru.registration.media import dispose_storage_if_unreferenced
from maru.registration.models import (
    AttendeeFursuit,
    AttendeeRegistrationProfile,
    MediaReviewStatus,
)

if TYPE_CHECKING:
    from uuid import UUID

CORRECTABLE_PROFILE_FIELDS = frozenset(
    {
        "real_name",
        "address_line_1",
        "address_line_2",
        "locality",
        "postal_code",
        "region",
        "country_code",
        "phone_number",
        "emergency_contact_name",
        "emergency_contact_phone",
        "pronoun_code",
        "other_pronouns",
        "bio",
        "spoken_language_codes",
    }
)


def build_subject_export(
    *,
    account: Account,
    organization_id: UUID | None,
) -> dict[str, object]:
    """Return a purpose-grouped self projection without provider secrets.

    Parameters
    ----------
    account : Account
        The platform account whose state or access is being evaluated.
    organization_id : UUID | None
        The organization identifier that owns the requested resource.

    Returns
    -------
    dict[str, object]
        A mapping containing the resolved build subject export data.
    """
    from maru.accreditation.models import Credential  # noqa: PLC0415
    from maru.communications.models import NotificationMessage  # noqa: PLC0415
    from maru.registration.models import Registration  # noqa: PLC0415

    registrations = Registration.objects.filter(account=account)
    profiles = AttendeeRegistrationProfile.objects.filter(account=account)
    credentials = Credential.objects.filter(account_id=account.id)
    notifications = NotificationMessage.objects.filter(account=account)
    corrections = PostEditionCorrection.objects.filter(account_id=account.id)
    restrictions = account.restrictions.all()
    if organization_id is not None:
        registrations = registrations.filter(organization_id=organization_id)
        profiles = profiles.filter(organization_id=organization_id)
        credentials = credentials.filter(organization_id=organization_id)
        notifications = notifications.filter(organization_id=organization_id)
        corrections = corrections.filter(organization_id=organization_id)
        restrictions = restrictions.filter(organization_id=organization_id)
    AccountSecurityEvent.objects.create(
        account=account,
        event_type=AccountSecurityEvent.EventType.DATA_EXPORT,
        outcome=AccountSecurityEvent.Outcome.SUCCEEDED,
        occurred_at=timezone.now(),
        source_channel="self_service",
        detail_code="privacy_export_generated",
    )
    return {
        "generated_at": timezone.now().isoformat(),
        "scope": {
            "account_id": str(account.id),
            "organization_id": (
                str(organization_id) if organization_id is not None else None
            ),
        },
        "platform_identity": {
            "email": account.email,
            "display_name": account.display_name,
            "preferred_language": account.preferred_language,
            "email_verified_at": (
                account.email_verified_at.isoformat()
                if account.email_verified_at
                else None
            ),
        },
        "registrations": list(
            registrations.values(
                "id",
                "organization_id",
                "edition_id",
                "reference",
                "state",
                "product_name_snapshot",
                "price_minor_snapshot",
                "currency_snapshot",
                "submitted_at",
                "payment_due_at",
                "confirmed_at",
            )
        ),
        "registration_profiles": list(
            profiles.values(
                "id",
                "organization_id",
                "edition_id",
                "real_name",
                "date_of_birth",
                "address_line_1",
                "address_line_2",
                "locality",
                "postal_code",
                "region",
                "country_code",
                "emergency_contact_name",
                "emergency_contact_phone",
                "phone_number",
                "telegram_handle",
                "pronouns",
                "bio",
                "spoken_language_codes",
                "directory_visible",
                "directory_country_code",
            )
        ),
        "credentials": list(
            credentials.values(
                "id",
                "edition_id",
                "public_id",
                "status",
                "label_snapshot",
                "issued_at",
                "revoked_at",
            )
        ),
        "notifications": list(
            notifications.values(
                "id",
                "edition_id",
                "subject",
                "body",
                "created_at",
                "read_at",
            )
        ),
        "historical_corrections": list(
            corrections.values(
                "id",
                "edition_id",
                "target_type",
                "target_id",
                "status",
                "changed_fields",
                "reason",
                "decision_reason",
            )
        ),
        "restrictions": list(
            restrictions.values(
                "id",
                "organization_id",
                "edition_id",
                "kind",
                "status",
                "attendee_message",
                "effective_at",
                "expires_at",
                "revoked_at",
            )
        ),
    }


def create_subject_rights_request(
    *,
    account: Account,
    organization_id: UUID | None,
    kind: str,
    summary: str,
) -> SubjectRightsRequest:
    """Create subject rights request.

    Parameters
    ----------
    account : Account
        The account applied within the audited domain transition.
    organization_id : UUID | None
        The identifier of the organization that owns the operation.
    kind : str
        The closed kind code.
    summary : str
        The human-readable summary.

    Returns
    -------
    SubjectRightsRequest
        The persisted record after validation and transaction commit.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    normalized = summary.strip()
    if kind not in SubjectRightsRequest.Kind.values:
        raise ValidationError(
            "Choose a supported privacy request.",
            code="privacy_request_kind_invalid",
        )
    if not normalized:
        raise ValidationError(
            "Describe the privacy request.",
            code="privacy_request_summary_required",
        )
    return SubjectRightsRequest.objects.create(
        account=account,
        organization_id=organization_id,
        kind=kind,
        requested_at=timezone.now(),
        request_summary=normalized,
    )


def transition_subject_rights_request(
    *,
    actor: Account,
    organization_id: UUID,
    request_id: UUID,
    action: str,
    outcome_summary: str,
    correlation_id: UUID,
) -> SubjectRightsRequest:
    """Advance one organization-scoped subject-rights case through safe states.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    request_id : UUID
        The correlation identifier attached to the incoming request.
    action : str
        The stable action code describing the requested transition.
    outcome_summary : str
        The outcome summary applied within the audited domain transition.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.

    Returns
    -------
    SubjectRightsRequest
        The resolved SubjectRightsRequest for transition subject rights request.

    Raises
    ------
    AuthorizationDenied
        If the actor lacks the required scoped capability.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    decision = decide(
        principal=actor,
        capability_code="privacy.manage_requests",
        resource=resolve_organization_target(organization_id=organization_id),
    )
    if not decision.allowed:
        raise AuthorizationDenied(
            "Privacy request management is unavailable.",
            reason_code=decision.reason_code,
        )
    transitions: dict[tuple[str, str], str] = {
        (
            SubjectRightsRequest.Status.RECEIVED,
            "begin_identity_check",
        ): SubjectRightsRequest.Status.IDENTITY_CHECK,
        (
            SubjectRightsRequest.Status.IDENTITY_CHECK,
            "verify_identity",
        ): SubjectRightsRequest.Status.IN_PROGRESS,
        (
            SubjectRightsRequest.Status.IN_PROGRESS,
            "complete",
        ): SubjectRightsRequest.Status.COMPLETED,
        (
            SubjectRightsRequest.Status.IN_PROGRESS,
            "deny",
        ): SubjectRightsRequest.Status.DENIED,
    }
    normalized_summary = outcome_summary.strip()
    with transaction.atomic():
        item = (
            SubjectRightsRequest.objects.select_for_update()
            .select_related("account")
            .get(
                id=request_id,
                organization_id=organization_id,
            )
        )
        target = transitions.get((item.status, action))
        if target is None:
            raise ValidationError(
                "The privacy request cannot take that transition.",
                code="privacy_request_transition_invalid",
            )
        completed = target in (
            SubjectRightsRequest.Status.COMPLETED,
            SubjectRightsRequest.Status.DENIED,
        )
        if completed and not normalized_summary:
            raise ValidationError(
                "Completion or denial requires an attendee-facing outcome summary.",
                code="privacy_request_outcome_required",
            )
        changed_fields = ["status"]
        item.status = target
        if action == "verify_identity":
            item.identity_verified_at = timezone.now()
            changed_fields.append("identity_verified_at")
        if completed:
            item.completed_at = timezone.now()
            item.safe_outcome_summary = normalized_summary
            changed_fields.extend(("completed_at", "safe_outcome_summary"))
        item.save(update_fields=(*changed_fields, "updated_at"))
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=actor.id,
                principal_context_id=None,
                organization_id=organization_id,
                event_edition_id=None,
                capability_code="privacy.manage_requests",
                operation="privacy.subject_rights.transition",
                target_type="privacyops.subject_rights_request",
                target_id=item.id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=f"privacy_request_{action}",
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
                obligations=tuple(sorted(decision.obligations)),
                changed_fields=tuple(changed_fields),
                safe_metadata={"policy_version": POLICY_VERSION},
                retention_class="security-extended",
            )
        )
        return item


def propose_profile_correction(
    *,
    account: Account,
    profile_id: UUID,
    changed_fields: object,
    reason: str,
) -> PostEditionCorrection:
    """Propose profile correction.

    Parameters
    ----------
    account : Account
        The account applied within the audited domain transition.
    profile_id : UUID
        The identifier of the profile.
    changed_fields : object
        The canonical field names changed by the operation.
    reason : str
        The operator-supplied reason for the operation.

    Returns
    -------
    PostEditionCorrection
        The newly persisted PostEditionCorrection with its durable command evidence.

    Raises
    ------
    AttendeeRegistrationProfile.DoesNotExist
        If the operation encounters a does not exist condition.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    profile = (
        AttendeeRegistrationProfile.objects.select_related("edition")
        .filter(id=profile_id, account=account)
        .first()
    )
    if profile is None:
        raise AttendeeRegistrationProfile.DoesNotExist
    if (
        profile.edition.lifecycle
        not in (
            EventEdition.Lifecycle.CLOSING,
            EventEdition.Lifecycle.ARCHIVED,
        )
        and profile.edition.ends_on >= timezone.localdate()
    ):
        raise ValidationError(
            "Use the ordinary profile editor while the edition is current.",
            code="post_edition_correction_not_applicable",
        )
    if not isinstance(changed_fields, dict) or not changed_fields:
        raise ValidationError(
            "Choose at least one field to correct.",
            code="correction_fields_required",
        )
    unknown = set(changed_fields) - CORRECTABLE_PROFILE_FIELDS
    if unknown:
        raise ValidationError(
            "A proposed correction contains unsupported fields.",
            code="correction_field_denied",
        )
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValidationError(
            "Explain why the historical correction is needed.",
            code="correction_reason_required",
        )
    return PostEditionCorrection.objects.create(
        organization_id=profile.organization_id,
        edition_id=profile.edition_id,
        account_id=account.id,
        target_type="registration.attendee_profile",
        target_id=profile.id,
        changed_fields=changed_fields,
        reason=normalized_reason,
        requested_by_id=account.id,
        requested_at=timezone.now(),
    )


def decide_profile_correction(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    correction_id: UUID,
    approve: bool,
    reason: str,
) -> PostEditionCorrection:
    """Decide profile correction.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    correction_id : UUID
        The identifier of the correction.
    approve : bool
        The approve applied within the audited domain transition.
    reason : str
        The operator-supplied reason for the operation.

    Returns
    -------
    PostEditionCorrection
        The PostEditionCorrection established after decide profile correction completes.

    Raises
    ------
    AuthorizationDenied
        If the actor lacks the required scoped capability.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    decision = decide(
        principal=actor,
        capability_code="privacy.manage_requests",
        resource=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    if not decision.allowed:
        raise AuthorizationDenied(
            "Historical correction review is unavailable.",
            reason_code=decision.reason_code,
        )
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValidationError(
            "Correction review requires a reason.",
            code="correction_decision_reason_required",
        )
    with transaction.atomic():
        correction = PostEditionCorrection.objects.select_for_update().get(
            id=correction_id,
            organization_id=organization_id,
            edition_id=edition_id,
            status=PostEditionCorrection.Status.PROPOSED,
        )
        correction.status = (
            PostEditionCorrection.Status.APPROVED
            if approve
            else PostEditionCorrection.Status.REJECTED
        )
        correction.decided_by_id = actor.id
        correction.decided_at = timezone.now()
        correction.decision_reason = normalized_reason
        correction.save(
            update_fields=(
                "status",
                "decided_by_id",
                "decided_at",
                "decision_reason",
                "updated_at",
            )
        )
        return correction


def minimize_registration_profile(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    profile_id: UUID,
    policy_id: UUID,
    correlation_id: UUID,
    today: date | None = None,
) -> DisposalReceipt:
    """Apply an approved retention policy without destroying financial history.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    profile_id : UUID
        The profile identifier within the requested scope.
    policy_id : UUID
        The policy identifier within the requested scope.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    today : date | None, default=None
        The today applied within the audited domain transition.

    Returns
    -------
    DisposalReceipt
        The resolved DisposalReceipt for minimize registration profile.

    Raises
    ------
    AuthorizationDenied
        If the actor lacks the required scoped capability.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    decision = decide(
        principal=actor,
        capability_code="privacy.manage_requests",
        resource=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    if not decision.allowed:
        raise AuthorizationDenied(
            "Registration retention is unavailable.",
            reason_code=decision.reason_code,
        )
    existing = DisposalReceipt.objects.filter(
        policy_id=policy_id,
        target_type="registration.attendee_profile",
        target_id=profile_id,
    ).first()
    if existing is not None:
        return existing
    policy = RetentionPolicy.objects.get(
        id=policy_id,
        organization_id=organization_id,
        data_category="registration_profile",
        disposition=RetentionPolicy.Disposition.MINIMIZE,
        active=True,
    )
    storage_names: list[str] = []
    with transaction.atomic():
        profile = (
            AttendeeRegistrationProfile.objects.select_for_update()
            .select_related("edition")
            .get(
                id=profile_id,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        )
        cutoff = (today or timezone.localdate()) - timedelta(days=policy.retention_days)
        if profile.edition.ends_on > cutoff:
            raise ValidationError(
                "This profile has not reached its approved retention deadline.",
                code="retention_deadline_not_reached",
            )
        if profile.profile_photo:
            storage_names.append(profile.profile_photo.name)
        storage_names.extend(
            AttendeeFursuit.objects.filter(profile=profile)
            .exclude(photo="")
            .values_list("photo", flat=True)
        )
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL maru.retention_workflow = 'on'")
        AttendeeFursuit.objects.filter(profile=profile).update(
            name="[minimized]",
            species="",
            is_active=False,
            photo="",
            photo_status=MediaReviewStatus.NONE,
            photo_reviewed_by_id=None,
            photo_reviewed_at=None,
            photo_review_note="",
            photo_reused_from_id=None,
            updated_at=timezone.now(),
        )
        AttendeeRegistrationProfile.objects.filter(id=profile.id).update(
            aggregate_version=profile.aggregate_version + 1,
            real_name="[minimized]",
            date_of_birth=date(1900, 1, 1),
            address_line_1="[minimized]",
            address_line_2="",
            locality="[minimized]",
            postal_code="[minimized]",
            region="[minimized]",
            country_code="ZZ",
            emergency_contact_name="[minimized]",
            emergency_contact_phone="0000000",
            phone_number="0000000",
            telegram_handle="",
            pronoun_code="they_them",
            other_pronouns="",
            pronouns="they/them",
            bio="",
            spoken_language_codes=[],
            brings_fursuits=False,
            profile_photo="",
            profile_photo_status=MediaReviewStatus.NONE,
            profile_photo_reviewed_by_id=None,
            profile_photo_reviewed_at=None,
            profile_photo_review_note="",
            profile_photo_reused_from_id=None,
            directory_visible=False,
            directory_country_code="",
            directory_consent_version="",
            directory_consent_at=None,
            updated_at=timezone.now(),
        )
    downstream = [
        {
            "storage_name": name,
            "deleted": dispose_storage_if_unreferenced(name),
        }
        for name in sorted(set(storage_names))
    ]
    receipt = DisposalReceipt.objects.create(
        organization_id=organization_id,
        edition_id=edition_id,
        policy=policy,
        target_type="registration.attendee_profile",
        target_id=profile_id,
        disposition=RetentionPolicy.Disposition.MINIMIZE,
        applied_at=timezone.now(),
        applied_by_id=actor.id,
        safe_result_code="registration_profile_minimized",
        downstream_receipts=downstream,
    )
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code="privacy.manage_requests",
            operation="privacy.registration_profile.minimize",
            target_type="registration.attendee_profile",
            target_id=profile_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="retention_policy_applied",
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="api",
            obligations=tuple(sorted(decision.obligations)),
            changed_fields=("profile", "profile_media", "disposal_receipt"),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "access_purpose": "approved retention policy",
            },
            retention_class="security-extended",
        )
    )
    return receipt
