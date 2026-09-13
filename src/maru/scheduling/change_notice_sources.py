"""Fresh actual-actor notice sources; no impersonated personal reader or sending."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from maru.authorization.catalog import POLICY_VERSION
from maru.programme.change_recipient_queries import load_host_change_recipient
from maru.programme.host_queries import ProgrammeHostReadRequest
from maru.programme.timetable_queries import (
    PersonalHostPurpose,
    load_personal_host_purposes,
)
from maru.workforce.change_recipient_queries import (
    ProgrammeWorkRecipientRequest,
    load_work_change_recipient,
)
from maru.workforce.personal_programme_links import load_personal_programme_work_links

from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_HISTORY,
    authorize_scheduling_scope,
)
from .catalogs import MAX_RELEASE_DEPENDENCY_USES
from .change_catalogs import ChangeNoticeSourceState, ChangeRecipientPurpose
from .change_recipient_queries import (
    OperatorChangeRecipientRequest,
    load_operator_change_recipient,
)
from .command_support import SchedulingUnavailableError, SchedulingVersionConflictError
from .inputs import scheduling_digest
from .models import (
    SchedulingOccurrence,
    SchedulingRelease,
    SchedulingReleaseApprovalDependency,
    SchedulingReleaseApprovalPlacement,
    SchedulingReleaseWithdrawal,
)
from .operator_release_impact import (
    OperatorOccurrenceChange,
    OperatorReleaseImpact,
    load_operator_release_impact,
)
from .operator_scope import OperatorReadRequest, OperatorScopeKind
from .personal_release_impact import (
    PersonalHostPresenceChange,
    load_personal_host_release_impact,
)
from .personal_release_impact import (
    _compare as _compare_host_presence,
)
from .personal_release_references import _presences
from .personal_work_release_impact import (
    PersonalWorkOccurrenceChange,
    load_personal_work_release_impact,
)
from .planning_queries import HISTORY_FIELDS, SchedulingReadRequest
from .release_impact import ReleaseSelectionChangeKind
from .release_impact_queries import load_programme_release_impact
from .release_queries import RELEASE_MANIFEST_FIELDS, ProgrammeReleaseState, _manifest

if TYPE_CHECKING:
    from collections.abc import Mapping

    from maru.workforce.personal_programme_links import PersonalProgrammeWorkLink

    from .change_inputs import ChangeRecipientSelection

type _Change = (
    PersonalHostPresenceChange | PersonalWorkOccurrenceChange | OperatorOccurrenceChange
)


@dataclass(frozen=True, slots=True)
class ProgrammeChangeNoticePreview:
    """Fresh minimized exact-purpose change, never portable sending authority.

    Attributes
    ----------
    release_id
        Exact current publication or latest explicit withdrawal source.
    occurrence_id
        Exact independently proven affected occurrence, not global cancellation.
    pointer_version
        Current publication/withdrawal sequence at the checked observation.
    source_state
        Available comparison or explicit governing suppression without old content.
    recipient_id
        Owner-resolved exact eligible person, never a supplied contact address.
    recipient_label
        Current sender-authorized operational label, or You for a genuine self read.
    recipient
        Exact owner relationship or independently admitted operator selection.
    snapshot_digest
        Complete source, purpose and generation fingerprint; not a permission token.
    dependency_digest
        Exact dependency-use snapshot for a writer's final generation-lock check.
    change
        One permitted comparison, absent when governing state suppresses it.
    """

    release_id: UUID
    occurrence_id: UUID
    pointer_version: int
    source_state: ChangeNoticeSourceState
    recipient_id: UUID
    recipient_label: str
    recipient: ChangeRecipientSelection
    snapshot_digest: str
    dependency_digest: str
    change: _Change | None


def _scope(request: SchedulingReadRequest) -> dict[str, UUID]:
    return {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }


def _personal_arguments(request: SchedulingReadRequest) -> dict[str, UUID]:
    return {
        **_scope(request),
        "actor_id": request.actor_id,
        "correlation_id": request.correlation_id,
    }


def _operator_request(
    request: SchedulingReadRequest, recipient: ChangeRecipientSelection
) -> OperatorReadRequest:
    return OperatorReadRequest(
        request.actor_id,
        request.organization_id,
        request.edition_id,
        request.correlation_id,
        OperatorScopeKind(recipient.purpose.value),
        recipient.target_id,
    )


def _jsonable(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise SchedulingUnavailableError
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, dict) and all(type(key) is str for key in value):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise SchedulingUnavailableError


def _host_proof(host: PersonalHostPurpose) -> dict[str, object]:
    return {
        "host_id": host.host_id,
        "item_id": host.item_id,
        "role": host.role,
        "state": host.state,
        "version": host.version,
        "invitation_sequence": host.invitation_sequence,
    }


def _operator_proof(impact: OperatorReleaseImpact) -> dict[str, object]:
    return {
        "policy_version": POLICY_VERSION,
        "kind": impact.kind.value,
        "target_id": impact.target_id,
        "room_links": tuple(asdict(row) for row in impact.room_links),
        "staffing_adopted": impact.staffing_adopted,
        "work_links": tuple(asdict(row) for row in impact.work_links),
    }


def _publication(
    request: SchedulingReadRequest,
    *,
    selected_release_id: UUID,
    current_release_id: UUID | None,
    pointer_version: int | None,
    state: ProgrammeReleaseState | None,
) -> SchedulingRelease:
    if (
        state is None
        or state is ProgrammeReleaseState.ABSENT
        or pointer_version is None
    ):
        raise SchedulingUnavailableError
    if state is ProgrammeReleaseState.WITHDRAWN:
        withdrawal = (
            SchedulingReleaseWithdrawal.objects.filter(
                **_scope(request), pointer_version=pointer_version
            )
            .values_list("release_id", flat=True)
            .first()
        )
        if withdrawal != selected_release_id:
            raise SchedulingVersionConflictError
    elif current_release_id != selected_release_id:
        raise SchedulingVersionConflictError
    publication = SchedulingRelease.objects.filter(
        **_scope(request), id=selected_release_id
    ).first()
    if publication is None:
        raise SchedulingUnavailableError
    return publication


def _approval_ids(
    request: SchedulingReadRequest, release: SchedulingRelease
) -> tuple[UUID, ...]:
    ids = {release.id}
    if release.previous_release_id is not None:
        ids.add(release.previous_release_id)
    approvals = tuple(
        SchedulingRelease.objects.filter(**_scope(request), id__in=ids)
        .order_by("id")
        .values_list("approval_id", flat=True)
    )
    if len(approvals) != len(ids):
        raise SchedulingUnavailableError
    return approvals


def _generation_digest(
    request: SchedulingReadRequest, release: SchedulingRelease
) -> str:
    # A second material source change while already invalidated must not inherit
    # acknowledgement merely because the coarse warning state is unchanged.
    approvals = _approval_ids(request, release)
    rows = tuple(
        SchedulingReleaseApprovalDependency.objects.filter(
            **_scope(request), approval_id__in=approvals
        )
        .order_by("approval_id", "dependency_id", "approval_placement_id", "horizon")
        .values_list(
            "approval_id",
            "dependency_id",
            "captured_generation",
            "dependency__generation",
            "approval__dependency_count",
            "approval_placement_id",
            "horizon",
            "operational_ends_at",
        )[: 2 * MAX_RELEASE_DEPENDENCY_USES + 1]
    )
    if not rows or len(rows) > 2 * MAX_RELEASE_DEPENDENCY_USES:
        raise SchedulingUnavailableError
    if {row[0] for row in rows} != set(approvals):
        raise SchedulingUnavailableError
    for approval_id in approvals:
        selected = tuple(row for row in rows if row[0] == approval_id)
        if (
            not 1 <= len(selected) <= MAX_RELEASE_DEPENDENCY_USES
            or len({(row[1], row[5], row[6]) for row in selected}) != len(selected)
            or any(
                row[4] != len(selected)
                or type(row[2]) is not int
                or type(row[3]) is not int
                or not 1 <= row[2] <= row[3] < 2**63 - 1
                for row in selected
            )
        ):
            raise SchedulingUnavailableError
    return scheduling_digest({"generations": _jsonable(rows)})


def _suppressed_membership(
    request: SchedulingReadRequest,
    release: SchedulingRelease,
    occurrence_id: UUID,
    recipient: ChangeRecipientSelection,
    *,
    operator: OperatorReleaseImpact | None,
) -> None:
    # Membership-only lookup after independent current purpose admission. Never
    # read or restore withdrawn/invalidated timing, titles or instructions.
    chosen = SchedulingReleaseApprovalPlacement.objects.filter(
        **_scope(request),
        approval_id__in=_approval_ids(request, release),
        occurrence_id=occurrence_id,
        placement__organization_id=request.organization_id,
        placement__edition_id=request.edition_id,
    )
    if recipient.purpose is ChangeRecipientPurpose.HOST:
        chosen = chosen.filter(
            placement__host_presences__host_relationship_id=recipient.target_id,
            placement__host_presences__organization_id=request.organization_id,
            placement__host_presences__edition_id=request.edition_id,
        )
    elif operator is not None:
        work_occurrences = {row.occurrence_id for row in operator.work_links}
        if occurrence_id not in work_occurrences:
            chosen = chosen.filter(
                placement__space_selection_id__in={
                    row.space_id for row in operator.room_links
                }
            )
    if not chosen.exists():
        raise SchedulingUnavailableError


def _finish(
    request: SchedulingReadRequest,
    *,
    release: SchedulingRelease,
    occurrence_id: UUID,
    pointer_version: int,
    state: ProgrammeReleaseState,
    recipient_id: UUID,
    recipient_label: str,
    recipient: ChangeRecipientSelection,
    purpose_proof: Mapping[str, object],
    changes: tuple[_Change, ...] | None,
    operator: OperatorReleaseImpact | None = None,
) -> ProgrammeChangeNoticePreview:
    selected = None
    source_state = ChangeNoticeSourceState(state.value)
    if changes is None:
        if state is ProgrammeReleaseState.AVAILABLE:
            source_state = ChangeNoticeSourceState.COMPARISON_SUPPRESSED
        _suppressed_membership(
            request, release, occurrence_id, recipient, operator=operator
        )
    else:
        matching = tuple(
            row
            for row in changes
            if (
                row.work.occurrence_id
                if isinstance(row, PersonalWorkOccurrenceChange)
                else row.occurrence_id
            )
            == occurrence_id
        )
        if (
            len(matching) != 1
            or matching[0].kind is ReleaseSelectionChangeKind.UNCHANGED
        ):
            raise SchedulingUnavailableError
        selected = matching[0]
    dependency_digest = _generation_digest(request, release)
    digest = scheduling_digest(
        {
            "contract": "programme.change-notice@1",
            "organization_id": str(request.organization_id),
            "edition_id": str(request.edition_id),
            "release_id": str(release.id),
            "pointer_version": pointer_version,
            "source_state": source_state.value,
            "occurrence_id": str(occurrence_id),
            "recipient_id": str(recipient_id),
            "recipient": recipient.payload(),
            "purpose": _jsonable(dict(purpose_proof)),
            "change": _jsonable(asdict(selected)) if selected is not None else None,
            "generations": dependency_digest,
        }
    )
    return ProgrammeChangeNoticePreview(
        release.id,
        occurrence_id,
        pointer_version,
        source_state,
        recipient_id,
        recipient_label,
        recipient,
        digest,
        dependency_digest,
        selected,
    )


def _sender_host_or_work(
    request: SchedulingReadRequest,
    release_id: UUID,
    occurrence_id: UUID,
    recipient: ChangeRecipientSelection,
) -> ProgrammeChangeNoticePreview:
    # The outer notice read already admits its own independent field. History
    # admission precedes even the opaque occurrence-to-item lookup below.
    authorize_scheduling_scope(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        actor_id=request.actor_id,
        capability_code=VIEW_HISTORY,
        requested_fields=HISTORY_FIELDS | RELEASE_MANIFEST_FIELDS,
        authorizer=DEFAULT_SCHEDULING_AUTHORIZER,
    )
    host = None
    work: PersonalProgrammeWorkLink | None = None
    if recipient.purpose is ChangeRecipientPurpose.HOST:
        item_id = (
            SchedulingOccurrence.objects.filter(**_scope(request), id=occurrence_id)
            .values_list("programme_item_id", flat=True)
            .first()
        )
        if item_id is None:
            raise SchedulingUnavailableError
        person = load_host_change_recipient(
            ProgrammeHostReadRequest(
                request.actor_id,
                request.organization_id,
                request.edition_id,
                item_id,
                request.correlation_id,
            ),
            host_id=recipient.target_id,
        )
        relationship = person.relationship
        host = PersonalHostPurpose(
            relationship.host_id,
            person.item_id,
            relationship.role,
            relationship.state,
            relationship.version,
            relationship.invitation_sequence,
            "",
            "",
        )
        account, label, proof = (
            person.account_id,
            person.display_label,
            _host_proof(host),
        )
    else:
        holder = load_work_change_recipient(
            ProgrammeWorkRecipientRequest(
                request.actor_id,
                request.organization_id,
                request.edition_id,
                request.correlation_id,
                occurrence_id,
                recipient.target_id,
            )
        )
        work = holder.work
        account, label, proof = holder.account_id, holder.display_label, asdict(work)
    # Owner recipient queries have locked the complete person set before the
    # history query can perform an actor-only final lock. Never reverse this order.
    impact = load_programme_release_impact(request, release_id=release_id)
    release = _publication(
        request,
        selected_release_id=release_id,
        current_release_id=impact.release_id if impact.is_active else None,
        pointer_version=impact.observed_pointer_version,
        state=impact.after_state,
    )
    changes: tuple[_Change, ...] | None = None
    if impact.changes is not None:
        if host is not None:
            before = (
                _manifest(**_scope(request), release_id=release.previous_release_id)
                if release.previous_release_id
                else None
            )
            after = _manifest(**_scope(request), release_id=release.id)
            if (
                after.state is not impact.after_state
                or after.pointer_version != impact.observed_pointer_version
                or not after.is_active
                or (
                    before is not None
                    and (
                        before.state is not impact.before_state
                        or before.pointer_version != impact.observed_pointer_version
                    )
                )
            ):
                raise SchedulingUnavailableError
            confirmed = {host.host_id: host}
            changes = _compare_host_presence(
                confirmed,
                _presences(request, before, confirmed) if before else (),
                _presences(request, after, confirmed),
                before,
                after,
            )
        elif work is not None:
            changes = tuple(
                PersonalWorkOccurrenceChange(
                    work,
                    row.selection.kind,
                    row.before,
                    row.after,
                    row.selection.changed_fields + row.geometry_fields,
                )
                for row in impact.changes
                if row.selection.occurrence_id == occurrence_id
            )
    return _finish(
        request,
        release=release,
        occurrence_id=occurrence_id,
        pointer_version=impact.observed_pointer_version,
        state=impact.after_state,
        recipient_id=account,
        recipient_label=label,
        recipient=recipient,
        purpose_proof=proof,
        changes=changes,
    )


def _sender_sources(
    request: SchedulingReadRequest,
    *,
    release_id: UUID,
    occurrence_id: UUID,
    recipient: ChangeRecipientSelection,
) -> ProgrammeChangeNoticePreview:
    recipient.validated()
    if recipient.purpose in {ChangeRecipientPurpose.HOST, ChangeRecipientPurpose.WORK}:
        return _sender_host_or_work(request, release_id, occurrence_id, recipient)
    if recipient.operator_account_id is None:
        raise SchedulingUnavailableError
    selected = load_operator_change_recipient(
        OperatorChangeRecipientRequest(
            request,
            recipient.operator_account_id,
            OperatorScopeKind(recipient.purpose.value),
            recipient.target_id,
        )
    )
    # This read is by the actual sender, who independently needs this scope.
    impact = load_operator_release_impact(_operator_request(request, recipient))
    release = _publication(
        request,
        selected_release_id=release_id,
        current_release_id=impact.release_id,
        pointer_version=impact.pointer_version,
        state=impact.state,
    )
    return _finish(
        request,
        release=release,
        occurrence_id=occurrence_id,
        pointer_version=impact.pointer_version,
        state=impact.state,
        recipient_id=selected.account_id,
        recipient_label=selected.display_label,
        recipient=recipient,
        purpose_proof=_operator_proof(impact),
        changes=impact.changes,
        operator=impact,
    )


def _self_sources(
    request: SchedulingReadRequest,
    *,
    release_id: UUID,
    occurrence_id: UUID,
    recipient: ChangeRecipientSelection,
) -> ProgrammeChangeNoticePreview:
    recipient.validated()
    arguments = _personal_arguments(request)
    operator = None
    if recipient.purpose is ChangeRecipientPurpose.HOST:
        hosts = tuple(
            host
            for host in load_personal_host_purposes(**arguments)
            if host.host_id == recipient.target_id and host.state == "confirmed"
        )
        if len(hosts) != 1:
            raise SchedulingUnavailableError
        personal = load_personal_host_release_impact(**arguments)
        proof = _host_proof(hosts[0])
        changes: tuple[_Change, ...] | None = (
            tuple(row for row in personal.changes if row.host_id == recipient.target_id)
            if personal.changes is not None
            else None
        )
        state, pointer, current = (
            personal.state,
            personal.pointer_version,
            personal.release_id,
        )
    elif recipient.purpose is ChangeRecipientPurpose.WORK:
        links = load_personal_programme_work_links(**arguments)
        work = tuple(
            row
            for row in links or ()
            if row.commitment_id == recipient.target_id
            and row.occurrence_id == occurrence_id
            and row.status in {"claimed", "confirmed"}
        )
        if len(work) != 1:
            raise SchedulingUnavailableError
        own_work = load_personal_work_release_impact(**arguments)
        proof = asdict(work[0])
        changes = (
            tuple(
                row
                for row in own_work.changes
                if row.work.commitment_id == recipient.target_id
            )
            if own_work.changes is not None
            else None
        )
        state, pointer, current = (
            own_work.state,
            own_work.pointer_version,
            own_work.release_id,
        )
    else:
        if recipient.operator_account_id != request.actor_id:
            raise SchedulingUnavailableError
        operator = load_operator_release_impact(_operator_request(request, recipient))
        proof, changes = _operator_proof(operator), operator.changes
        state, pointer, current = (
            operator.state,
            operator.pointer_version,
            operator.release_id,
        )
    if state is None or pointer is None:
        raise SchedulingUnavailableError
    release = _publication(
        request,
        selected_release_id=release_id,
        current_release_id=current,
        pointer_version=pointer,
        state=state,
    )
    return _finish(
        request,
        release=release,
        occurrence_id=occurrence_id,
        pointer_version=pointer,
        state=state,
        recipient_id=request.actor_id,
        recipient_label="You",
        recipient=recipient,
        purpose_proof=proof,
        changes=changes,
        operator=operator,
    )
