import json
from uuid import uuid4

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from django.test import RequestFactory

from maru.demo.convention_plan import ACCOUNT_KEYS
from maru.demo.views import convention_demo


@pytest.fixture
def preview(monkeypatch, settings):
    settings.ROOT_URLCONF = "maru.demo.urls"
    settings.DEBUG = True
    settings.ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "maru.settings.local")
    monkeypatch.setenv("MARU_SYNTHETIC_CONVENTION_DEMO", "true")
    passwords = {key: f"synthetic-{key}-secret" for key in ACCOUNT_KEYS}
    monkeypatch.setenv("MARU_DEMO_PASSWORDS", json.dumps(passwords))
    manifest = {
        "schema_version": 1,
        "synthetic_only": True,
        "anchor": "2026-10-15",
        "time_zone": "Europe/Budapest",
        "editions": [
            {
                "key": key,
                "name": "MaruCon",
                "starts_on": "2026-10-14",
                "ends_on": "2026-10-17",
                "organization_id": str(uuid4()),
                "edition_id": str(uuid4()),
            }
            for key in ("ongoing", "future")
        ],
    }
    monkeypatch.setenv("MARU_DEMO_MANIFEST", json.dumps(manifest))
    request = RequestFactory().get(
        "/demo/", HTTP_HOST="127.0.0.1:8765", REMOTE_ADDR="127.0.0.1"
    )
    request.user = AnonymousUser()
    return request, manifest


def test_trial_displays_six_scoped_content_accounts_and_never_operator_passwords(
    preview,
):
    request, manifest = preview
    response = convention_demo(request)
    text = response.content.decode()
    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    assert response["Referrer-Policy"] == "same-origin"
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
    assert 'type="password" value="synthetic-ongoing-author-secret"' in text
    assert "synthetic-platform-secret" not in text
    assert "synthetic-operator-a-secret" not in text
    assert text.count("Copy password</button>") == 6
    assert all(edition["edition_id"] in text for edition in manifest["editions"])
    assert "accounts/login/?next=" in text
    assert "If your browser blocks copying, choose Show this practice password" in text


@pytest.mark.parametrize(
    "change",
    ["production", "remote", "host", "debug", "disabled", "missing", "malformed"],
)
def test_credential_trial_fails_closed_outside_exact_local_ready_preview(
    preview, monkeypatch, settings, change
):
    request, _manifest = preview
    if change == "production":
        monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "maru.settings.production")
    elif change == "remote":
        request.META["REMOTE_ADDR"] = "192.0.2.1"
    elif change == "host":
        settings.ALLOWED_HOSTS = ["example.invalid"]
        request.META["HTTP_HOST"] = "example.invalid"
    elif change == "debug":
        settings.DEBUG = False
    elif change == "disabled":
        monkeypatch.delenv("MARU_SYNTHETIC_CONVENTION_DEMO")
    elif change == "missing":
        monkeypatch.delenv("MARU_DEMO_MANIFEST")
    else:
        monkeypatch.setenv("MARU_DEMO_MANIFEST", '{"schema_version": 2}')
    with pytest.raises(Http404):
        convention_demo(request)


def test_trial_never_accepts_post_as_a_login_or_grant(preview):
    request, _manifest = preview
    request.method = "POST"
    assert convention_demo(request).status_code == 405
