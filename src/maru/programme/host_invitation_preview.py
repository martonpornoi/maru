"""Purpose-signed exact-person invitation selection without mutable-email replay."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hmac import compare_digest
from typing import TYPE_CHECKING
from uuid import UUID

from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from maru.identity.queries import resolve_active_verified_person_reference_by_email

from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_MANAGE_HOSTS,
    ProgrammeAuthorizationDeniedError,
    authorize_programme_scope,
)
from .host_inputs import ProgrammeHostInvitationInput
from .inputs import canonical_digest, normalized_reason, require_uuid
from .queries import _authorized_query

if TYPE_CHECKING:
    from .authorization import ProgrammeAuthorizer
    from .workbench_queries import ProgrammeWorkbenchRequest

_SALT = "programme.host-invitation-selection.v1"
MAX_HOST_SELECTION_BYTES = 2048
_MAX_ADDRESS_LENGTH = 254


@dataclass(frozen=True, slots=True)
class HostInvitationIntent:
    """Retain the original deliberate invitation and its exact-address selector.

    Attributes
    ----------
    recipient_email : str
        User-supplied known address used only during fresh person selection.
    expected_version : int
        Original item cursor, never silently refreshed after uncertainty.
    idempotency_key : UUID
        Original actor/edition intent identity.
    role : str
        Explicit host or co-host role.
    title : str
        Deliberate host-visible invitation title.
    briefing : str
        Deliberate host-visible operational text, never private-source copying.
    reason : str
        Separate organizer rationale, not visible to the invited person.
    """

    recipient_email: str
    expected_version: int
    idempotency_key: UUID
    role: str
    title: str
    briefing: str
    reason: str

    def normalized(self, person_id: UUID) -> HostInvitationIntent:
        """Reuse canonical invitation/reason bounds and validate the known address.

        Parameters
        ----------
        person_id : UUID
            Exact selected person, never resolved by this pure normalization.

        Returns
        -------
        HostInvitationIntent
            Canonical copy/version/retry intent with the original selector bound.

        Raises
        ------
        ValidationError
            If the selector is not a bounded syntactically valid email address.
        """
        require_uuid(self.idempotency_key, field="idempotency_key")
        if (
            not isinstance(self.recipient_email, str)
            or len(self.recipient_email) > _MAX_ADDRESS_LENGTH
        ):
            raise ValidationError({"recipient_email": "Use a bounded exact address."})
        email = self.recipient_email.strip()
        validate_email(email)
        invitation = self.invitation(person_id)
        return replace(
            self,
            recipient_email=email,
            role=invitation.role,
            title=invitation.title,
            briefing=invitation.briefing,
            expected_version=invitation.expected_item_version,
            reason=normalized_reason(self.reason),
        )

    def invitation(self, person_id: UUID) -> ProgrammeHostInvitationInput:
        """Build the unchanged first-invitation command without a person lookup.

        Parameters
        ----------
        person_id : UUID
            Exact selected or verified-proof person reference.

        Returns
        -------
        ProgrammeHostInvitationInput
            Canonical host version zero and original item/copy intent.
        """
        return ProgrammeHostInvitationInput(
            person_id, self.role, self.title, self.briefing, self.expected_version, 0
        ).normalized()


@dataclass(frozen=True, slots=True)
class HostInvitationPreview:
    """Expose selected identity and canonical intent separately from authority.

    Attributes
    ----------
    person_id : UUID
        Exact person resolved under current invitation-preparation authority.
    intent : HostInvitationIntent
        Normalized original selector, copy, rationale, cursor and retry.
    proof : str
        Purpose-signed person identifier and exact-intent digest, not a grant.
    """

    person_id: UUID
    intent: HostInvitationIntent
    proof: str


def _digest(
    scope: ProgrammeWorkbenchRequest,
    item_id: UUID,
    person_id: UUID,
    intent: HostInvitationIntent,
) -> str:
    for field in ("actor_id", "organization_id", "edition_id"):
        require_uuid(getattr(scope, field), field=field)
    require_uuid(item_id, field="item_id")
    return canonical_digest(
        {
            "actor_id": scope.actor_id,
            "organization_id": scope.organization_id,
            "edition_id": scope.edition_id,
            "item_id": item_id,
            "person_id": person_id,
            "intent": asdict(intent),
        }
    )


def prepare_host_invitation_preview(
    scope: ProgrammeWorkbenchRequest,
    *,
    item_id: UUID,
    intent: HostInvitationIntent,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> HostInvitationPreview | None:
    """Resolve a known person once under locked, audited fresh manager admission.

    Parameters
    ----------
    scope : ProgrammeWorkbenchRequest
        Trusted current actor, tenant and server correlation references.
    item_id : UUID
        Exact item selected by the separately authorized workbench context.
    intent : HostInvitationIntent
        Original complete proposed invitation; no source copy is inferred.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Current Programme policy or the existing guarded native-test seam.

    Returns
    -------
    HostInvitationPreview | None
        Audited selection proof or audited empty match; no invitation or receipt.

    Notes
    -----
    The owning admission/query boundary refuses closed private planning and
    audits an empty match when the address has no active verified person.
    """
    require_uuid(item_id, field="item_id")

    def load() -> HostInvitationPreview | None:
        admitted = authorize_programme_scope(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            capability_code=PROGRAMME_MANAGE_HOSTS,
            requested_fields=frozenset(),
            authorizer=authorizer,
            lock=True,
        )
        if not admitted.accepts_private_planning_writes:
            raise ProgrammeAuthorizationDeniedError
        # Validate the full pure intent before using the exact-address seam.
        validated = intent.normalized(scope.actor_id)
        person = resolve_active_verified_person_reference_by_email(
            email=validated.recipient_email
        )
        if person is None:
            return None
        normalized = validated.normalized(person.account_id)
        proof = signing.dumps(
            {
                "person_id": str(person.account_id),
                "intent": _digest(scope, item_id, person.account_id, normalized),
            },
            salt=_SALT,
        )
        return HostInvitationPreview(person.account_id, normalized, proof)

    return _authorized_query(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=PROGRAMME_MANAGE_HOSTS,
        requested_fields=frozenset(),
        operation="programme.host_invitation.preview",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=lambda preview: int(preview is not None),
        reason="Prepare one exact person for explicit Programme hosting confirmation",
        correlation_id=scope.correlation_id,
        source_channel="programme-hosts",
        authorizer=authorizer,
    )


def _verified_selection(
    scope: ProgrammeWorkbenchRequest,
    item_id: UUID,
    intent: HostInvitationIntent,
    proof: str,
) -> HostInvitationPreview:
    if (
        not isinstance(proof, str)
        or len(proof.encode("utf-8")) > MAX_HOST_SELECTION_BYTES
    ):
        raise ValueError
    payload = signing.loads(proof, salt=_SALT)
    if not isinstance(payload, dict) or set(payload) != {"person_id", "intent"}:
        raise ValueError
    person_id = UUID(payload["person_id"])
    normalized = intent.normalized(person_id)
    if not isinstance(payload["intent"], str) or not compare_digest(
        payload["intent"], _digest(scope, item_id, person_id, normalized)
    ):
        raise ValueError
    return HostInvitationPreview(person_id, normalized, proof)


def verify_host_invitation_preview(
    scope: ProgrammeWorkbenchRequest,
    *,
    item_id: UUID,
    intent: HostInvitationIntent,
    proof: str,
) -> HostInvitationPreview:
    """Verify original selection without re-resolving a mutable address or person.

    Parameters
    ----------
    scope : ProgrammeWorkbenchRequest
        Original actor and tenant; correlation does not change the signed intent.
    item_id : UUID
        Original route-selected Programme item.
    intent : HostInvitationIntent
        Original version/retry/selector and deliberate copy/rationale.
    proof : str
        Bounded purpose-signed selection, subject to configured signing fallbacks.

    Returns
    -------
    HostInvitationPreview
        Verified exact original selection, never fresh command/read authority.

    Raises
    ------
    ValidationError
        If proof is absent, malformed, foreign or bound to different intent.
    """
    try:
        return _verified_selection(scope, item_id, intent, proof)
    except (
        signing.BadSignature,
        ValueError,
        TypeError,
        UnicodeError,
        AttributeError,
    ) as error:
        raise ValidationError(
            {
                "selection_proof": (
                    "This original person selection cannot be verified. Keep the "
                    "original request after uncertainty; inspect retained history "
                    "before a new intent. Changed input needs a deliberate new "
                    "preview, not silent retargeting."
                )
            }
        ) from error
