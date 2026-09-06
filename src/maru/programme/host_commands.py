"""Governed host invitations, person decisions and purpose-owned availability."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from maru.events.queries import (
    resolve_edition_time_envelope_reference,
    resolve_private_planning_edition_reference,
)
from maru.identity.queries import resolve_active_verified_person_reference

from . import commands as item_commands
from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_HOST_SELF_CAPABILITIES,
    PROGRAMME_MANAGE_HOST_AVAILABILITY_SELF,
    PROGRAMME_MANAGE_HOSTS,
    PROGRAMME_RESPOND_HOST_SELF,
    AuthorizedProgrammeScope,
    ProgrammeAuthorizationDeniedError,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from .catalogs import ProgrammeCommandOperation, ProgrammeReadinessConcern
from .commands import (
    _advance_dependency_versions,
    _advance_item,
    _append_denial_audit,
    _audit_command_errors,
    _ensure_editable,
    _locked_control,
    _locked_item,
    _record_success,
    _replay,
    _require_version,
)
from .host_authorization import authorize_host_retry_scope
from .host_catalogs import (
    HOST_TERMINAL_STATES,
    MAX_HOST_REVISIONS,
    MAX_HOSTS_PER_ITEM,
    ProgrammeHostAvailabilityState,
    ProgrammeHostResponse,
    ProgrammeHostState,
)
from .host_inputs import (
    ProgrammeHostAvailabilityInput,
    ProgrammeHostAvailabilityPeriod,
    ProgrammeHostInvitationInput,
    ProgrammeHostResponseInput,
    _host_version,
    host_availability_periods_digest,
    normalize_host_availability_periods,
)
from .inputs import (
    canonical_digest,
    normalized_reason,
    normalized_source_channel,
    require_uuid,
)
from .models import (
    ProgrammeEditionControl,
    ProgrammeHostAvailabilityWindow,
    ProgrammeHostInvitation,
    ProgrammeHostRelationship,
    ProgrammeHostRevision,
    ProgrammeItem,
)
from .writer_boundary import programme_writer

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

    from django.db.models import QuerySet


@dataclass(frozen=True, slots=True)
class ProgrammeHostCommandResult:
    """Retain only command-result identifiers and historical versions.

    Attributes
    ----------
    receipt_id
        Immutable Programme command receipt.
    item_id
        Exact Programme item affected by this intent.
    host_id
        Retained item/person relationship identifier.
    revision_id
        Immutable host revision created by this intent.
    resulting_item_version
        Historical item version returned by the receipt.
    resulting_host_version
        Historical relationship version, not its current state.
    invitation_sequence
        Invitation sequence represented by the historical revision.
    replayed
        Whether only retained evidence was returned.
    """

    receipt_id: UUID
    item_id: UUID
    host_id: UUID
    revision_id: UUID
    resulting_item_version: int
    resulting_host_version: int
    invitation_sequence: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class _HostCommand:
    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    item_id: UUID
    idempotency_key: UUID
    correlation_id: UUID
    source_channel: str
    operation: ProgrammeCommandOperation
    capability: str

    def checked(self) -> None:
        for field in (
            "actor_id",
            "organization_id",
            "edition_id",
            "item_id",
            "idempotency_key",
            "correlation_id",
        ):
            require_uuid(getattr(self, field), field=field)
        normalized_source_channel(self.source_channel)

    def retry_scope(self, authorizer: ProgrammeAuthorizer) -> None:
        authorize_host_retry_scope(
            actor_id=self.actor_id,
            organization_id=self.organization_id,
            edition_id=self.edition_id,
            capability_code=self.capability,
            authorizer=authorizer,
        )

    def digest(self, intent: dict[str, object], reason: str) -> str:
        return canonical_digest(
            {
                "operation": self.operation.value,
                "item_id": self.item_id,
                "intent": intent,
                "reason": reason,
                "source_channel": self.source_channel,
            }
        )


@dataclass(frozen=True, slots=True)
class _HostWrite:
    command: _HostCommand
    scope: AuthorizedProgrammeScope
    control: ProgrammeEditionControl
    item: ProgrammeItem
    host: ProgrammeHostRelationship | None
    digest: str


def _host_result(
    result: item_commands.ProgrammeCommandResult,
) -> ProgrammeHostCommandResult:
    revision = (
        ProgrammeHostRevision.objects.filter(
            id=result.result_object_id,
            item_id=result.item_id,
        )
        .values_list("host_id", "sequence", "invitation_sequence")
        .first()
    )
    if revision is None:
        raise item_commands.ProgrammeUnavailableError
    return ProgrammeHostCommandResult(
        result.receipt_id,
        result.item_id,
        revision[0],
        result.result_object_id,
        result.resulting_item_version,
        revision[1],
        revision[2],
        result.replayed,
    )


def _lock_host_edition(command: _HostCommand) -> None:
    if (
        resolve_private_planning_edition_reference(
            organization_id=command.organization_id,
            edition_id=command.edition_id,
            lock=True,
        )
        is None
    ):
        raise ProgrammeAuthorizationDeniedError


def _lock_host_people(command: _HostCommand, subject: UUID | None = None) -> None:
    people = {command.actor_id}
    if subject is not None:
        people.add(subject)
    for person_id in sorted(people, key=str):
        person = resolve_active_verified_person_reference(
            account_id=person_id, lock=True
        )
        if person is None and person_id == command.actor_id:
            raise ProgrammeAuthorizationDeniedError
        if (
            person is None
            and command.operation is not ProgrammeCommandOperation.HOST_REMOVE
        ):
            raise item_commands.ProgrammeUnavailableError


def _host_query(
    command: _HostCommand, *, host_id: UUID | None, account_id: UUID | None
) -> QuerySet[ProgrammeHostRelationship]:
    query = ProgrammeHostRelationship.objects.filter(
        organization_id=command.organization_id,
        edition_id=command.edition_id,
        item_id=command.item_id,
    )
    is_self = command.capability in PROGRAMME_HOST_SELF_CAPABILITIES
    if is_self:
        query = query.filter(account_id=command.actor_id)
    if host_id is not None:
        query = query.filter(id=host_id)
    elif account_id is not None:
        query = query.filter(account_id=account_id)
    else:
        raise item_commands.ProgrammeUnavailableError
    subject = query.values_list("account_id", flat=True).first()
    if subject is None and host_id is not None:
        if is_self:
            raise ProgrammeAuthorizationDeniedError
        raise item_commands.ProgrammeUnavailableError
    _lock_host_people(command, subject or account_id)
    return query


def _require_host_history_room(
    host: ProgrammeHostRelationship | None, *, closing: bool
) -> None:
    ceiling = MAX_HOST_REVISIONS + 2 if closing else MAX_HOST_REVISIONS
    if host is not None and host.version >= ceiling:
        raise item_commands.ProgrammeLimitConflictError


@contextmanager
def _host_write(
    command: _HostCommand,
    *,
    digest: str,
    expected_item_version: int,
    expected_host_version: int,
    authorizer: ProgrammeAuthorizer,
    host_id: UUID | None = None,
    account_id: UUID | None = None,
    privacy_exit: bool = False,
) -> Iterator[_HostWrite | item_commands.ProgrammeCommandResult]:
    command.checked()
    try:
        command.retry_scope(authorizer)
        with transaction.atomic(), programme_writer():
            _lock_host_edition(command)
            command.retry_scope(authorizer)
            replay = _replay(
                actor_id=command.actor_id,
                edition_id=command.edition_id,
                idempotency_key=command.idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                _lock_host_people(command)
                command.retry_scope(authorizer)
                yield replay
                return
            authorize_programme_scope(
                actor_id=command.actor_id,
                organization_id=command.organization_id,
                edition_id=command.edition_id,
                capability_code=command.capability,
                authorizer=authorizer,
            )
            query = _host_query(command, host_id=host_id, account_id=account_id)
            scope = authorize_programme_scope(
                actor_id=command.actor_id,
                organization_id=command.organization_id,
                edition_id=command.edition_id,
                capability_code=command.capability,
                authorizer=authorizer,
                lock=True,
            )
            if not privacy_exit:
                _ensure_editable(scope)
            control = _locked_control(
                organization_id=command.organization_id,
                edition_id=command.edition_id,
                required=True,
            )
            item = _locked_item(
                organization_id=command.organization_id,
                edition_id=command.edition_id,
                item_id=command.item_id,
            )
            host = query.select_for_update().first()
            _require_version(
                actual=item.aggregate_version, expected=expected_item_version
            )
            _require_version(
                actual=host.version if host else 0, expected=expected_host_version
            )
            _require_host_history_room(
                host,
                closing=privacy_exit
                or command.operation is ProgrammeCommandOperation.HOST_REMOVE,
            )
            yield _HostWrite(command, scope, control, item, host, digest)
    except ProgrammeAuthorizationDeniedError:
        _append_denial_audit(
            actor_id=command.actor_id,
            organization_id=command.organization_id,
            edition_id=command.edition_id,
            capability_code=command.capability,
            operation=command.operation.value,
            correlation_id=command.correlation_id,
            source_channel=command.source_channel,
        )
        raise


def _finish(
    work: _HostWrite,
    host: ProgrammeHostRelationship,
    *,
    reason: str,
    action: str,
    periods: tuple[ProgrammeHostAvailabilityPeriod, ...],
    invitation: ProgrammeHostInvitationInput | None = None,
) -> ProgrammeHostCommandResult:
    command = work.command
    expected_version = work.item.aggregate_version
    item_version = _advance_item(work.item, actor_id=command.actor_id)
    if work.host is not None:
        host.version += 1
    host.item_version = item_version
    host.last_modified_by_id = command.actor_id
    host.save()
    ProgrammeHostAvailabilityWindow.objects.filter(host=host).delete()
    for period in periods:
        ProgrammeHostAvailabilityWindow.objects.create(
            host=host,
            item=work.item,
            organization_id=command.organization_id,
            edition_id=command.edition_id,
            starts_at=period.starts_at,
            ends_at=period.ends_at,
            kind=period.kind,
        )
    occurred_at = timezone.now()
    if invitation is not None:
        ProgrammeHostInvitation.objects.create(
            host=host,
            item=work.item,
            organization_id=command.organization_id,
            edition_id=command.edition_id,
            sequence=host.invitation_sequence,
            host_version=host.version,
            item_version=item_version,
            role=host.role,
            title=invitation.title,
            briefing=invitation.briefing,
            actor_id=command.actor_id,
            reason=reason,
            occurred_at=occurred_at,
        )
    revision = ProgrammeHostRevision.objects.create(
        host=host,
        item=work.item,
        organization_id=command.organization_id,
        edition_id=command.edition_id,
        sequence=host.version,
        invitation_sequence=host.invitation_sequence,
        item_version=item_version,
        operation=command.operation.value,
        role=host.role,
        state=host.state,
        availability_state=host.availability_state,
        availability_version=host.availability_version,
        period_count=len(periods),
        periods_digest=host_availability_periods_digest(periods),
        actor_id=command.actor_id,
        reason=reason,
        occurred_at=occurred_at,
    )
    concerns = {ProgrammeReadinessConcern.SCHEDULE_AVAILABILITY.value}
    if command.operation is not ProgrammeCommandOperation.HOST_AVAILABILITY:
        concerns.add(ProgrammeReadinessConcern.HOST_CONFIRMATION.value)
    _advance_dependency_versions(
        item=work.item,
        actor_id=command.actor_id,
        resulting_item_version=item_version,
        concerns=frozenset(concerns),
    )
    return _host_result(
        _record_success(
            scope=work.scope,
            control=work.control,
            item=work.item,
            operation=command.operation,
            event_action=action,
            capability_code=command.capability,
            reason=reason,
            idempotency_key=command.idempotency_key,
            request_digest=work.digest,
            correlation_id=command.correlation_id,
            source_channel=command.source_channel,
            result_object_id=revision.id,
            expected_version=expected_version,
            resulting_item_version=item_version,
            resulting_control_version=None,
            changed_fields=("host_availability",)
            if command.operation is ProgrammeCommandOperation.HOST_AVAILABILITY
            else ("host_relationship",),
            occurred_at=occurred_at,
        )
    )


@_audit_command_errors(capability_code=PROGRAMME_MANAGE_HOSTS, operation="host_invite")
def invite_programme_host(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    invitation: ProgrammeHostInvitationInput,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "programme-hosts",
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeHostCommandResult:
    """Invite one exact person without deriving a host from proposal collaboration.

    Parameters
    ----------
    actor_id : UUID
        Authenticated organizer with independent host-management authority.
    organization_id : UUID
        Expected organization owner from trusted routing.
    edition_id : UUID
        Exact edition containing the item.
    item_id : UUID
        Exact accepted or organizer-created Programme item.
    invitation : ProgrammeHostInvitationInput
        Explicit person, role, host-visible copy and optimistic versions.
    reason : str
        Required retained organizer rationale, never exposed to the invitee.
    idempotency_key : UUID
        Actor-owned key in the shared Programme retry namespace.
    correlation_id : UUID
        Evidence correlation, excluded from normalized retry intent.
    source_channel : str, default='programme-hosts'
        Bounded adapter attribution.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real policy or the existing sealed isolated-test substitute.

    Returns
    -------
    ProgrammeHostCommandResult
        Immutable identifiers and versions, including exact retained replay.

    Raises
    ------
    item_commands.ProgrammeLimitConflictError
        If the retained roster or editable history limit is exhausted.
    item_commands.ProgrammeLifecycleConflictError
        If an existing current relationship cannot be reinvited.
    """
    invitation, reason = invitation.normalized(), normalized_reason(reason)
    command = _HostCommand(
        actor_id,
        organization_id,
        edition_id,
        item_id,
        idempotency_key,
        correlation_id,
        source_channel,
        ProgrammeCommandOperation.HOST_INVITE,
        PROGRAMME_MANAGE_HOSTS,
    )
    with _host_write(
        command,
        digest=command.digest(asdict(invitation), reason),
        expected_item_version=invitation.expected_item_version,
        expected_host_version=invitation.expected_host_version,
        account_id=invitation.account_id,
        authorizer=authorizer,
    ) as work:
        if isinstance(work, item_commands.ProgrammeCommandResult):
            return _host_result(work)
        host = work.host
        if host is None:
            if (
                ProgrammeHostRelationship.objects.filter(item=work.item).count()
                >= MAX_HOSTS_PER_ITEM
            ):
                raise item_commands.ProgrammeLimitConflictError
            host = ProgrammeHostRelationship(
                organization_id=organization_id,
                edition_id=edition_id,
                item=work.item,
                account_id=invitation.account_id,
                role=invitation.role,
                state=ProgrammeHostState.INVITED.value,
            )
        else:
            if host.state not in HOST_TERMINAL_STATES:
                raise item_commands.ProgrammeLifecycleConflictError
            if host.version >= MAX_HOST_REVISIONS - 1:
                raise item_commands.ProgrammeLimitConflictError
            host.invitation_sequence += 1
            host.availability_version += 1
            host.role = invitation.role
            host.state = ProgrammeHostState.INVITED.value
            host.availability_state = ProgrammeHostAvailabilityState.UNKNOWN.value
        return _finish(
            work,
            host,
            reason=reason,
            action="invite_host",
            periods=(),
            invitation=invitation,
        )


@_audit_command_errors(
    capability_code=PROGRAMME_RESPOND_HOST_SELF, operation="host_respond"
)
def respond_to_programme_host_invitation(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    response: ProgrammeHostResponseInput,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "programme-hosts",
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeHostCommandResult:
    """Record the exact invitee's response without collecting private explanations.

    Parameters
    ----------
    actor_id : UUID
        Authenticated person who must own the exact relationship.
    organization_id : UUID
        Expected organization owner from trusted routing.
    edition_id : UUID
        Exact edition containing the invitation.
    item_id : UUID
        Exact Programme item, never inferred from a foreign host identifier.
    response : ProgrammeHostResponseInput
        Confirm, decline or withdraw intent with exact current versions.
    idempotency_key : UUID
        Actor-owned Programme retry key.
    correlation_id : UUID
        Evidence correlation, not part of retry intent.
    source_channel : str, default='programme-hosts'
        Bounded adapter attribution.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real policy or sealed isolated-test substitute.

    Returns
    -------
    ProgrammeHostCommandResult
        Minimized historical result, granting no fresh content authority.

    Raises
    ------
    ProgrammeAuthorizationDeniedError
        If the exact personal relationship is unavailable.
    item_commands.ProgrammeLifecycleConflictError
        If the response does not match the current invitation state.
    """
    response = response.normalized()
    reason = {
        "confirm": "Person confirmed their Programme hosting invitation.",
        "decline": "Person declined their Programme hosting invitation.",
        "withdraw": "Person withdrew from their Programme hosting relationship.",
    }[response.response]
    command = _HostCommand(
        actor_id,
        organization_id,
        edition_id,
        item_id,
        idempotency_key,
        correlation_id,
        source_channel,
        ProgrammeCommandOperation.HOST_RESPOND,
        PROGRAMME_RESPOND_HOST_SELF,
    )
    with _host_write(
        command,
        digest=command.digest(asdict(response), reason),
        expected_item_version=response.expected_item_version,
        expected_host_version=response.expected_host_version,
        host_id=response.host_id,
        privacy_exit=response.response != ProgrammeHostResponse.CONFIRM.value,
        authorizer=authorizer,
    ) as work:
        if isinstance(work, item_commands.ProgrammeCommandResult):
            return _host_result(work)
        host = work.host
        if host is None:
            raise ProgrammeAuthorizationDeniedError
        _require_version(
            actual=host.invitation_sequence, expected=response.invitation_sequence
        )
        expected_state = (
            ProgrammeHostState.CONFIRMED.value
            if response.response == "withdraw"
            else ProgrammeHostState.INVITED.value
        )
        if host.state != expected_state:
            raise item_commands.ProgrammeLifecycleConflictError
        host.state = {
            "confirm": "confirmed",
            "decline": "declined",
            "withdraw": "withdrawn",
        }[response.response]
        if response.response != "confirm":
            host.availability_state = ProgrammeHostAvailabilityState.WITHDRAWN.value
            host.availability_version += 1
        return _finish(work, host, reason=reason, action="respond_host", periods=())


@_audit_command_errors(capability_code=PROGRAMME_MANAGE_HOSTS, operation="host_remove")
def remove_programme_host(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    host_id: UUID,
    expected_item_version: int,
    expected_host_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "programme-hosts",
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeHostCommandResult:
    """Remove current hosting with retained rationale, never fabricate a self response.

    Parameters
    ----------
    actor_id : UUID
        Independently authorized host manager.
    organization_id : UUID
        Expected organization owner from trusted routing.
    edition_id : UUID
        Exact edition containing the hosting relationship.
    item_id : UUID
        Exact Programme item.
    host_id : UUID
        Current invited or confirmed relationship to remove.
    expected_item_version : int
        Current optimistic Programme item version.
    expected_host_version : int
        Current optimistic relationship version.
    reason : str
        Required retained organizer rationale.
    idempotency_key : UUID
        Actor-owned Programme retry key.
    correlation_id : UUID
        Evidence correlation, excluded from retry intent.
    source_channel : str, default='programme-hosts'
        Bounded adapter attribution.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real policy or sealed isolated-test substitute.

    Returns
    -------
    ProgrammeHostCommandResult
        Immutable result identifiers and versions.

    Raises
    ------
    item_commands.ProgrammeLifecycleConflictError
        If the relationship is not currently invited or confirmed.
    """
    host_id = require_uuid(host_id, field="host_id")
    expected_item_version = _host_version(
        expected_item_version, field="expected_item_version"
    )
    expected_host_version = _host_version(
        expected_host_version, field="expected_host_version"
    )
    reason = normalized_reason(reason)
    command = _HostCommand(
        actor_id,
        organization_id,
        edition_id,
        item_id,
        idempotency_key,
        correlation_id,
        source_channel,
        ProgrammeCommandOperation.HOST_REMOVE,
        PROGRAMME_MANAGE_HOSTS,
    )
    intent = {
        "host_id": host_id,
        "expected_item_version": expected_item_version,
        "expected_host_version": expected_host_version,
    }
    with _host_write(
        command,
        digest=command.digest(intent, reason),
        expected_item_version=expected_item_version,
        expected_host_version=expected_host_version,
        host_id=host_id,
        authorizer=authorizer,
    ) as work:
        if isinstance(work, item_commands.ProgrammeCommandResult):
            return _host_result(work)
        host = work.host
        if host is None or host.state not in {"invited", "confirmed"}:
            raise item_commands.ProgrammeLifecycleConflictError
        host.state = ProgrammeHostState.REMOVED.value
        host.availability_state = ProgrammeHostAvailabilityState.WITHDRAWN.value
        host.availability_version += 1
        return _finish(work, host, reason=reason, action="remove_host", periods=())


@_audit_command_errors(
    capability_code=PROGRAMME_MANAGE_HOST_AVAILABILITY_SELF,
    operation="host_availability",
)
def replace_programme_host_availability(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    availability: ProgrammeHostAvailabilityInput,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "programme-hosts",
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeHostCommandResult:
    """Replace or withdraw only the confirmed person's exact-item availability.

    Parameters
    ----------
    actor_id : UUID
        Confirmed host who owns the exact relationship and periods.
    organization_id : UUID
        Expected organization owner from trusted routing.
    edition_id : UUID
        Exact edition whose current dates bound sharing.
    item_id : UUID
        Exact hosting purpose; other items and Workforce are untouched.
    availability : ProgrammeHostAvailabilityInput
        Complete replacement state, periods and optimistic versions.
    idempotency_key : UUID
        Actor-owned Programme retry key.
    correlation_id : UUID
        Evidence correlation, excluded from retry intent.
    source_channel : str, default='programme-hosts'
        Bounded adapter attribution.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real policy or sealed isolated-test substitute.

    Returns
    -------
    ProgrammeHostCommandResult
        Immutable result identifiers and minimized historical versions.

    Raises
    ------
    item_commands.ProgrammeLifecycleConflictError
        If the person is not confirmed or availability is already withdrawn.
    item_commands.ProgrammeUnavailableError
        If the current edition time envelope cannot be proved.
    """
    availability = availability.normalized()
    withdrawal = availability.state == ProgrammeHostAvailabilityState.WITHDRAWN.value
    reason = f"Person set their Programme host availability to {availability.state}."
    command = _HostCommand(
        actor_id,
        organization_id,
        edition_id,
        item_id,
        idempotency_key,
        correlation_id,
        source_channel,
        ProgrammeCommandOperation.HOST_AVAILABILITY,
        PROGRAMME_MANAGE_HOST_AVAILABILITY_SELF,
    )
    with _host_write(
        command,
        digest=command.digest(asdict(availability), reason),
        expected_item_version=availability.expected_item_version,
        expected_host_version=availability.expected_host_version,
        host_id=availability.host_id,
        privacy_exit=withdrawal,
        authorizer=authorizer,
    ) as work:
        if isinstance(work, item_commands.ProgrammeCommandResult):
            return _host_result(work)
        host = work.host
        if host is None or host.state != ProgrammeHostState.CONFIRMED.value:
            raise item_commands.ProgrammeLifecycleConflictError
        if (
            withdrawal
            and host.availability_state
            == ProgrammeHostAvailabilityState.WITHDRAWN.value
        ):
            raise item_commands.ProgrammeLifecycleConflictError
        if not withdrawal:
            envelope = resolve_edition_time_envelope_reference(
                organization_id=organization_id,
                edition_id=edition_id,
                lock=True,
            )
            if envelope is None:
                raise item_commands.ProgrammeUnavailableError
            normalize_host_availability_periods(
                availability.periods,
                edition_starts_at=envelope.starts_at,
                edition_ends_at=envelope.ends_at,
            )
        host.availability_state = availability.state
        host.availability_version += 1
        return _finish(
            work,
            host,
            reason=reason,
            action="change_host_availability",
            periods=availability.periods,
        )


__all__ = [
    "ProgrammeHostCommandResult",
    "invite_programme_host",
    "remove_programme_host",
    "replace_programme_host_availability",
    "respond_to_programme_host_invitation",
]
