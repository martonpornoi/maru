"""Real signing and scope verification over simulated HTTP, not native issuance."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from maru.scheduling.continuity_offline import decode_continuity_trust_policy
from maru.scheduling.continuity_payload import ContinuityProjection
from maru.scheduling.continuity_protocol import ContinuityScope
from maru.scheduling.continuity_signing import (
    load_continuity_signing_policy,
    sign_continuity_projection,
)
from tests.rehearsals import programme_continuity_download as download
from tests.rehearsals import programme_continuity_material as material
from tests.rehearsals.programme_http_session import ProgrammeHttpResponse
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)


@pytest.fixture
def permitted(monkeypatch):
    guard = Mock(return_value=SimpleNamespace(run_id="a" * 32, lease_seconds=3600))
    monkeypatch.setattr(download, "require_programme_rehearsal_request", guard)
    monkeypatch.setattr(material, "require_programme_rehearsal_request", guard)
    monkeypatch.setattr(material, "remaining_lease", Mock(return_value=1800.0))
    setup = SimpleNamespace(organization_id=uuid4(), edition_id=uuid4())
    keys = material.generate_continuity_material(setup, deadline=1900.0)
    policy = load_continuity_signing_policy(
        environment={material.SIGNING_ENV: keys.signing_policy}
    )
    trust = decode_continuity_trust_policy(keys.trust_policy)
    scope = ContinuityScope(setup.organization_id, setup.edition_id, "public")
    now = datetime.now(UTC)
    projection = ContinuityProjection(
        scope,
        "scheduling.public-timetable@1",
        "a" * 64,
        now,
        "Europe/Budapest",
        "available",
        2,
        uuid4(),
        now - timedelta(seconds=1),
        "not_applicable",
        "not_applicable",
        (),
    )
    package = sign_continuity_projection(projection, policy=policy, issued_at=now)
    response = ProgrammeHttpResponse(
        200,
        {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": (
                'attachment; filename="programme-continuity.maru.json"'
            ),
        },
        package,
    )
    return scope, projection, response, trust


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "status",
        "mime",
        "cache",
        "nosniff",
        "attachment",
        "tamper",
        "scope",
        "key",
        "expiry",
    ],
)
def test_independent_trust_and_transport_are_both_required(
    permitted, monkeypatch, fault
):
    scope, projection, response, trust = permitted
    if fault == "status":
        response = replace(response, status=503)
    elif fault in {"mime", "cache", "nosniff", "attachment"}:
        field = {
            "mime": "Content-Type",
            "cache": "Cache-Control",
            "nosniff": "X-Content-Type-Options",
            "attachment": "Content-Disposition",
        }[fault]
        response.headers[field] = "incorrect"
    elif fault == "tamper":
        response = replace(response, body=response.body[:-1] + b"!")
    elif fault == "scope":
        scope = replace(scope, organization_id=uuid4())
    elif fault == "key":
        trust = (replace(trust[0], public_key=b"x" * 32),)
    elif fault == "expiry":
        monkeypatch.setattr(
            download,
            "datetime",
            SimpleNamespace(
                now=lambda _zone: projection.observed_at + timedelta(seconds=300)
            ),
        )
    session = Mock()
    session.request.return_value = response
    if fault:
        with pytest.raises(download.ProgrammeHttpsError, match="download"):
            download.download_continuity_pack(session, scope=scope, trust=trust)
    else:
        result = download.download_continuity_pack(session, scope=scope, trust=trust)
        assert result.manifest.scope == scope
        assert result.manifest.pointer_version == 2
        assert result.package == response.body
        assert result.projection == projection
        assert response.body.decode() not in repr(result)
        assert "projection=" not in repr(result)
    session.request.assert_called_once_with(download.continuity_path(scope))


@pytest.mark.parametrize(
    "kind", ["public", "personal", "room", "department", "edition"]
)
def test_paths_derive_only_from_independent_known_scope(permitted, kind):
    public = permitted[0]
    if kind == "personal":
        scope = replace(public, audience="exact_person", actor_id=uuid4(), kind=kind)
        prefix = "/my/"
    elif kind in {"room", "department", "edition"}:
        scope = replace(
            public,
            audience="private_operator",
            actor_id=uuid4(),
            kind=kind,
            target_id=public.edition_id if kind == "edition" else uuid4(),
            layers=("staffing",),
        )
        prefix = "/admin/programme/now/"
    else:
        scope, prefix = public, "/programme/"
    path = download.continuity_path(scope)
    assert path.startswith(prefix)
    assert f"{public.organization_id}/{public.edition_id}/" in path
    assert path.endswith("format=pack")
    assert ("staffing=1" in path) == (kind in {"room", "department", "edition"})


@pytest.mark.parametrize(
    "changes",
    [
        {"organization_id": UUID(int=0)},
        {"edition_id": "private"},
        {"actor_id": UUID(int=99)},
        {"layers": ("technical",)},
        {"kind": "unknown"},
        {
            "audience": "private_operator",
            "actor_id": UUID(int=99),
            "kind": "edition",
            "target_id": UUID(int=98),
        },
    ],
)
def test_invalid_scope_never_reads_http(permitted, changes):
    scope = replace(permitted[0], **changes)
    session = Mock()
    with pytest.raises(download.ProgrammeHttpsError, match="scope_invalid"):
        download.download_continuity_pack(session, scope=scope, trust=permitted[3])
    session.request.assert_not_called()


def test_deferral_precedes_every_http_or_crypto_read(monkeypatch):
    monkeypatch.setattr(
        download,
        "require_programme_rehearsal_request",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
        download.download_continuity_pack(None, scope=None, trust=None)
