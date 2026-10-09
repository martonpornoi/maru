"""Audited, purpose-admitted Guidance access pages and personal approval tasks."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.guidance_catalog import (
    GUIDANCE_CONTROL_CAPABILITY,
    GUIDANCE_CONTROLLER_ROLE_CODE,
    GUIDANCE_ROLE_RECIPES,
    GuidanceRoleRecipe,
)
from maru.authorization.models import (
    AuthorityIssuance,
    GuidanceAccessRequest,
    RoleAssignment,
)
from maru.authorization.policy import (
    decide_verified_principal_exact_edition,
    resolve_edition_target,
)
from maru.authorization.provenance import (
    ControlHorizonMode,
    authority_issuance_is_current,
)
from maru.events.knowledge_scope import resolve_knowledge_edition_scope
from maru.events.knowledge_workspace_queries import (
    KnowledgeWorkspaceReference,
    knowledge_workspace_reference,
)
from maru.identity.models import Account
from maru.identity.queries import active_verified_person_account_display_labels

_MAX_ACCESS_ASSIGNMENTS = 256
_MAX_RETAINED_TASKS = 100


@dataclass(frozen=True, slots=True)
class GuidanceAccessPerson:
    """An admitted task participant label, never a browsable account directory.

    Attributes
    ----------
    account_id : UUID
        Identity of the admitted person represented by this choice.
    label : str
        Admitted display label for this specific person.
    """

    account_id: UUID
    label: str


@dataclass(frozen=True, slots=True)
class GuidanceAccessAssignment:
    """One purpose-qualified assignment and its separately computed current state.

    Attributes
    ----------
    assignment_id : UUID
        Identity of the exact retained role assignment.
    recipient : GuidanceAccessPerson
        Admitted person receiving the requested role.
    recipe_code : str
        Stable code of the exact canonical access recipe.
    recipe_label : str
        Display label describing the canonical access recipe.
    expires_at : datetime | None
        Requested role expiry, or None for an open-ended term.
    current : bool
        Whether this exact assignment and its original qualified lineage remain
        current.
    revoked : bool
        Whether an explicit revocation has been retained for this assignment.
    """

    assignment_id: UUID
    recipient: GuidanceAccessPerson
    recipe_code: str
    recipe_label: str
    expires_at: datetime | None
    current: bool
    revoked: bool


@dataclass(frozen=True, slots=True)
class GuidanceAccessWorkspace:
    """Exact edition context, fixed recipes and current access-management choices.

    Attributes
    ----------
    scope : KnowledgeWorkspaceReference
        Admitted public event labels and exact adoption context.
    recipes : tuple[GuidanceRoleRecipe, ...]
        Closed content recipes available through named approval; excludes
        controllers.
    approvers : tuple[GuidanceAccessPerson, ...]
        Admitted current controllers available for independent approval.
    assignments : tuple[GuidanceAccessAssignment, ...]
        Purpose-qualified assignments with separately resolved current status.
    """

    scope: KnowledgeWorkspaceReference
    recipes: tuple[GuidanceRoleRecipe, ...]
    approvers: tuple[GuidanceAccessPerson, ...]
    assignments: tuple[GuidanceAccessAssignment, ...]


@dataclass(frozen=True, slots=True)
class GuidanceAccessRequestView:
    """The accepted recipient, recipe and original approval terms of one task.

    Attributes
    ----------
    request_id : UUID
        Opaque identity of the retained immutable request.
    request_digest : str
        Digest binding the exact immutable request terms.
    organization_id : UUID
        Exact organization owning this event and its evidence.
    edition_id : UUID
        Exact event edition within the owning organization.
    edition_name : str
        Admitted event edition display name.
    requested_by : GuidanceAccessPerson
        Actual current controller who proposed the immutable access terms.
    approver : GuidanceAccessPerson
        Named independent controller whose authenticated decision is required.
    recipient : GuidanceAccessPerson
        Admitted person receiving the requested role.
    recipe_code : str
        Stable code of the exact canonical access recipe.
    recipe_label : str
        Display label describing the canonical access recipe.
    capability_codes : tuple[str, ...]
        Exact distinct permissions included in the accepted canonical recipe.
    reason : str
        Private accountable explanation retained with the request.
    expires_at : datetime | None
        Requested role expiry, or None for an open-ended term.
    decision_deadline : datetime
        Last instant at which a fresh approval or refusal may be recorded.
    state : str
        Current request state derived from retained decisions and source
        validity.
    can_answer : bool
        Whether the admitted viewing person may currently answer this request.
    own_answer : bool | None
        The viewing person's recorded decision, or None if unanswered.
    assignment_id : UUID | None
        Resulting role assignment, or None while pending or after refusal.
    """

    request_id: UUID
    request_digest: str
    organization_id: UUID
    edition_id: UUID
    edition_name: str
    requested_by: GuidanceAccessPerson
    approver: GuidanceAccessPerson
    recipient: GuidanceAccessPerson
    recipe_code: str
    recipe_label: str
    capability_codes: tuple[str, ...]
    reason: str
    expires_at: datetime | None
    decision_deadline: datetime
    state: str
    can_answer: bool
    own_answer: bool | None
    assignment_id: UUID | None


def require_guidance_access_actor(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> None:
    """Admit exact purpose and field ceiling before reading owner or person labels.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    organization_id : UUID
        Exact organization owning the requested scope.
    edition_id : UUID
        Exact event edition within the organization.

    Raises
    ------
    PermissionDenied
        If current actor, purpose, scope or native protection is unavailable.
    """
    from maru.authorization.guidance_readiness import (  # noqa: PLC0415
        require_guidance_authority_integrity,
    )

    require_guidance_authority_integrity()
    decision = decide_verified_principal_exact_edition(
        principal_id=actor.id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=GUIDANCE_CONTROL_CAPABILITY,
        requested_fields=frozenset({"guidance_access"}),
    )
    if not decision.allowed or not frozenset({"guidance_access"}).issubset(
        decision.fields
    ):
        raise PermissionDenied("Current Guidance access responsibility is required.")
    scope = resolve_knowledge_edition_scope(
        organization_id=organization_id, edition_id=edition_id
    )
    if scope is None or not scope.parents_active:
        raise PermissionDenied("Guidance access is unavailable for this event.")


def _audit(
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    target_id: UUID | None = None,
) -> None:
    require_guidance_access_actor(
        actor=actor, organization_id=organization_id, edition_id=edition_id
    )
    if not isinstance(correlation_id, UUID) or correlation_id.int == 0:
        raise ValidationError("Use a non-empty trace.")
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=GUIDANCE_CONTROL_CAPABILITY,
            operation="authorization.guidance.access.review",
            target_type="authorization.guidance_access_request",
            target_id=target_id,
            outcome="allow",
            reason_code="current_guidance_controller",
            correlation_id=correlation_id,
            source_channel="html",
            obligations=("audit_sensitive_read",),
        )
    )


def _current(assignment: RoleAssignment) -> bool:
    if assignment.edition_id is None:
        return False
    target = resolve_edition_target(
        organization_id=assignment.organization_id, edition_id=assignment.edition_id
    )
    issuance = AuthorityIssuance.objects.filter(
        role_assignment_id=assignment.id
    ).first()
    now = timezone.now()
    return bool(
        target is not None
        and issuance is not None
        and authority_issuance_is_current(
            issuance_ordinal=issuance.ordinal,
            principal_id=assignment.principal_id,
            capability_code=assignment.role_bundle.capability_codes[0],
            target=target,
            requested_effective_from=now,
            requested_expires_at=None,
            evaluated_at=now,
            horizon_mode=ControlHorizonMode.POINT_IN_TIME,
        )
    )


def load_guidance_access_workspace(
    *, actor: Account, organization_id: UUID, edition_id: UUID, correlation_id: UUID
) -> GuidanceAccessWorkspace:
    """Return bounded actual access relationships only after purpose admission.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    organization_id : UUID
        Exact organization owning the requested scope.
    edition_id : UUID
        Exact event edition within the organization.
    correlation_id : UUID
        Non-empty audit trace for this attempt.

    Returns
    -------
    GuidanceAccessWorkspace
        The admitted immutable result; it grants no additional authority.

    Raises
    ------
    PermissionDenied
        If current actor, purpose, scope or native protection is unavailable.
    ValidationError
        If the immutable intent, version, acceptance or retained evidence conflicts.
    """
    require_guidance_access_actor(
        actor=actor, organization_id=organization_id, edition_id=edition_id
    )
    scope = knowledge_workspace_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if scope is None:
        raise PermissionDenied
    rows = tuple(
        RoleAssignment.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            role_bundle__code__in=GUIDANCE_ROLE_RECIPES,
        )
        .select_related("role_bundle")
        .order_by("created_at", "id")[:257]
    )
    if len(rows) > _MAX_ACCESS_ASSIGNMENTS:
        raise ValidationError(
            "This access history is too large for this view; no "
            "partial inventory is shown."
        )
    labels = active_verified_person_account_display_labels(
        account_ids=tuple(row.principal_id for row in rows)
    )
    current = {row.id: _current(row) for row in rows}
    approvers = {
        row.principal_id: GuidanceAccessPerson(
            row.principal_id, labels[row.principal_id]
        )
        for row in rows
        if row.role_bundle.code == GUIDANCE_CONTROLLER_ROLE_CODE
        and current[row.id]
        and row.principal_id in labels
        and row.principal_id != actor.id
    }
    assignments = tuple(
        GuidanceAccessAssignment(
            row.id,
            GuidanceAccessPerson(
                row.principal_id, labels.get(row.principal_id, "Unavailable account")
            ),
            row.role_bundle.code,
            row.role_bundle.name,
            row.expires_at,
            current[row.id],
            row.revoked_at is not None,
        )
        for row in rows
    )
    result = GuidanceAccessWorkspace(
        scope,
        tuple(
            recipe
            for recipe in GUIDANCE_ROLE_RECIPES.values()
            if recipe.code != GUIDANCE_CONTROLLER_ROLE_CODE
        ),
        tuple(approvers.values()),
        assignments,
    )
    if (
        knowledge_workspace_reference(
            organization_id=organization_id, edition_id=edition_id
        )
        != scope
    ):
        raise PermissionDenied
    _audit(actor, organization_id, edition_id, correlation_id)
    return result


def _request_sources_are_current(request: GuidanceAccessRequest) -> bool:
    from maru.events.knowledge_scope import (  # noqa: PLC0415
        resolve_knowledge_edition_scope,
    )
    from maru.identity.queries import (  # noqa: PLC0415
        resolve_active_verified_person_reference,
    )

    scope = resolve_knowledge_edition_scope(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    target = resolve_edition_target(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    if (
        scope is None
        or not scope.accepts_writes
        or target is None
        or resolve_active_verified_person_reference(account_id=request.recipient_id)
        is None
    ):
        return False
    return all(
        resolve_active_verified_person_reference(account_id=principal) is not None
        and authority_issuance_is_current(
            issuance_ordinal=source,
            principal_id=principal,
            capability_code=GUIDANCE_CONTROL_CAPABILITY,
            target=target,
            requested_effective_from=request.effective_from,
            requested_expires_at=request.expires_at,
        )
        for principal, source in (
            (request.requested_by_id, request.actor_source_id),
            (request.approver_id, request.approver_source_id),
        )
    )


def load_guidance_access_request(
    *, actor: Account, request_id: UUID, correlation_id: UUID
) -> GuidanceAccessRequestView:
    """Release only a named controller's exact pending or retained approval task.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    request_id : UUID
        Opaque identifier of the original immutable request.
    correlation_id : UUID
        Non-empty audit trace for this attempt.

    Returns
    -------
    GuidanceAccessRequestView
        The admitted immutable result; it grants no additional authority.

    Raises
    ------
    PermissionDenied
        If current actor, purpose, scope or native protection is unavailable.
    """
    locator = (
        GuidanceAccessRequest.objects.filter(
            Q(requested_by_id=actor.id) | Q(approver_id=actor.id), id=request_id
        )
        .values("organization_id", "edition_id")
        .first()
    )
    if locator is None:
        raise PermissionDenied("This access request is unavailable.")
    require_guidance_access_actor(
        actor=actor,
        organization_id=locator["organization_id"],
        edition_id=locator["edition_id"],
    )
    row = GuidanceAccessRequest.objects.select_related("role_bundle").get(
        id=request_id,
        organization_id=locator["organization_id"],
        edition_id=locator["edition_id"],
    )
    scope = knowledge_workspace_reference(
        organization_id=row.organization_id, edition_id=row.edition_id
    )
    if scope is None:
        raise PermissionDenied
    labels = active_verified_person_account_display_labels(
        account_ids=(row.requested_by_id, row.approver_id, row.recipient_id)
    )

    def person(person_id: UUID) -> GuidanceAccessPerson:
        return GuidanceAccessPerson(
            person_id, labels.get(person_id, "Unavailable account")
        )

    decision = getattr(row, "decision", None)
    state = (
        ("accepted" if decision.accepted else "declined")
        if decision
        else "expired"
        if row.decision_deadline <= timezone.now()
        else "changed"
        if not _request_sources_are_current(row)
        else "waiting"
    )
    result = GuidanceAccessRequestView(
        row.id,
        row.request_digest,
        row.organization_id,
        row.edition_id,
        scope.edition_name,
        person(row.requested_by_id),
        person(row.approver_id),
        person(row.recipient_id),
        row.role_bundle.code,
        row.role_bundle.name,
        tuple(row.role_bundle.capability_codes),
        row.reason,
        row.expires_at,
        row.decision_deadline,
        state,
        state == "waiting" and actor.id == row.approver_id,
        decision.accepted if decision and actor.id == row.approver_id else None,
        decision.assignment_id if decision else None,
    )
    if (
        knowledge_workspace_reference(
            organization_id=row.organization_id, edition_id=row.edition_id
        )
        != scope
    ):
        raise PermissionDenied
    _audit(actor, row.organization_id, row.edition_id, correlation_id, row.id)
    return result


def list_my_guidance_access_requests(
    *, actor: Account, correlation_id: UUID
) -> tuple[GuidanceAccessRequestView, ...]:
    """List bounded own tasks; current permission remains mandatory for each item.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    correlation_id : UUID
        Non-empty audit trace for this attempt.

    Returns
    -------
    tuple[GuidanceAccessRequestView, ...]
        The admitted immutable result; it grants no additional authority.

    Raises
    ------
    ValidationError
        If the immutable intent, version, acceptance or retained evidence conflicts.
    """
    ids = tuple(
        GuidanceAccessRequest.objects.filter(
            Q(requested_by_id=actor.id) | Q(approver_id=actor.id)
        )
        .order_by("-created_at", "-id")
        .values_list("id", flat=True)[:101]
    )
    if len(ids) > _MAX_RETAINED_TASKS:
        raise ValidationError("Too many retained access requests; open the exact task.")
    result = []
    for request_id in ids:
        try:
            result.append(
                load_guidance_access_request(
                    actor=actor, request_id=request_id, correlation_id=correlation_id
                )
            )
        except PermissionDenied:
            continue
    return tuple(result)


def has_current_guidance_tasks(*, actor: Account, correlation_id: UUID) -> bool:
    """Expose only whether this actual person has an admitted pending setup decision.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    correlation_id : UUID
        Non-empty audit trace for this attempt.

    Returns
    -------
    bool
        Whether the complete exact contract is currently satisfied.
    """
    from maru.events.guidance_activation_queries import (  # noqa: PLC0415
        has_current_guidance_activation_tasks,
    )

    if not actor.is_active:
        return False
    if has_current_guidance_activation_tasks(
        actor=actor, correlation_id=correlation_id
    ):
        return True
    candidates = (
        GuidanceAccessRequest.objects.filter(
            approver_id=actor.id,
            decision__isnull=True,
            decision_deadline__gt=timezone.now(),
        )
        .only("id", "organization_id", "edition_id")
        .order_by("created_at", "id")
    )
    for request in candidates[:256]:
        try:
            require_guidance_access_actor(
                actor=actor,
                organization_id=request.organization_id,
                edition_id=request.edition_id,
            )
        except PermissionDenied:
            continue
        if not _request_sources_are_current(request):
            continue
        _audit(actor, request.organization_id, request.edition_id, correlation_id)
        return True
    return False
