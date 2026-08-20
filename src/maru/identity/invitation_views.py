"""Server-rendered Page 10 adapters for platform account invitations."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast
from urllib.parse import urlencode
from uuid import UUID, uuid4

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from maru.identity.invitation_audit import append_platform_account_read_audit
from maru.identity.invitation_commands import (
    InvitationAuthorizationDeniedError,
    InvitationChallengeInvalidError,
    InvitationDependencyUnavailableError,
    InvitationIdentityConflictError,
    InvitationRetryConflictError,
    InvitationStateConflictError,
    InvitationUnavailableError,
    InvitationVersionConflictError,
    accept_platform_account_invitation,
    create_platform_account_invitation,
    reissue_platform_account_invitation,
    revoke_platform_account_invitation,
)
from maru.identity.invitation_delivery_reconciliation import (
    resolve_platform_identity_delivery_as_delivered,
    resolve_platform_identity_delivery_for_retry,
)
from maru.identity.invitation_forms import (
    AccountInvitationAcceptanceForm,
    PlatformAccountInventoryFilterForm,
    PlatformAccountInvitationActionForm,
    PlatformAccountInvitationForm,
    PlatformIdentityDeliveryDeliveredForm,
    PlatformIdentityDeliveryRetryForm,
)
from maru.identity.invitation_queries import (
    AccountInventoryPage,
    AccountInvitationDetail,
    PlatformAccountInventoryCursorStaleError,
    PlatformAccountInventoryDeniedError,
    PlatformAccountInventoryInputError,
    PlatformAccountInventoryLimitExceededError,
    PlatformAccountInventoryUnavailableError,
    PlatformAccountInvitationNotFoundError,
    load_platform_account_inventory,
    load_platform_account_invitation_detail,
)
from maru.identity.models import Account, PlatformIdentityDelivery
from maru.identity.services import request_fingerprint, require_recent_step_up

logger = logging.getLogger(__name__)

_ADMIN_TEMPLATE_CONTEXT: dict[str, object] = {
    "baseline_admin_parent_template": "admin/base_site.html",
    "baseline_use_admin_shell": True,
    "has_permission": True,
}


def _request_id(request: HttpRequest) -> UUID:
    candidate = getattr(request, "correlation_id", None)
    if isinstance(candidate, str):
        try:
            return UUID(candidate)
        except ValueError:
            pass
    return uuid4()


def _private_no_store(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _step_up_redirect(
    request: HttpRequest,
    *,
    return_to: str | None = None,
) -> HttpResponse:
    """Send a privileged browser action to the shared same-shell step-up.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    return_to : str | None, default=None
        The return to evaluated while step up redirect.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.
    """
    step_up_url = reverse("account-step-up")
    return _private_no_store(
        redirect(f"{step_up_url}?{urlencode({'next': return_to or request.path})}")
    )


def _require_privileged_step_up(
    request: HttpRequest,
    *,
    actor: Account,
    always: bool = False,
    return_to: str | None = None,
) -> HttpResponse | None:
    if not always and not settings.REQUIRE_PRIVILEGED_STEP_UP:
        return None
    try:
        require_recent_step_up(account=actor, request=request)
    except ValidationError:
        return _step_up_redirect(request, return_to=return_to)
    return None


def _admin_response(
    request: HttpRequest,
    template_name: str,
    context: dict[str, Any],
    *,
    page_id: str,
    page_class: str = "",
    status: int = 200,
) -> HttpResponse:
    template_context = admin.site.each_context(request)
    template_context.update(_ADMIN_TEMPLATE_CONTEXT)
    template_context.update(
        {
            "baseline_page_id": page_id,
            "baseline_page_class": page_class,
            **context,
        }
    )
    return _private_no_store(
        TemplateResponse(request, template_name, template_context, status=status)
    )


def _public_response(
    request: HttpRequest,
    *,
    form: AccountInvitationAcceptanceForm,
    status: int = 200,
    request_invalid: bool = False,
) -> HttpResponse:
    return _private_no_store(
        TemplateResponse(
            request,
            "identity/account_invitation_accept.html",
            {
                "form": form,
                "acceptance_request_invalid": request_invalid,
            },
            status=status,
        )
    )


def _active_platform_administrator(request: HttpRequest) -> Account:
    """Resolve fresh platform authority before parsing a protected body.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    Account
        The resolved Account for active platform administrator.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    if not isinstance(request.user, Account) or not request.user.is_authenticated:
        raise PermissionDenied
    actor = (
        Account.objects.filter(
            id=request.user.id,
            is_active=True,
            is_staff=True,
            is_superuser=True,
            account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
        )
        .order_by("id")
        .first()
    )
    if actor is None:
        raise PermissionDenied
    return actor


def _safe_dependency_log(request: HttpRequest, *, operation: str) -> None:
    logger.error(
        "Platform account invitation dependency failed",
        extra={
            "correlation_id": str(_request_id(request)),
            "operation": operation,
        },
    )


def _add_domain_validation_errors(
    form: forms.BaseForm,
    error: ValidationError,
    *,
    allowed_fields: frozenset[str],
) -> bool:
    """Map only allowlisted, value-free validation messages to the form.

    Parameters
    ----------
    form : forms.BaseForm
        The form evaluated while add domain validation errors.
    error : ValidationError
        The error evaluated while add domain validation errors.
    allowed_fields : frozenset[str]
        The closed set of object keys accepted by this boundary.

    Returns
    -------
    bool
        `True` when Map only allowlisted, value-free validation messages to the
        form; otherwise `False`.
    """
    if hasattr(error, "message_dict"):
        for field_name, field_errors in error.message_dict.items():
            if field_name not in allowed_fields or field_name not in form.fields:
                return False
            target: str | None = field_name
            if isinstance(form.fields[field_name].widget, forms.HiddenInput):
                target = None
            for message in field_errors:
                form.add_error(target, message)
        return True
    target = "new_password" if "new_password" in allowed_fields else None
    for field_error in error.error_list:
        form.add_error(target, field_error)
    return True


def _inventory_next_url(
    *,
    page: AccountInventoryPage,
    cleaned: dict[str, Any],
) -> str:
    if page.next_cursor is None:
        return ""
    query: list[tuple[str, str]] = []
    for key in ("search", "search_mode", "kind", "state"):
        value = cleaned.get(key)
        if value not in (None, ""):
            query.append((key, str(value)))
    query.append(("cursor", page.next_cursor))
    return f"{reverse('platform-account-inventory')}?{urlencode(query)}"


def _inventory_error_response(
    request: HttpRequest,
    *,
    form: PlatformAccountInventoryFilterForm,
    state: str,
    status: int,
) -> HttpResponse:
    return _admin_response(
        request,
        "identity/platform_account_inventory.html",
        {
            "filter_form": form,
            "inventory": None,
            "account_inventory_state": state,
            "next_page_url": "",
        },
        page_id="platform-account-inventory",
        status=status,
    )


@never_cache
@login_required(login_url="staff-login")
@require_GET
def platform_account_inventory(request: HttpRequest) -> HttpResponse:
    """Render one audited, bounded page of platform identity records.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    actor = _active_platform_administrator(request)
    form = PlatformAccountInventoryFilterForm(
        request.GET or None,
        initial={"search_mode": "prefix"},
    )
    if form.is_bound and not form.is_valid():
        return _inventory_error_response(
            request,
            form=form,
            state="invalid",
            status=400,
        )
    cleaned = (
        form.cleaned_data
        if form.is_bound
        else {
            "search": None,
            "search_mode": "prefix",
            "kind": None,
            "state": None,
            "cursor": None,
        }
    )
    correlation_id = _request_id(request)
    try:
        inventory = load_platform_account_inventory(
            actor=actor,
            audit_hook=append_platform_account_read_audit,
            correlation_id=correlation_id,
            source_channel="web",
            search=cleaned.get("search"),
            search_mode=cleaned.get("search_mode", "prefix"),
            kind=cleaned.get("kind"),
            state=cleaned.get("state"),
            cursor=cleaned.get("cursor"),
        )
    except PlatformAccountInventoryDeniedError as error:
        raise PermissionDenied from error
    except PlatformAccountInventoryInputError as error:
        target = error.field_name if error.field_name in form.fields else None
        form.add_error(target, "Review the account inventory filters and try again.")
        return _inventory_error_response(
            request,
            form=form,
            state="invalid",
            status=400,
        )
    except PlatformAccountInventoryCursorStaleError:
        return _inventory_error_response(
            request,
            form=form,
            state="stale",
            status=409,
        )
    except PlatformAccountInventoryLimitExceededError:
        return _inventory_error_response(
            request,
            form=form,
            state="limit_exceeded",
            status=409,
        )
    except PlatformAccountInventoryUnavailableError:
        _safe_dependency_log(request, operation="account_inventory_read")
        return _inventory_error_response(
            request,
            form=form,
            state="unavailable",
            status=503,
        )
    return _admin_response(
        request,
        "identity/platform_account_inventory.html",
        {
            "filter_form": form,
            "inventory": inventory,
            "account_inventory_state": "ready",
            "next_page_url": _inventory_next_url(
                page=inventory,
                cleaned=cleaned,
            ),
        },
        page_id="platform-account-inventory",
    )


def _invitation_creation_response(
    request: HttpRequest,
    *,
    form: PlatformAccountInvitationForm,
    status: int = 200,
    action_error: str = "",
    request_invalid: bool = False,
) -> HttpResponse:
    return _admin_response(
        request,
        "identity/platform_account_invite.html",
        {
            "form": form,
            "action_error": action_error,
            "invitation_request_invalid": request_invalid,
        },
        page_id="platform-account-invite",
        page_class="baseline-page--form",
        status=status,
    )


@never_cache
@login_required(login_url="staff-login")
@require_http_methods(["GET", "POST"])
def platform_account_invite(request: HttpRequest) -> HttpResponse:  # noqa: PLR0911
    """Reserve an inactive person account and enqueue recipient-owned acceptance.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    actor = _active_platform_administrator(request)
    if request.method == "POST":
        step_up_response = _require_privileged_step_up(
            request,
            actor=actor,
            return_to=reverse("platform-account-invite"),
        )
        if step_up_response is not None:
            return step_up_response
    if request.GET:
        return _invitation_creation_response(
            request,
            form=PlatformAccountInvitationForm(),
            status=400,
            request_invalid=True,
        )
    form = PlatformAccountInvitationForm(
        request.POST if request.method == "POST" else None
    )
    if request.method != "POST" or not form.is_valid():
        return _invitation_creation_response(
            request,
            form=form,
            status=400 if request.method == "POST" else 200,
        )
    correlation_id = _request_id(request)
    try:
        result = create_platform_account_invitation(
            actor=actor,
            email=form.cleaned_data["email"],
            login_handle=form.cleaned_data["login_handle"],
            display_name=form.cleaned_data["display_name"],
            preferred_language=form.cleaned_data["preferred_language"],
            reason=form.cleaned_data["reason"],
            expected_version=form.cleaned_data["expected_version"],
            retry_key=form.cleaned_data["retry_key"],
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="web",
        )
    except InvitationAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except InvitationIdentityConflictError:
        form.add_error(
            None,
            "The invitation could not be created with those account details. "
            "No identity was changed and Maru cannot disclose which detail is "
            "unavailable.",
        )
        return _invitation_creation_response(
            request,
            form=form,
            status=409,
        )
    except (
        InvitationRetryConflictError,
        InvitationStateConflictError,
        InvitationVersionConflictError,
    ):
        form.add_error(
            None,
            "This form no longer matches the current account inventory. Reload "
            "the invitation page before trying again.",
        )
        return _invitation_creation_response(
            request,
            form=form,
            status=409,
        )
    except ValidationError as error:
        validation_fields = frozenset(getattr(error, "message_dict", {}).keys())
        if validation_fields & {"email", "login_handle"}:
            form.add_error(
                None,
                "The invitation could not be created with those account details. "
                "No identity was changed and Maru cannot disclose which detail "
                "is unavailable.",
            )
            return _invitation_creation_response(
                request,
                form=form,
                status=409,
            )
        mapped = _add_domain_validation_errors(
            form,
            error,
            allowed_fields=frozenset(
                {
                    "email",
                    "login_handle",
                    "display_name",
                    "preferred_language",
                    "reason",
                }
            ),
        )
        if mapped:
            return _invitation_creation_response(
                request,
                form=form,
                status=400,
            )
        _safe_dependency_log(request, operation="account_invitation_create")
        form.add_error(None, "The invitation could not be created safely.")
        return _invitation_creation_response(
            request,
            form=form,
            status=503,
        )
    except (InvitationDependencyUnavailableError, DatabaseError):
        _safe_dependency_log(request, operation="account_invitation_create")
        form.add_error(
            None,
            "The invitation could not be queued. Try again after the identity "
            "delivery dependency is available.",
        )
        return _invitation_creation_response(
            request,
            form=form,
            status=503,
        )
    messages.success(
        request,
        (
            "The existing invitation result was recovered safely."
            if result.replayed
            else (
                "The inactive person account was reserved and its invitation "
                "was queued."
            )
        ),
    )
    return _private_no_store(
        redirect(
            "platform-account-invitation-detail",
            invitation_id=result.invitation.id,
        )
    )


def _detail_error_response(
    request: HttpRequest,
    *,
    state: str,
    status: int,
) -> HttpResponse:
    return _admin_response(
        request,
        "identity/platform_account_invitation_detail.html",
        {
            "invitation": None,
            "invitation_detail_state": state,
            "reissue_form": None,
            "revoke_form": None,
            "delivery_delivered_form": None,
            "delivery_retry_form": None,
            "active_action": "",
            "action_error": "",
            "reload_required": False,
        },
        page_id="platform-account-invitation-detail",
        status=status,
    )


def _load_invitation_detail(
    request: HttpRequest,
    *,
    actor: Account,
    invitation_id: UUID,
) -> AccountInvitationDetail:
    return load_platform_account_invitation_detail(
        actor=actor,
        invitation_id=invitation_id,
        audit_hook=append_platform_account_read_audit,
        correlation_id=_request_id(request),
        source_channel="web",
    )


def _render_invitation_detail(
    request: HttpRequest,
    *,
    actor: Account,
    invitation_id: UUID,
    reissue_form: PlatformAccountInvitationActionForm | None = None,
    revoke_form: PlatformAccountInvitationActionForm | None = None,
    delivery_delivered_form: PlatformIdentityDeliveryDeliveredForm | None = None,
    delivery_retry_form: PlatformIdentityDeliveryRetryForm | None = None,
    active_action: str = "",
    action_error: str = "",
    reload_required: bool = False,
    status: int = 200,
) -> HttpResponse:
    try:
        detail = _load_invitation_detail(
            request,
            actor=actor,
            invitation_id=invitation_id,
        )
    except PlatformAccountInventoryDeniedError as error:
        raise PermissionDenied from error
    except PlatformAccountInvitationNotFoundError as error:
        raise Http404 from error
    except PlatformAccountInventoryLimitExceededError:
        return _detail_error_response(
            request,
            state="limit_exceeded",
            status=409,
        )
    except (
        PlatformAccountInventoryInputError,
        PlatformAccountInventoryCursorStaleError,
    ):
        return _detail_error_response(request, state="invalid", status=400)
    except PlatformAccountInventoryUnavailableError:
        _safe_dependency_log(request, operation="account_invitation_read")
        return _detail_error_response(
            request,
            state="unavailable",
            status=503,
        )

    if reissue_form is None:
        reissue_form = PlatformAccountInvitationActionForm(
            expected_version=detail.invitation_version,
            auto_id="id_invitation_reissue_%s",
        )
    if revoke_form is None:
        revoke_form = PlatformAccountInvitationActionForm(
            expected_version=detail.invitation_version,
            auto_id="id_invitation_revoke_%s",
        )
    delivery = detail.current_delivery
    if (
        delivery is not None
        and delivery.reconciliation_state
        == PlatformIdentityDelivery.ReconciliationState.REQUIRED
    ):
        if delivery_delivered_form is None:
            delivery_delivered_form = PlatformIdentityDeliveryDeliveredForm(
                expected_version=delivery.aggregate_version,
            )
        if delivery_retry_form is None:
            delivery_retry_form = PlatformIdentityDeliveryRetryForm(
                expected_version=delivery.aggregate_version,
            )
    return _admin_response(
        request,
        "identity/platform_account_invitation_detail.html",
        {
            "invitation": detail,
            "invitation_detail_state": "ready",
            "reissue_form": reissue_form,
            "revoke_form": revoke_form,
            "delivery_delivered_form": delivery_delivered_form,
            "delivery_retry_form": delivery_retry_form,
            "active_action": active_action,
            "action_error": action_error,
            "reload_required": reload_required,
        },
        page_id="platform-account-invitation-detail",
        page_class="baseline-page--form",
        status=status,
    )


@never_cache
@login_required(login_url="staff-login")
@require_GET
def platform_account_invitation_detail(
    request: HttpRequest,
    invitation_id: UUID,
) -> HttpResponse:
    """Return platform account invitation detail.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    invitation_id : UUID
        The identifier of the invitation.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    actor = _active_platform_administrator(request)
    if request.GET:
        return _detail_error_response(request, state="invalid", status=400)
    return _render_invitation_detail(
        request,
        actor=actor,
        invitation_id=invitation_id,
    )


def _action_error_message(error: Exception) -> tuple[str, bool]:
    if isinstance(error, InvitationVersionConflictError):
        return (
            "The invitation changed after this form was opened. Reload the "
            "current invitation before trying again.",
            True,
        )
    if isinstance(error, InvitationRetryConflictError):
        return (
            "This browser retry identifier was already used with different "
            "values. Reload the current invitation before trying again.",
            True,
        )
    if isinstance(error, InvitationStateConflictError):
        return (
            "The invitation's current state does not permit this action. Reload "
            "the current invitation to review what changed.",
            True,
        )
    return ("The invitation could not be changed safely.", False)


def _render_action_form_failure(
    request: HttpRequest,
    *,
    actor: Account,
    invitation_id: UUID,
    operation: str,
    form: PlatformAccountInvitationActionForm,
    action_error: str,
    status: int,
    reload_required: bool = False,
) -> HttpResponse:
    if operation == "reissue":
        return _render_invitation_detail(
            request,
            actor=actor,
            invitation_id=invitation_id,
            reissue_form=form,
            active_action=operation,
            action_error=action_error,
            reload_required=reload_required,
            status=status,
        )
    return _render_invitation_detail(
        request,
        actor=actor,
        invitation_id=invitation_id,
        revoke_form=form,
        active_action=operation,
        action_error=action_error,
        reload_required=reload_required,
        status=status,
    )


InvitationActionCommand = Callable[..., object]


def _invitation_action(  # noqa: PLR0911
    request: HttpRequest,
    *,
    invitation_id: UUID,
    operation: str,
    command: InvitationActionCommand,
) -> HttpResponse:
    actor = _active_platform_administrator(request)
    step_up_response = _require_privileged_step_up(
        request,
        actor=actor,
        return_to=reverse(
            "platform-account-invitation-detail",
            kwargs={"invitation_id": invitation_id},
        ),
    )
    if step_up_response is not None:
        return step_up_response
    if request.GET:
        return _detail_error_response(request, state="invalid", status=400)
    form = PlatformAccountInvitationActionForm(
        request.POST,
        expected_version=1,
        auto_id=f"id_invitation_{operation}_%s",
    )
    if not form.is_valid():
        return _render_action_form_failure(
            request,
            actor=actor,
            invitation_id=invitation_id,
            operation=operation,
            form=form,
            action_error="Review the highlighted values. No invitation was changed.",
            status=400,
        )
    correlation_id = _request_id(request)
    try:
        result = command(
            actor=actor,
            invitation_id=invitation_id,
            expected_version=form.cleaned_data["expected_version"],
            reason=form.cleaned_data["reason"],
            retry_key=form.cleaned_data["retry_key"],
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="web",
        )
    except InvitationAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except InvitationUnavailableError as error:
        raise Http404 from error
    except (
        InvitationVersionConflictError,
        InvitationRetryConflictError,
        InvitationStateConflictError,
    ) as error:
        message, reload_required = _action_error_message(error)
        form.add_error(None, message)
        return _render_action_form_failure(
            request,
            actor=actor,
            invitation_id=invitation_id,
            operation=operation,
            form=form,
            action_error=message,
            status=409,
            reload_required=reload_required,
        )
    except ValidationError as error:
        if _add_domain_validation_errors(
            form,
            error,
            allowed_fields=frozenset({"reason"}),
        ):
            return _render_action_form_failure(
                request,
                actor=actor,
                invitation_id=invitation_id,
                operation=operation,
                form=form,
                action_error=(
                    "Review the highlighted values. No invitation was changed."
                ),
                status=400,
            )
        _safe_dependency_log(
            request,
            operation=f"account_invitation_{operation}",
        )
        return _detail_error_response(
            request,
            state="unavailable",
            status=503,
        )
    except (InvitationDependencyUnavailableError, DatabaseError):
        _safe_dependency_log(
            request,
            operation=f"account_invitation_{operation}",
        )
        return _detail_error_response(
            request,
            state="unavailable",
            status=503,
        )
    replayed = bool(getattr(result, "replayed", False))
    messages.success(
        request,
        (
            "The existing invitation result was recovered safely."
            if replayed
            else (
                "A fresh invitation was queued and the previous code was invalidated."
                if operation == "reissue"
                else "The invitation was revoked and its code was invalidated."
            )
        ),
    )
    return _private_no_store(
        redirect(
            "platform-account-invitation-detail",
            invitation_id=invitation_id,
        )
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def reissue_platform_account_invitation_view(
    request: HttpRequest,
    invitation_id: UUID,
) -> HttpResponse:
    """Return reissue platform account invitation view.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    invitation_id : UUID
        The identifier of the invitation.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    return _invitation_action(
        request,
        invitation_id=invitation_id,
        operation="reissue",
        command=reissue_platform_account_invitation,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def revoke_platform_account_invitation_view(
    request: HttpRequest,
    invitation_id: UUID,
) -> HttpResponse:
    """Revoke platform account invitation view.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    invitation_id : UUID
        The identifier of the invitation.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    return _invitation_action(
        request,
        invitation_id=invitation_id,
        operation="revoke",
        command=revoke_platform_account_invitation,
    )


def _delivery_reconciliation_preflight(
    request: HttpRequest,
    *,
    actor: Account,
    invitation_id: UUID,
    delivery_id: UUID,
) -> AccountInvitationDetail | HttpResponse:
    """Authorize and bind both route locators without reading the POST body.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    actor : Account
        The authenticated account authorizing the operation.
    invitation_id : UUID
        The invitation identifier within the requested scope.
    delivery_id : UUID
        The delivery identifier within the requested scope.

    Returns
    -------
    AccountInvitationDetail | HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    step_up_response = _require_privileged_step_up(
        request,
        actor=actor,
        always=True,
        return_to=reverse(
            "platform-account-invitation-detail",
            kwargs={"invitation_id": invitation_id},
        ),
    )
    if step_up_response is not None:
        return step_up_response
    try:
        detail = _load_invitation_detail(
            request,
            actor=actor,
            invitation_id=invitation_id,
        )
    except PlatformAccountInventoryDeniedError as error:
        raise PermissionDenied from error
    except PlatformAccountInvitationNotFoundError as error:
        raise Http404 from error
    except PlatformAccountInventoryLimitExceededError:
        return _detail_error_response(
            request,
            state="limit_exceeded",
            status=409,
        )
    except (
        PlatformAccountInventoryInputError,
        PlatformAccountInventoryCursorStaleError,
    ):
        return _detail_error_response(request, state="invalid", status=400)
    except PlatformAccountInventoryUnavailableError:
        _safe_dependency_log(request, operation="delivery_reconciliation_preflight")
        return _detail_error_response(
            request,
            state="unavailable",
            status=503,
        )
    if (
        detail.current_delivery is None
        or detail.current_delivery.delivery_id != delivery_id
    ):
        raise Http404
    return detail


def _delivery_reconciliation_error(error: Exception) -> tuple[str, bool]:
    if isinstance(error, InvitationVersionConflictError):
        return (
            "The delivery changed after this form was opened. Reload the "
            "current invitation before trying again.",
            True,
        )
    if isinstance(error, InvitationRetryConflictError):
        return (
            "This browser retry identifier was already used with different "
            "values. Reload the current invitation before trying again.",
            True,
        )
    if isinstance(error, InvitationStateConflictError):
        return (
            "The delivery's current state does not permit this action. Reload "
            "the invitation to review what changed.",
            True,
        )
    return ("The delivery could not be reconciled safely.", False)


def _render_delivery_reconciliation_failure(
    request: HttpRequest,
    *,
    actor: Account,
    invitation_id: UUID,
    operation: str,
    form: PlatformIdentityDeliveryDeliveredForm | PlatformIdentityDeliveryRetryForm,
    action_error: str,
    status: int,
    reload_required: bool = False,
) -> HttpResponse:
    if operation == "delivery_delivered":
        return _render_invitation_detail(
            request,
            actor=actor,
            invitation_id=invitation_id,
            delivery_delivered_form=cast(
                "PlatformIdentityDeliveryDeliveredForm",
                form,
            ),
            active_action=operation,
            action_error=action_error,
            reload_required=reload_required,
            status=status,
        )
    return _render_invitation_detail(
        request,
        actor=actor,
        invitation_id=invitation_id,
        delivery_retry_form=form,
        active_action=operation,
        action_error=action_error,
        reload_required=reload_required,
        status=status,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def resolve_platform_identity_delivery_as_delivered_view(  # noqa: PLR0911
    request: HttpRequest,
    invitation_id: UUID,
    delivery_id: UUID,
) -> HttpResponse:
    """Record an externally confirmed provider acceptance through Page 10.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    invitation_id : UUID
        The invitation identifier within the requested scope.
    delivery_id : UUID
        The delivery identifier within the requested scope.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    actor = _active_platform_administrator(request)
    preflight = _delivery_reconciliation_preflight(
        request,
        actor=actor,
        invitation_id=invitation_id,
        delivery_id=delivery_id,
    )
    if isinstance(preflight, HttpResponse):
        return preflight
    current_delivery = preflight.current_delivery
    if current_delivery is None:  # Defensive: preflight already binds it.
        raise Http404
    form = PlatformIdentityDeliveryDeliveredForm(
        request.POST,
        expected_version=current_delivery.aggregate_version,
    )
    if not form.is_valid():
        return _render_delivery_reconciliation_failure(
            request,
            actor=actor,
            invitation_id=invitation_id,
            operation="delivery_delivered",
            form=form,
            action_error="Review the highlighted values. No delivery was changed.",
            status=400,
        )
    correlation_id = _request_id(request)
    try:
        result = resolve_platform_identity_delivery_as_delivered(
            actor=actor,
            delivery_id=delivery_id,
            expected_version=form.cleaned_data["expected_version"],
            provider_reference=form.cleaned_data["provider_reference"],
            reason=form.cleaned_data["reason"],
            retry_key=form.cleaned_data["retry_key"],
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="web",
        )
    except InvitationAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except InvitationUnavailableError as error:
        raise Http404 from error
    except (
        InvitationVersionConflictError,
        InvitationRetryConflictError,
        InvitationStateConflictError,
    ) as error:
        message, reload_required = _delivery_reconciliation_error(error)
        form.add_error(None, message)
        return _render_delivery_reconciliation_failure(
            request,
            actor=actor,
            invitation_id=invitation_id,
            operation="delivery_delivered",
            form=form,
            action_error=message,
            status=409,
            reload_required=reload_required,
        )
    except ValidationError as error:
        if _add_domain_validation_errors(
            form,
            error,
            allowed_fields=frozenset({"provider_reference", "reason"}),
        ):
            return _render_delivery_reconciliation_failure(
                request,
                actor=actor,
                invitation_id=invitation_id,
                operation="delivery_delivered",
                form=form,
                action_error=(
                    "Review the highlighted values. No delivery was changed."
                ),
                status=400,
            )
        _safe_dependency_log(request, operation="delivery_resolve_delivered")
        return _detail_error_response(request, state="unavailable", status=503)
    except (InvitationDependencyUnavailableError, DatabaseError):
        _safe_dependency_log(request, operation="delivery_resolve_delivered")
        return _detail_error_response(request, state="unavailable", status=503)
    messages.success(
        request,
        (
            "The existing delivery reconciliation result was recovered safely."
            if result.replayed
            else "The confirmed delivery was recorded."
        ),
    )
    return _private_no_store(
        redirect(
            "platform-account-invitation-detail",
            invitation_id=invitation_id,
        )
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def resolve_platform_identity_delivery_for_retry_view(  # noqa: PLR0911
    request: HttpRequest,
    invitation_id: UUID,
    delivery_id: UUID,
) -> HttpResponse:
    """Schedule one bounded retry after an operator rules out acceptance.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    invitation_id : UUID
        The invitation identifier within the requested scope.
    delivery_id : UUID
        The delivery identifier within the requested scope.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    actor = _active_platform_administrator(request)
    preflight = _delivery_reconciliation_preflight(
        request,
        actor=actor,
        invitation_id=invitation_id,
        delivery_id=delivery_id,
    )
    if isinstance(preflight, HttpResponse):
        return preflight
    current_delivery = preflight.current_delivery
    if current_delivery is None:  # Defensive: preflight already binds it.
        raise Http404
    form = PlatformIdentityDeliveryRetryForm(
        request.POST,
        expected_version=current_delivery.aggregate_version,
    )
    if not form.is_valid():
        return _render_delivery_reconciliation_failure(
            request,
            actor=actor,
            invitation_id=invitation_id,
            operation="delivery_retry",
            form=form,
            action_error="Review the highlighted values. No delivery was changed.",
            status=400,
        )
    correlation_id = _request_id(request)
    try:
        result = resolve_platform_identity_delivery_for_retry(
            actor=actor,
            delivery_id=delivery_id,
            expected_version=form.cleaned_data["expected_version"],
            reason=form.cleaned_data["reason"],
            retry_key=form.cleaned_data["retry_key"],
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="web",
        )
    except InvitationAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except InvitationUnavailableError as error:
        raise Http404 from error
    except (
        InvitationVersionConflictError,
        InvitationRetryConflictError,
        InvitationStateConflictError,
    ) as error:
        message, reload_required = _delivery_reconciliation_error(error)
        form.add_error(None, message)
        return _render_delivery_reconciliation_failure(
            request,
            actor=actor,
            invitation_id=invitation_id,
            operation="delivery_retry",
            form=form,
            action_error=message,
            status=409,
            reload_required=reload_required,
        )
    except ValidationError as error:
        if _add_domain_validation_errors(
            form,
            error,
            allowed_fields=frozenset({"reason"}),
        ):
            return _render_delivery_reconciliation_failure(
                request,
                actor=actor,
                invitation_id=invitation_id,
                operation="delivery_retry",
                form=form,
                action_error=(
                    "Review the highlighted values. No delivery was changed."
                ),
                status=400,
            )
        _safe_dependency_log(request, operation="delivery_resolve_retry")
        return _detail_error_response(request, state="unavailable", status=503)
    except (InvitationDependencyUnavailableError, DatabaseError):
        _safe_dependency_log(request, operation="delivery_resolve_retry")
        return _detail_error_response(request, state="unavailable", status=503)
    messages.success(
        request,
        (
            "The existing delivery reconciliation result was recovered safely."
            if result.replayed
            else "One controlled delivery retry was scheduled."
        ),
    )
    return _private_no_store(
        redirect(
            "platform-account-invitation-detail",
            invitation_id=invitation_id,
        )
    )


@never_cache
@require_http_methods(["GET", "POST"])
def accept_platform_account_invitation_view(  # noqa: PLR0911
    request: HttpRequest,
) -> HttpResponse:
    """Consume a fragment-carried/manual code without reflecting any secret.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.
    """
    if request.GET:
        return _public_response(
            request,
            form=AccountInvitationAcceptanceForm(),
            status=400,
            request_invalid=True,
        )
    form = AccountInvitationAcceptanceForm(
        request.POST if request.method == "POST" else None
    )
    if request.method != "POST" or not form.is_valid():
        return _public_response(
            request,
            form=form,
            status=400 if request.method == "POST" else 200,
        )
    correlation_id = _request_id(request)
    try:
        accept_platform_account_invitation(
            raw_token=cast("str", form.cleaned_data["raw_token"]),
            new_password=cast("str", form.cleaned_data["new_password"]),
            retry_key=form.cleaned_data["retry_key"],
            correlation_id=correlation_id,
            request_fingerprint=request_fingerprint(request),
            request_id=correlation_id,
            source_channel="web",
        )
    except (
        InvitationChallengeInvalidError,
        InvitationStateConflictError,
        InvitationUnavailableError,
    ):
        form.add_error(
            "raw_token",
            "This invitation code is invalid or has expired.",
        )
        return _public_response(request, form=form, status=400)
    except InvitationRetryConflictError:
        form.add_error(
            None,
            "This acceptance attempt could not be completed. Reload this clean "
            "page, paste the invitation code again, and retry.",
        )
        return _public_response(request, form=form, status=409)
    except ValidationError as error:
        if _add_domain_validation_errors(
            form,
            error,
            allowed_fields=frozenset({"new_password"}),
        ):
            return _public_response(request, form=form, status=400)
        _safe_dependency_log(request, operation="account_invitation_accept")
        form.add_error(
            None,
            "The invitation could not be accepted safely. Try again later.",
        )
        return _public_response(request, form=form, status=503)
    except (InvitationDependencyUnavailableError, DatabaseError):
        _safe_dependency_log(request, operation="account_invitation_accept")
        form.add_error(
            None,
            "The invitation could not be accepted safely. Try again later.",
        )
        return _public_response(request, form=form, status=503)
    messages.success(
        request,
        "Your account is active. Sign in with the password you just chose.",
    )
    return _private_no_store(redirect("staff-login"))


__all__ = [
    "accept_platform_account_invitation_view",
    "platform_account_inventory",
    "platform_account_invitation_detail",
    "platform_account_invite",
    "reissue_platform_account_invitation_view",
    "revoke_platform_account_invitation_view",
]
