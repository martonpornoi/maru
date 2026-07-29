"""Authentication signals projected into user-visible security history."""

from typing import Any

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.http import HttpRequest
from django.utils import timezone

from maru.identity.models import Account, AccountSecurityEvent


def _append_session_event(
    *,
    account: Account,
    event_type: str,
    source_channel: str,
) -> None:
    AccountSecurityEvent.objects.create(
        account=account,
        event_type=event_type,
        outcome=AccountSecurityEvent.Outcome.SUCCEEDED,
        occurred_at=timezone.now(),
        source_channel=source_channel,
        detail_code="bootstrap_session",
    )


@receiver(user_logged_in, dispatch_uid="maru.identity.security_history.login")
def project_successful_login(
    sender: object,
    request: HttpRequest | None,
    user: Any,
    **kwargs: object,
) -> None:
    del sender, kwargs
    if isinstance(user, Account):
        _append_session_event(
            account=user,
            event_type=AccountSecurityEvent.EventType.SIGN_IN,
            source_channel="web" if request is not None else "service",
        )


@receiver(user_logged_out, dispatch_uid="maru.identity.security_history.logout")
def project_logout(
    sender: object,
    request: HttpRequest | None,
    user: Any,
    **kwargs: object,
) -> None:
    del sender, kwargs
    if isinstance(user, Account):
        _append_session_event(
            account=user,
            event_type=AccountSecurityEvent.EventType.SIGN_OUT,
            source_channel="web" if request is not None else "service",
        )
