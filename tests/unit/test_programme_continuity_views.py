"""Real shared templates and signatures with isolated, non-native owner reads."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from bs4 import BeautifulSoup
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, override_settings
from django.urls import Resolver404, resolve

from maru.scheduling import continuity_views as views
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.continuity_operator_source import operator_continuity_projection
from maru.scheduling.continuity_protocol import (
    ContinuityScope,
    ContinuityTrustKey,
    verify_continuity_package,
)
from maru.scheduling.continuity_signing import (
    ContinuitySigningKey,
    ContinuitySigningPolicy,
)
from maru.scheduling.continuity_sources import (
    personal_continuity_projection,
    public_continuity_projection,
)
from tests.unit.test_personal_timetable_rendering import (
    personal as personal,  # noqa: PLC0414
)
from tests.unit.test_programme_operator_rendering import (
    full_sheet as full_sheet,  # noqa: PLC0414
)
from tests.unit.test_programme_operator_rendering import sheet as sheet  # noqa: PLC0414
from tests.unit.test_scheduling_output_rendering import (
    snapshot as snapshot,  # noqa: PLC0414
)


@pytest.fixture(autouse=True)
def shell():
    with (
        override_settings(ROOT_URLCONF="tests.support.programme_output_urls"),
        patch.object(views.admin.site, "each_context", side_effect=lambda _request: {}),
        patch(
            "maru.events.templatetags.admin_edition_context.admin_shell_access",
            return_value={"workspace_available": False},
        ),
        patch(
            "maru.events.templatetags.admin_edition_context.project_shell_navigation",
            return_value={},
        ),
    ):
        yield


@pytest.fixture(params=["public", "exact_person", "private_operator"])
def projection(request, snapshot, personal, full_sheet):
    if request.param == "public":
        return public_continuity_projection(
            snapshot, organization_id=UUID(int=21), edition_id=UUID(int=22)
        )
    if request.param == "exact_person":
        return personal_continuity_projection(
            personal,
            actor_id=personal.actor_id,
            organization_id=personal.organization_id,
            edition_id=personal.edition_id,
        )
    return operator_continuity_projection(
        full_sheet,
        scope=ContinuityScope(
            full_sheet.organization_id,
            full_sheet.edition_id,
            "private_operator",
            UUID(int=19),
            full_sheet.kind.value,
            full_sheet.target_id,
            tuple(sorted(full_sheet.layers)),
        ),
    )


def request_view(projection, query="", *, method="get", anonymous=False):
    scope = projection.scope
    request = getattr(RequestFactory(), method)("/synthetic/now/" + query)
    request.user = (
        AnonymousUser()
        if anonymous
        else SimpleNamespace(
            pk=scope.actor_id,
            is_authenticated=True,
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )
    )
    ownership = {
        "organization_id": scope.organization_id,
        "edition_id": scope.edition_id,
    }
    if scope.audience == "public":
        return views.public_programme_now(request, **ownership)
    if scope.audience == "exact_person":
        return views.personal_programme_now(request, **ownership)
    return views.operator_programme_now(
        request, **ownership, scope_kind=scope.kind, target_id=scope.target_id
    )


def query(projection, output_format):
    return (
        "?format="
        + output_format
        + "".join(f"&{layer}=1" for layer in projection.scope.layers)
    )


def test_unavailable_then_fresh_source_does_not_retain_error_context(projection):
    with patch.object(
        views,
        "load_continuity_projection",
        side_effect=[SchedulingUnavailableError(), projection, projection],
    ):
        failed = request_view(projection, query(projection, "html"))
        recovered = request_view(projection, query(projection, "html"))
    assert failed.status_code == 503
    assert b"No old or partial" in failed.content
    assert recovered.status_code == 200
    assert b"Complete run sheet" in recovered.content
    assert b"No old or partial" not in recovered.content


@pytest.mark.parametrize("output_format", ["html", "print"])
def test_shared_shells_have_one_heading_landmark_and_exact_current_source(
    projection, output_format, monkeypatch
):
    load = Mock(return_value=projection)
    monkeypatch.setattr(views, "load_continuity_projection", load)
    signing = Mock(side_effect=AssertionError("HTML must not load signing secrets"))
    monkeypatch.setattr(views, "load_continuity_signing_policy", signing)
    response = request_view(projection, query(projection, output_format))
    assert response.status_code == 200
    assert load.call_args.args[0] == projection.scope
    assert isinstance(load.call_args.kwargs["correlation_id"], UUID)
    assert "no-store" in response["Cache-Control"]
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "unsafe-inline" not in response["Content-Security-Policy"]
    soup = BeautifulSoup(response.content, "html.parser")
    assert len(soup.find_all("h1")) == 1
    assert len(soup.find_all("main")) == 1
    assert soup.find(id="continuity-now") is not None
    assert soup.find(id="continuity-next") is not None
    assert soup.find(id="continuity-agenda") is not None
    text = soup.get_text(" ", strip=True)
    assert "Replace/dispose" in text
    assert projection.source_sha256 in text
    assert "not a freshness guarantee" in text
    if output_format == "html":
        assert "Download signed snapshot" in text
        # Stubbed content alone does not admit a separate destination.
        assert "Programme output tasks" not in text
    else:
        assert "Download signed snapshot" not in text
    if projection.scope.audience == "public":
        assert "Technical secret" not in text
        assert "Private host instructions" not in text
    elif projection.scope.audience == "exact_person":
        assert "Private host instructions" in text
        assert "Private handover instructions" in text
    else:
        assert "Technical secret" in text
        assert "retained predecessor, not cancelled" in text


def test_signed_download_is_real_exact_audience_and_contains_no_key(
    projection, monkeypatch
):
    key = Ed25519PrivateKey.generate()
    trust = ContinuityTrustKey(
        projection.scope.organization_id,
        projection.scope.edition_id,
        "ephemeral",
        key.public_key().public_bytes_raw(),
        projection.observed_at - timedelta(days=1),
        projection.observed_at + timedelta(days=1),
    )
    monkeypatch.setattr(
        views, "load_continuity_projection", Mock(return_value=projection)
    )
    monkeypatch.setattr(
        views,
        "load_continuity_signing_policy",
        lambda: ContinuitySigningPolicy((ContinuitySigningKey(trust, key),)),
    )
    monkeypatch.setattr(views.timezone, "now", lambda: projection.observed_at)
    response = request_view(projection, query(projection, "pack"))
    assert response.status_code == 200
    assert (
        'filename="programme-continuity.maru.json"' in response["Content-Disposition"]
    )
    verified = verify_continuity_package(
        response.content,
        expected_scope=projection.scope,
        trust=(trust,),
        now=projection.observed_at,
    )
    assert verified.manifest.scope == projection.scope
    assert b"private_key" not in response.content


def test_missing_signing_config_returns_no_file_but_live_view_still_works(
    projection, monkeypatch
):
    monkeypatch.setattr(
        views, "load_continuity_projection", Mock(return_value=projection)
    )
    monkeypatch.delenv("MARU_PROGRAMME_CONTINUITY_SIGNING_KEYS_JSON", raising=False)
    response = request_view(projection, query(projection, "pack"))
    assert response.status_code == 503
    assert "Content-Disposition" not in response
    assert b"No file was produced" in response.content
    assert b"continuity-agenda" not in response.content
    assert request_view(projection, query(projection, "html")).status_code == 200


@pytest.mark.parametrize(
    "bad_query",
    ["?actor=other", "?format=html&format=print", "?format=invalid", "?technical=0"],
)
def test_unknown_or_repeated_options_are_rejected_after_owner_admission(
    projection, bad_query, monkeypatch
):
    load = Mock(return_value=projection)
    monkeypatch.setattr(views, "load_continuity_projection", load)
    assert request_view(projection, bad_query).status_code == 400
    load.assert_called_once()
    load.side_effect = SchedulingAuthorizationDeniedError
    assert request_view(projection, bad_query).status_code == 404


def test_owner_failure_and_post_never_return_partial_content(projection, monkeypatch):
    load = Mock(side_effect=SchedulingUnavailableError)
    monkeypatch.setattr(views, "load_continuity_projection", load)
    response = request_view(projection, query(projection, "html"))
    assert response.status_code == 503
    assert b"continuity-agenda" not in response.content
    load.reset_mock()
    assert request_view(projection, method="post").status_code == 405
    load.assert_not_called()


def test_private_anonymous_redirect_and_no_production_mount(projection, monkeypatch):
    load = Mock(return_value=projection)
    monkeypatch.setattr(views, "load_continuity_projection", load)
    if projection.scope.audience != "public":
        assert request_view(projection, anonymous=True).status_code == 302
        load.assert_not_called()
    org, edition = projection.scope.organization_id, projection.scope.edition_id
    with override_settings(ROOT_URLCONF="maru.urls"):
        with pytest.raises(Resolver404):
            resolve(f"/programme/{org}/{edition}/now/")
        with pytest.raises(Resolver404):
            resolve(f"/my/{org}/{edition}/programme-now/")


def test_stored_markup_stays_escaped_in_real_shared_template(projection, monkeypatch):
    row = replace(projection.entries[0], title='<script>alert("untrusted")</script>')
    changed = replace(projection, entries=(row, *projection.entries[1:]))
    monkeypatch.setattr(views, "load_continuity_projection", Mock(return_value=changed))
    response = request_view(changed, query(changed, "html"))
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert not any(
        "untrusted" in script.get_text() for script in soup.find_all("script")
    )
    assert b"&lt;script&gt;" in response.content


@pytest.mark.parametrize("output_format", ["html", "print", "pack"])
@pytest.mark.parametrize(
    ("failure", "status"),
    [(SchedulingAuthorizationDeniedError, 404), (SchedulingUnavailableError, 503)],
)
def test_final_source_failure_discards_rendered_page_or_once_signed_pack(
    projection, monkeypatch, output_format, failure, status
):
    load = Mock(side_effect=[projection, failure])
    monkeypatch.setattr(views, "load_continuity_projection", load)
    monkeypatch.setattr(views, "programme_output_links", Mock(return_value=()))
    signer = Mock(return_value=b"synthetic signed bytes must be withheld")
    monkeypatch.setattr(views, "sign_continuity_projection", signer)
    monkeypatch.setattr(views, "load_continuity_signing_policy", Mock())
    response = request_view(projection, query(projection, output_format))
    assert response.status_code == status
    assert load.call_count == 2
    assert load.call_args.kwargs["expected"] is projection
    assert load.call_args.args[0] == projection.scope
    assert (
        load.call_args_list[0].kwargs["correlation_id"]
        == load.call_args.kwargs["correlation_id"]
    )
    assert signer.call_count == (1 if output_format == "pack" else 0)
    assert "Content-Disposition" not in response
    assert b"synthetic signed bytes" not in response.content
    assert b"continuity-agenda" not in response.content
    assert projection.source_sha256.encode() not in response.content


@pytest.mark.parametrize("elapsed", [-1, 2])
def test_pack_expiry_and_clock_rollback_after_source_recheck_withhold_file(
    projection, monkeypatch, elapsed
):
    key = Ed25519PrivateKey.generate()
    trust = ContinuityTrustKey(
        projection.scope.organization_id,
        projection.scope.edition_id,
        "ephemeral",
        key.public_key().public_bytes_raw(),
        projection.observed_at - timedelta(days=1),
        projection.observed_at + timedelta(days=1),
    )
    monkeypatch.setattr(
        views, "load_continuity_projection", Mock(return_value=projection)
    )
    monkeypatch.setattr(
        views,
        "load_continuity_signing_policy",
        lambda: ContinuitySigningPolicy(
            (ContinuitySigningKey(trust, key),), lifetime_seconds=1
        ),
    )
    signer = Mock(wraps=views.sign_continuity_projection)
    monkeypatch.setattr(views, "sign_continuity_projection", signer)
    monkeypatch.setattr(
        views.timezone,
        "now",
        Mock(
            side_effect=[
                projection.observed_at,
                projection.observed_at + timedelta(seconds=elapsed),
            ]
        ),
    )
    response = request_view(projection, query(projection, "pack"))
    assert response.status_code == 503
    assert "Content-Disposition" not in response
    signer.assert_called_once()
