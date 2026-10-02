"""Real exit-view CSRF decorators retain exact origins and token validation."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.test import RequestFactory

from maru.events import programme_stop_views
from maru.programme import archive_views


@pytest.mark.parametrize("owner", [programme_stop_views, archive_views])
@pytest.mark.parametrize(
    ("origin", "referer", "token_present", "expected"),
    [
        ("https://testserver", None, True, 200),
        ("null", None, True, 403),
        ("https://foreign.invalid", None, True, 403),
        (None, "https://testserver/original/", True, 200),
        (None, None, True, 403),
        ("https://testserver", None, False, 403),
    ],
)
def test_exit_views_keep_real_csrf_before_owner_commands(
    owner, origin, referer, token_present, expected, monkeypatch
):
    factory = RequestFactory()
    seed = factory.get("/", secure=True)
    token = get_token(seed)
    request = factory.post(
        "/synthetic-exit/",
        {"csrfmiddlewaretoken": token} if token_present else {},
        secure=True,
    )
    request.COOKIES["csrftoken"] = seed.META["CSRF_COOKIE"]
    request.user = SimpleNamespace(pk=UUID(int=1), is_authenticated=True)
    if origin is not None:
        request.META["HTTP_ORIGIN"] = origin
    if referer is not None:
        request.META["HTTP_REFERER"] = referer
    page = Mock(return_value=HttpResponse("synthetic owner boundary"))
    monkeypatch.setattr(owner, "_page", page)
    if owner is archive_views:
        monkeypatch.setattr(owner, "_scope", Mock(return_value=object()))
        view = owner.programme_archive
    else:
        view = owner.programme_stop
    response = view(request, UUID(int=2), UUID(int=3))
    assert response.status_code == expected
    assert page.call_count == (1 if expected == 200 else 0)
