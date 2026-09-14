"""Purpose-signed exact decision previews without copied private token payloads."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hmac import compare_digest
from typing import TYPE_CHECKING

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import ProgrammeReviewAction
from .programme_authorization import DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
from .programme_decider_queries import (
    DecisionEvidence,
    DecisionWork,
    _purpose,
    get_programme_decision_evidence,
    get_programme_decision_work,
)
from .programme_inputs import (
    canonical_programme_digest,
    normalized_programme_text,
    require_programme_uuid,
)
from .programme_review_inputs import (
    MAX_REVIEW_REASON,
    ProgrammeDecisionTemplateInput,
    ProgrammeReviewCommandInput,
)
from .programme_review_queries import ProgrammeReviewReadRequest, _audit
from .programme_review_rules import ProgrammeReviewConflictError

if TYPE_CHECKING:
    from uuid import UUID

    from .programme_authorization import ApplicationsProgrammeAuthorizer

_DEFAULT_AUTHORIZER = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_SALT = "applications.programme-decision-preview.v1"
MAX_DECISION_PREVIEW_BYTES = 2048


@dataclass(frozen=True, slots=True)
class DecisionIntent:
    """Retain the original closed version, retry, outcome and separate text fields.

    Attributes
    ----------
    expected_version : int
        Original inspected case version, never silently replaced.
    retry_key : UUID
        Original canonical command intent identifier.
    outcome : str
        Deliberately chosen final or wait-list outcome.
    text : str
        Recipient-visible additional text, separate from the pinned template.
    reason : str
        Private retained decision rationale, never appended to the message.
    """

    expected_version: int
    retry_key: UUID
    outcome: str
    text: str
    reason: str

    def normalized(self, case_id: UUID) -> DecisionIntent:
        """Use the canonical owner's exact text and closed command semantics.

        Parameters
        ----------
        case_id : UUID
            Exact case selected by the route, not an editable target field.

        Returns
        -------
        DecisionIntent
            Canonical preview values matching the eventual owner command.

        Raises
        ------
        ValidationError
            If the original version is outside the closed command boundary.
        """
        require_programme_uuid(case_id, field="case_id")
        require_programme_uuid(self.retry_key, field="retry_key")
        if (
            type(self.expected_version) is not int
            or not 1 <= self.expected_version <= 2**63 - 2
        ):
            raise ValidationError("Use the original positive case version.")
        command = ProgrammeReviewCommandInput(
            ProgrammeReviewAction.DECIDED,
            case_id,
            outcome=self.outcome,
            text=self.text,
        ).normalized()
        reason = normalized_programme_text(
            self.reason,
            field="reason",
            maximum=MAX_REVIEW_REASON,
            required=True,
            multiline=True,
        )
        return replace(self, text=command.text, reason=reason)


@dataclass(frozen=True, slots=True)
class DecisionPreview:
    """Show the exact composed message and private intent before confirmation.

    Attributes
    ----------
    work : DecisionWork
        Independently protected pinned source and policy.
    evidence : DecisionEvidence
        Original all-stage readiness and bounded history page.
    intent : DecisionIntent
        Canonical original request whose digest is confirmed.
    template : ProgrammeDecisionTemplateInput
        Exact pinned template and acknowledgement policy for the chosen outcome.
    message : str
        Template plus two line feeds plus deliberate recipient text.
    proof : str
        Bounded signed digest, not copied private text or a permission grant.
    """

    work: DecisionWork
    evidence: DecisionEvidence
    intent: DecisionIntent
    template: ProgrammeDecisionTemplateInput
    message: str
    proof: str


def _digest(
    request: ProgrammeReviewReadRequest, case_id: UUID, intent: DecisionIntent
) -> str:
    return canonical_programme_digest(
        {
            "actor": request.actor_id,
            "organization": request.organization_id,
            "edition": request.edition_id,
            "department": request.department_id,
            "case": case_id,
            **asdict(intent),
        }
    )


@transaction.atomic
def prepare_programme_decision_preview(
    *,
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    intent: DecisionIntent,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> DecisionPreview:
    """Bind a deliberate decision to independently inspected current ready evidence.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact decider/context purpose; evidence is additionally proved separately.
    case_id : UUID
        Original route-selected case.
    intent : DecisionIntent
        Original version/retry and explicit outcome/text/rationale.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test admission seam.

    Returns
    -------
    DecisionPreview
        Exact private preview with no mutation, recipient lookup or delivery.

    Raises
    ------
    ProgrammeReviewConflictError
        If the original source/version or current all-stage decision gates fail.
    """
    intent = intent.normalized(case_id)
    work = get_programme_decision_work(
        request=request, case_id=case_id, authorizer=authorizer
    )
    evidence = get_programme_decision_evidence(
        request=replace(request, requested_fields=frozenset({"review_evidence"})),
        case_id=case_id,
        authorizer=authorizer,
    )
    if (
        work.case.version != intent.expected_version
        or evidence.detail.version != intent.expected_version
        or not work.writable
        or not work.case.current_revision
        or work.case.stage != len(work.policy.stages) - 1
        or work.case.state not in {"open", "waitlisted"}
        or (work.case.state == "waitlisted" and intent.outcome == "waitlisted")
        or len(evidence.stages) != len(work.policy.stages)
        or not all(stage.ready for stage in evidence.stages)
    ):
        raise ProgrammeReviewConflictError
    template = next(
        row for row in work.policy.templates if row.outcome == intent.outcome
    )
    proof = signing.dumps({"intent": _digest(request, case_id, intent)}, salt=_SALT)
    result = DecisionPreview(
        work, evidence, intent, template, template.text + "\n\n" + intent.text, proof
    )
    _audit(request, "decision_preview", case_id, authorizer)
    return result


def _verified(proof: str, digest: str) -> None:
    if (
        not isinstance(proof, str)
        or len(proof.encode("ascii")) > MAX_DECISION_PREVIEW_BYTES
        or proof.startswith(".")
    ):
        raise ValueError
    value = signing.loads(proof, salt=_SALT)
    if (
        not isinstance(value, dict)
        or set(value) != {"intent"}
        or not isinstance(value["intent"], str)
        or not compare_digest(value["intent"], digest)
    ):
        raise ValueError


def verify_programme_decision_preview(
    *,
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    intent: DecisionIntent,
    proof: str,
) -> DecisionIntent:
    """Verify only original preview integrity, never fresh authority or content.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact decider/context binding; the caller must separately authorize it.
    case_id : UUID
        Exact route-selected original case.
    intent : DecisionIntent
        Original submitted values, normalized using canonical semantics.
    proof : str
        Bounded purpose-signed digest; no expiry prevents old receipt recovery.

    Returns
    -------
    DecisionIntent
        Verified original normalized intent, not a write or content permission.

    Raises
    ------
    ValidationError
        If the signature or exact actor/scope/version/retry/content binding fails.
    """
    _purpose(request, "review_context")
    intent = intent.normalized(case_id)
    try:
        _verified(proof, _digest(request, case_id, intent))
    except (signing.BadSignature, ValueError, TypeError, UnicodeError) as error:
        raise ValidationError(
            "This confirmation no longer matches its exact preview. Keep the "
            "original intent and inspect current state before previewing again."
        ) from error
    return intent
