from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.urls import reverse


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_google_email(email: str) -> bool:
    normalized = normalize_email(email)
    _, separator, domain = normalized.rpartition("@")
    return bool(separator) and domain in settings.MARU_GOOGLE_EMAIL_DOMAINS


@dataclass(frozen=True)
class GoogleIdentity:
    email: str
    email_verified: bool
    name: str = ""
    picture_url: str = ""


class GoogleOAuthError(Exception):
    pass


def is_google_oauth_configured() -> bool:
    return bool(
        settings.MARU_GOOGLE_OAUTH_CLIENT_ID
        and settings.MARU_GOOGLE_OAUTH_CLIENT_SECRET
    )


def build_google_authorization_url(request, state: str) -> str:
    query = {
        "client_id": settings.MARU_GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": google_redirect_uri(request),
        "response_type": "code",
        "scope": " ".join(settings.MARU_GOOGLE_OAUTH_SCOPES),
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{settings.MARU_GOOGLE_OAUTH_AUTHORIZATION_URL}?{urlencode(query)}"


def google_redirect_uri(request) -> str:
    configured = settings.MARU_GOOGLE_OAUTH_REDIRECT_URI
    if configured:
        return configured
    return request.build_absolute_uri(reverse("accounts:google_oauth_callback"))


def exchange_google_code_for_identity(code: str, request) -> GoogleIdentity:
    token_payload = _post_form(
        settings.MARU_GOOGLE_OAUTH_TOKEN_URL,
        {
            "code": code,
            "client_id": settings.MARU_GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.MARU_GOOGLE_OAUTH_CLIENT_SECRET,
            "redirect_uri": google_redirect_uri(request),
            "grant_type": "authorization_code",
        },
    )
    access_token = token_payload.get("access_token")
    if not access_token:
        raise GoogleOAuthError("Google did not return an access token.")

    userinfo = _get_json(
        settings.MARU_GOOGLE_OAUTH_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    email = normalize_email(str(userinfo.get("email", "")))
    if not email:
        raise GoogleOAuthError("Google did not return an email address.")
    return GoogleIdentity(
        email=email,
        email_verified=bool(userinfo.get("email_verified")),
        name=str(userinfo.get("name", "")),
        picture_url=str(userinfo.get("picture", "")),
    )


def _post_form(url: str, payload: dict[str, str]) -> dict:
    encoded = urlencode(payload).encode()
    request = Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    return _open_json(request)


def _get_json(url: str, headers: dict[str, str]) -> dict:
    request = Request(url, headers=headers, method="GET")
    return _open_json(request)


def _open_json(request: Request) -> dict:
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GoogleOAuthError("Google sign-in request failed.") from exc
