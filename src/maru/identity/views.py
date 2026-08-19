"""Server-rendered, CSRF-protected identity challenge completion."""

from django.contrib.auth import login
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse

from maru.identity.forms import AccountRecoveryForm, EmailVerificationForm
from maru.identity.models import IdentityChallenge
from maru.identity.services import consume_identity_challenge


def verify_email(request: HttpRequest) -> HttpResponse:
    """Verify email.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    initial = {"token": request.GET.get("token", "")}
    form = EmailVerificationForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            account = consume_identity_challenge(
                raw_token=form.cleaned_data["token"],
                purpose=IdentityChallenge.Purpose.VERIFY_EMAIL,
                source_channel="reference_client",
            )
        except ValidationError as error:
            form.add_error(None, error.messages[0])
        else:
            login(request, account)
            return redirect("public-registration-index")
    return TemplateResponse(
        request,
        "identity/verify_email.html",
        {"form": form},
    )


def recover_account(request: HttpRequest) -> HttpResponse:
    """Render recover account.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    initial = {"token": request.GET.get("token", "")}
    form = AccountRecoveryForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            account = consume_identity_challenge(
                raw_token=form.cleaned_data["token"],
                purpose=IdentityChallenge.Purpose.RECOVER_ACCOUNT,
                new_password=form.cleaned_data["new_password"],
                source_channel="reference_client",
            )
        except ValidationError as error:
            form.add_error(None, error.messages[0])
        else:
            login(request, account)
            return redirect("public-registration-index")
    return TemplateResponse(
        request,
        "identity/recover_account.html",
        {"form": form},
    )
