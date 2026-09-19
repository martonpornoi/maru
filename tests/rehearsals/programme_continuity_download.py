"""Download through real fixture routes, then verify independently provisioned trust."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlencode
from uuid import UUID

from maru.scheduling.continuity_payload import (
    ContinuityProjection,
    decode_continuity_payload,
)
from maru.scheduling.continuity_protocol import (
    ContinuityInvalidError,
    ContinuityManifest,
    ContinuityScope,
    verify_continuity_package,
)
from tests.rehearsals.programme_https import ProgrammeHttpsError
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)


@dataclass(frozen=True, slots=True)
class DownloadedProgrammePack:
    """Private fixture bytes plus verified metadata, not proof of offline freshness."""

    manifest: ContinuityManifest
    package: bytes = field(repr=False)
    projection: ContinuityProjection = field(repr=False)


def continuity_path(scope):
    """Map only independently known closed purposes, never selectors from a pack."""
    if type(scope) is not ContinuityScope or any(
        type(value) is not UUID or value.int == 0
        for value in (scope.organization_id, scope.edition_id)
    ):
        raise ProgrammeHttpsError("fixture_continuity_scope_invalid")
    pair = scope.audience, scope.kind
    own = type(scope.actor_id) is UUID and scope.actor_id.int != 0
    targeted = type(scope.target_id) is UUID and scope.target_id.int != 0
    prefix = f"{scope.organization_id}/{scope.edition_id}/"
    if (
        pair == ("public", "public")
        and scope.actor_id is None
        and scope.target_id is None
        and scope.layers == ()
    ):
        path = f"/programme/{prefix}now/"
    elif (
        pair == ("exact_person", "personal")
        and own
        and scope.target_id is None
        and scope.layers == ()
    ):
        path = f"/my/{prefix}programme-now/"
    elif (
        scope.audience == "private_operator"
        and type(scope.kind) is str
        and scope.kind in {"room", "department", "edition"}
        and own
        and targeted
        and (scope.kind != "edition" or scope.target_id == scope.edition_id)
        and type(scope.layers) is tuple
        and all(type(layer) is str for layer in scope.layers)
        and set(scope.layers) <= {"technical", "accessibility", "media", "staffing"}
        and scope.layers == tuple(sorted(set(scope.layers)))
    ):
        path = f"/admin/programme/now/{prefix}{scope.kind}/{scope.target_id}/"
    else:
        raise ProgrammeHttpsError("fixture_continuity_scope_invalid")
    return path + "?" + urlencode(dict.fromkeys(scope.layers, "1") | {"format": "pack"})


def download_continuity_pack(session, *, scope, trust):
    """Verify actual HTTP bytes with expected scope and keys not obtained from them."""
    require_programme_rehearsal_request()
    response = session.request(continuity_path(scope))
    if (
        response.status != 200
        or response.headers.get("Content-Type", "").split(";")[0] != "application/json"
        or "no-store" not in response.headers.get("Cache-Control", "")
        or response.headers.get("X-Content-Type-Options") != "nosniff"
        or not response.headers.get("Content-Disposition", "").startswith("attachment;")
    ):
        raise ProgrammeHttpsError("fixture_continuity_download_failed")
    try:
        verified = verify_continuity_package(
            response.body, expected_scope=scope, trust=trust, now=datetime.now(UTC)
        )
        projection = decode_continuity_payload(
            verified.payload, manifest=verified.manifest
        )
    except ContinuityInvalidError:
        raise ProgrammeHttpsError("fixture_continuity_download_untrusted") from None
    return DownloadedProgrammePack(verified.manifest, response.body, projection)
