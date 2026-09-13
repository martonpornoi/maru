"""Closed on-site cards preserve audience and interval semantics without a database."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from maru.scheduling import continuity_payload as payload
from maru.scheduling import continuity_presentation as presentation
from maru.scheduling.continuity_protocol import (
    ContinuityInvalidError,
    ContinuityManifest,
    ContinuityScope,
)

NOW = datetime(2030, 8, 2, 12, tzinfo=UTC)


@pytest.fixture
def projection():
    entry = payload.ContinuityEntry(
        f"public:{UUID(int=4)}",
        "public_event",
        "Opening",
        NOW,
        NOW + timedelta(hours=1),
        UUID(int=5),
        UUID(int=6),
        None,
        (payload.ContinuityFact("room", "Main stage"),),
    )
    return payload.ContinuityProjection(
        ContinuityScope(UUID(int=1), UUID(int=2), "public"),
        "scheduling.public-timetable@1",
        "a" * 64,
        NOW,
        "Europe/Budapest",
        "available",
        1,
        UUID(int=3),
        NOW - timedelta(minutes=1),
        "not_applicable",
        "not_applicable",
        (entry,),
    )


def manifest_for(projection):
    return ContinuityManifest(
        projection.scope,
        "test-key",
        projection.observed_at,
        NOW,
        NOW + timedelta(hours=1),
        projection.zone_name,
        projection.release_state,
        projection.pointer_version,
        projection.release_id,
        hashlib.sha256(payload.encode_continuity_payload(projection)).hexdigest(),
    )


def encoded(document):
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def test_live_cards_escape_markup_and_preserve_zone_source_and_copy_deadline(
    projection,
):
    row = replace(
        projection.entries[0],
        title='<script>alert("unsafe")</script>',
        facts=(payload.ContinuityFact("room", '<img src=x onerror="unsafe">'),),
    )
    html = presentation.render_continuity_body(
        replace(projection, entries=(row,)), at=NOW, expires_at=NOW + timedelta(hours=1)
    )
    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html
    assert "2020" not in html
    assert "Europe/Budapest" in html
    assert "2030-08-02 14:00:00+02:00" in html
    assert "2030-08-02 15:00:00+02:00" in html
    assert "Replace/dispose" in html
    assert "not a freshness guarantee" in html
    assert "not handoff" in html
    assert html.index("id='continuity-now'") < html.index("id='continuity-provenance'")
    assert "<main" not in html
    assert "<h1" not in html


def test_offline_html_is_script_free_self_contained_and_explicitly_a_dated_copy(
    projection,
):
    html = presentation.render_offline_continuity_html(
        projection, at=NOW + timedelta(minutes=10), expires_at=NOW + timedelta(hours=1)
    ).decode()
    assert html.count("<main") == 1
    assert html.count("<h1") == 1
    assert "<script" not in html
    assert "<form" not in html
    assert "href='http" not in html
    assert "style-src 'sha256-" in html
    assert "Historical / degraded copy - disconnected" in html
    assert "not a live verifier" in html
    assert "600 seconds" in html
    assert "cannot know newer releases" in html
    assert "@media print" in html
    assert "@media (max-width: 40rem)" in html


@pytest.mark.parametrize("state", ["withdrawn", "invalidated"])
def test_suppression_view_never_renders_old_normal_geometry(projection, state):
    suppressed = replace(
        projection,
        release_state=state,
        entries=(),
        release_id=projection.release_id if state == "invalidated" else None,
        published_at=projection.published_at if state == "invalidated" else None,
    )
    html = presentation.render_continuity_body(
        suppressed, at=NOW, expires_at=NOW + timedelta(hours=1)
    )
    assert "Normal Programme geometry is withheld" in html
    assert "Do not reuse an earlier timetable" in html
    assert "Opening" not in html
    assert "silently cancelled" in html


@pytest.mark.parametrize(
    ("at", "expires"),
    [
        (NOW - timedelta(seconds=1), NOW + timedelta(hours=1)),
        (NOW + timedelta(hours=1), NOW + timedelta(hours=1)),
        (NOW, NOW + timedelta(hours=4, seconds=1)),
    ],
)
def test_presentation_cannot_extend_expiry_or_render_before_observation(
    projection, at, expires
):
    with pytest.raises(ContinuityInvalidError):
        presentation.render_continuity_body(projection, at=at, expires_at=expires)


def test_presentation_byte_bound_never_returns_truncated_html(projection, monkeypatch):
    monkeypatch.setattr(presentation, "MAX_CONTINUITY_HTML_BYTES", 100)
    with pytest.raises(ContinuityInvalidError):
        presentation.render_continuity_body(
            projection, at=NOW, expires_at=NOW + timedelta(hours=1)
        )


def test_closed_round_trip_and_deterministic_sort(projection):
    second = replace(projection.entries[0], key=f"public:{UUID(int=7)}")
    unsorted = replace(projection, entries=(second, *projection.entries))
    document = payload.encode_continuity_payload(unsorted)
    result = payload.decode_continuity_payload(
        document, manifest=manifest_for(unsorted)
    )
    assert result.entries == (*projection.entries, second)
    assert payload.encode_continuity_payload(result) == document
    assert b"attendance" not in document


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_contract", "scheduling.personal-timetable@1"),
        ("source_sha256", "not-a-digest"),
        ("source_sha256", "A" * 64),
        ("zone_name", "Missing/Zone"),
        ("zone_name", []),
        ("release_state", []),
        ("release_state", "unknown"),
        ("pointer_version", True),
        ("pointer_version", 0),
        ("release_id", None),
        ("published_at", None),
        ("published_at", NOW + timedelta(seconds=1)),
        ("hosting_status", []),
        ("work_status", []),
        ("work_status", "available"),
        ("entries", []),
        ("observed_at", NOW.replace(tzinfo=None)),
    ],
)
def test_malformed_source_metadata_fails_closed(projection, field, value):
    with pytest.raises(ContinuityInvalidError):
        payload.encode_continuity_payload(replace(projection, **{field: value}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "operator_event"),
        ("kind", []),
        ("key", "public:invalid"),
        ("key", f"operator:{UUID(int=4)}"),
        ("title", ""),
        ("ends_at", NOW),
        ("space_id", None),
        ("day_id", None),
        ("context", (NOW, NOW, NOW, NOW)),
        ("facts", (payload.ContinuityFact("technical", "Private briefing"),)),
        ("facts", (payload.ContinuityFact("room", "a"),) * 2),
        ("facts", (payload.ContinuityFact("room", "a" * 5001),)),
    ],
)
def test_invalid_or_private_public_card_rejected(projection, field, value):
    entry = replace(projection.entries[0], **{field: value})
    with pytest.raises(ContinuityInvalidError):
        payload.encode_continuity_payload(replace(projection, entries=(entry,)))


@pytest.mark.parametrize("state", ["absent", "withdrawn", "invalidated"])
def test_known_suppression_cannot_include_old_geometry(projection, state):
    suppressed = replace(
        projection,
        release_state=state,
        pointer_version=0 if state == "absent" else 2,
        release_id=projection.release_id if state == "invalidated" else None,
        published_at=projection.published_at if state == "invalidated" else None,
    )
    with pytest.raises(ContinuityInvalidError):
        payload.encode_continuity_payload(suppressed)
    suppressed = replace(suppressed, entries=())
    encoded_payload = payload.encode_continuity_payload(suppressed)
    assert (
        payload.decode_continuity_payload(
            encoded_payload, manifest=manifest_for(suppressed)
        )
        == suppressed
    )


def test_duplicates_and_overbound_projection_are_not_partial_success(
    projection, monkeypatch
):
    with pytest.raises(ContinuityInvalidError):
        payload.encode_continuity_payload(
            replace(projection, entries=projection.entries * 2)
        )
    monkeypatch.setattr(payload, "MAX_CONTINUITY_PAYLOAD_BYTES", 100)
    with pytest.raises(ContinuityInvalidError):
        payload.encode_continuity_payload(projection)


@pytest.mark.parametrize(
    "mutation", ["private", "scope", "order", "date", "extra", "type"]
)
def test_decoder_rejects_noncanonical_mixed_or_malformed_data(projection, mutation):
    document = json.loads(payload.encode_continuity_payload(projection))
    if mutation == "private":
        document["entries"][0]["facts"].append({"code": "technical", "value": "secret"})
    elif mutation == "scope":
        document["scope"]["organization_id"] = str(UUID(int=9))
    elif mutation == "date":
        document["entries"][0]["starts_at"] = NOW.isoformat().replace("+00:00", "Z")
    elif mutation == "extra":
        document["entries"][0]["private_notes"] = "secret"
    elif mutation == "type":
        document["work_status"] = []
    raw = encoded(document) if mutation != "order" else json.dumps(document).encode()
    with pytest.raises(ContinuityInvalidError):
        payload.decode_continuity_payload(raw, manifest=manifest_for(projection))


def test_now_end_exclusive_next_ties_and_full_agenda(projection):
    opening = projection.entries[0]
    next_one = replace(
        opening,
        key=f"public:{UUID(int=7)}",
        starts_at=opening.ends_at,
        ends_at=opening.ends_at + timedelta(hours=1),
    )
    next_two = replace(next_one, key=f"public:{UUID(int=8)}")
    complete = replace(projection, entries=(next_two, opening, next_one))
    at_start = payload.programme_now_next(complete, at=NOW)
    assert at_start.now == (opening,)
    assert at_start.next == (next_one, next_two)
    at_end = payload.programme_now_next(complete, at=opening.ends_at)
    assert at_end.now == (next_one, next_two)
    assert at_end.next == ()
    assert len(complete.entries) == 3


def personal_work(projection, status):
    return replace(
        projection,
        scope=replace(
            projection.scope,
            audience="exact_person",
            actor_id=UUID(int=9),
            kind="personal",
        ),
        source_contract="scheduling.personal-timetable@1",
        release_state="unobserved",
        pointer_version=None,
        release_id=None,
        published_at=None,
        hosting_status="unobserved",
        work_status="available",
        entries=(
            replace(
                projection.entries[0],
                key=f"work:{UUID(int=4)}",
                kind=f"work_{status}",
                space_id=None,
                day_id=None,
                facts=(payload.ContinuityFact("status", status),),
            ),
        ),
    )


@pytest.mark.parametrize("status", ["claimed", "confirmed", "removed", "completed"])
def test_retained_work_does_not_depend_on_hosting_or_imply_attendance(
    projection, status
):
    work = personal_work(projection, status)
    result = payload.programme_now_next(work, at=NOW)
    assert bool(result.now) == (status in {"claimed", "confirmed"})
    assert work.entries[0].kind == f"work_{status}"
    assert (
        payload.decode_continuity_payload(
            payload.encode_continuity_payload(work), manifest=manifest_for(work)
        )
        == work
    )


def test_host_context_normalizes_timezone_without_extending_required_presence(
    projection,
):
    personal = personal_work(projection, "confirmed")
    context = (
        NOW - timedelta(minutes=30),
        NOW,
        NOW + timedelta(hours=1),
        NOW + timedelta(hours=2),
    )
    host = replace(
        projection.entries[0],
        key=f"host:{UUID(int=8)}:{UUID(int=4)}",
        kind="host_presence",
        starts_at=NOW + timedelta(minutes=15),
        context=tuple(
            value.astimezone(timezone(timedelta(hours=2))) for value in context
        ),
    )
    personal = replace(
        personal,
        release_state="available",
        hosting_status="available",
        pointer_version=1,
        release_id=UUID(int=3),
        published_at=NOW,
        entries=(host,),
    )
    document = payload.encode_continuity_payload(personal)
    result = payload.decode_continuity_payload(
        document, manifest=manifest_for(personal)
    )
    assert result.entries[0].context == context
    assert payload.programme_now_next(result, at=NOW).now == ()
    assert payload.programme_now_next(result, at=NOW).next == result.entries
