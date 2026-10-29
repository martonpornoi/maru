"""Keep adoption, credentials, dates and normal sign-in explicit in practice."""

import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock
from urllib.parse import unquote

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from django.test import RequestFactory
from scripts import convention_preview, try_maru

from maru.demo import workforce_plan
from maru.demo.convention_plan import ACCOUNT_KEYS, account_identity
from maru.demo.views import convention_demo, workforce_demo


def test_practice_has_distinct_closed_fictional_identities_and_fixed_dates():
    original = {account_identity(key)[0] for key in ACCOUNT_KEYS}
    people = {
        workforce_plan.account_identity(key)[0] for key in workforce_plan.ACCOUNT_KEYS
    }
    assert len(people) == 9
    assert people.isdisjoint(original)
    assert all(
        workforce_plan.account_identity(key)[1].endswith("@maru.invalid")
        for key in workforce_plan.ACCOUNT_KEYS
    )
    anchor = date(2026, 10, 29)
    ongoing, future = workforce_plan.edition_plan(anchor)
    assert ongoing.starts_on < anchor < ongoing.ends_on < future.starts_on
    with pytest.raises(ValueError, match="Unknown"):
        workforce_plan.account_identity("actual-human")


def test_practice_work_uses_real_elapsed_time_and_future_edition_local_time():
    now = datetime(2026, 10, 29, 12, tzinfo=UTC)
    ongoing, future = workforce_plan.edition_plan(now.date())
    start, end = workforce_plan.shift_period(ongoing, now)
    assert start == now + timedelta(minutes=3)
    assert end == now + timedelta(minutes=5)
    future_start, future_end = workforce_plan.shift_period(future, now)
    assert future_start.date() == future.starts_on
    assert future_start.hour == 10
    assert future_end - future_start == timedelta(hours=1)
    assert str(future_start.tzinfo) == "Europe/Budapest"
    with pytest.raises(ValueError, match="aware"):
        workforce_plan.shift_period(ongoing, now.replace(tzinfo=None))


@pytest.fixture
def preview(monkeypatch, settings):
    settings.ROOT_URLCONF = "maru.demo.urls"
    settings.DEBUG = True
    settings.ALLOWED_HOSTS = ["127.0.0.1"]
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "maru.settings.local")
    monkeypatch.setenv("MARU_SYNTHETIC_CONVENTION_DEMO", "true")
    passwords = {key: f"fictional-{key}-secret" for key in workforce_plan.ACCOUNT_KEYS}
    monkeypatch.setenv("MARU_DEMO_PASSWORDS", json.dumps(passwords))
    manifest = {
        "schema_version": 1,
        "scenario": "workforce",
        "synthetic_only": True,
        "anchor": "2026-10-29",
        "time_zone": "Europe/Budapest",
        "editions": [
            {
                "key": key,
                "name": "MaruCon team",
                "organization_slug": "fictional",
                "series_slug": "team",
                "edition_slug": key,
            }
            for key in ("ongoing", "future")
        ],
    }
    monkeypatch.setenv("MARU_DEMO_MANIFEST", json.dumps(manifest))
    request = RequestFactory().get(
        "/demo/workforce/", HTTP_HOST="127.0.0.1:8765", REMOTE_ADDR="127.0.0.1"
    )
    request.user = AnonymousUser()
    return request, manifest


def test_trial_has_six_closed_accounts_and_scoped_normal_links(preview):
    request, _manifest = preview
    response = workforce_demo(request)
    text = response.content.decode()
    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    assert "private" in response["Cache-Control"]
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
    assert text.count("Copy password</button>") == 6
    assert "fictional-platform-secret" not in text
    assert "fictional-operator-a-secret" not in text
    assert "fictional-ongoing-volunteer-secret" in text
    assert "accounts/login/?next=" in text
    assert "my/workforce/fictional/team/future/availability/" in unquote(text)
    assert "five actual minutes" in text
    assert "synthetic setup, not independent human acceptance" in text


@pytest.mark.parametrize(
    "change",
    [
        "remote",
        "production",
        "not_ready",
        "wrong_scenario",
        "wrong_roles",
        "not_synthetic",
    ],
)
def test_workforce_trial_rejects_any_nonlocal_or_mixed_dataset(
    preview, monkeypatch, change
):
    request, manifest = preview
    if change == "remote":
        request.META["REMOTE_ADDR"] = "192.0.2.2"
    elif change == "production":
        monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "maru.settings.production")
    elif change == "not_ready":
        monkeypatch.delenv("MARU_DEMO_MANIFEST")
    elif change == "wrong_roles":
        monkeypatch.setenv("MARU_DEMO_PASSWORDS", json.dumps({"platform": "fictional"}))
    else:
        manifest["scenario" if change == "wrong_scenario" else "synthetic_only"] = (
            "convention" if change == "wrong_scenario" else False
        )
        monkeypatch.setenv("MARU_DEMO_MANIFEST", json.dumps(manifest))
    with pytest.raises(Http404):
        workforce_demo(request)


def test_workforce_manifest_never_populates_the_existing_convention_trial(preview):
    request, _manifest = preview
    with pytest.raises(Http404):
        convention_demo(request)
    request.method = "POST"
    assert workforce_demo(request).status_code == 405


def test_explicit_launcher_selects_separate_preparation_and_destination(monkeypatch):
    prepare = Mock()
    monkeypatch.setattr(convention_preview, "prepare_convention_preview", prepare)
    preview = Mock()
    destination, _help = try_maru.prepare_scenario(preview, "workforce")
    assert destination == "demo/workforce/"
    prepare.assert_called_once_with(preview, scenario="workforce")
    preview.manage.assert_not_called()
