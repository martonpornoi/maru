"""Same-shell browser adapter for a recent privileged-session check."""

from __future__ import annotations

from typing import Any

from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from maru.identity.models import Account
from maru.identity.services import complete_step_up
from maru.identity.step_up_forms import AccountStepUpForm


def _active_account(request: HttpRequest) -> Account:
    if not isinstance(request.user, Account) or not request.user.is_authenticated:
        raise PermissionDenied
    account = Account.objects.filter(pk=request.user.pk, is_active=True).first()
    if account is None:
        raise PermissionDenied
    return account


def _safe_next(request: HttpRequest, value: object) -> str:
    if not isinstance(value, str) or not value:
        return reverse("admin:index")
    if not url_has_allowed_host_and_scheme(
        value,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return reverse("admin:index")
    return value


def _response(
    request: HttpRequest,
    *,
    form: AccountStepUpForm,
    status: int = 200,
) -> HttpResponse:
    context: dict[str, Any] = admin.site.each_context(request)
    context.update(
        {
            "baseline_admin_parent_template": "admin/base_site.html",
            "baseline_use_admin_shell": True,
            "has_permission": True,
            "title": "Confirm it is you",
            "form": form,
        }
    )
    response = TemplateResponse(
        request,
        "identity/account_step_up.html",
        context,
        status=status,
    )
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@never_cache
@login_required(login_url="staff-login")
@require_http_methods(["GET", "POST"])
def account_step_up(request: HttpRequest) -> HttpResponse:
    account = _active_account(request)
    if request.method == "GET":
        if set(request.GET) - {"next"}:
            return _response(
                request,
                form=AccountStepUpForm(initial={"next": reverse("admin:index")}),
                status=400,
            )
        return _response(
            request,
            form=AccountStepUpForm(
                initial={"next": _safe_next(request, request.GET.get("next"))}
            ),
        )

    form = AccountStepUpForm(request.POST)
    if not form.is_valid():
        return _response(request, form=form, status=400)
    try:
        complete_step_up(
            account=account,
            request=request,
            password=form.cleaned_data["password"],
        )
    except ValidationError:
        form.add_error(
            "password",
            "The password could not confirm this session. Try again.",
        )
        return _response(request, form=form, status=400)
    messages.success(request, "Your session is confirmed for privileged actions.")
    response = redirect(_safe_next(request, form.cleaned_data.get("next")))
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    return response


__all__ = ["account_step_up"]
