"""Escaped on-site presentation shared by live pages and offline copies."""

from __future__ import annotations

import base64
import hashlib
from html import escape
from importlib.resources import files
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .continuity_payload import encode_continuity_payload, programme_now_next
from .continuity_protocol import MAX_CONTINUITY_AGE, ContinuityInvalidError, _utc

if TYPE_CHECKING:
    from datetime import datetime

    from .continuity_payload import ContinuityEntry, ContinuityProjection

MAX_CONTINUITY_HTML_BYTES = 16 * 1024 * 1024
_KIND_LABELS = {
    "public_event": "Released event",
    "host_presence": "Your required host presence",
    "work_claimed": "Tentative claim - not confirmed",
    "work_confirmed": "Your retained confirmed work",
    "work_removed": "Removed work record - not current work",
    "work_completed": "Completed work record - not attendance evidence",
    "operator_event": "Operator preparation, delivery and teardown",
    "staffing_demand": "Current requested staffing - not confirmed attendance",
}
_STATE_LABELS = {
    "available": "Approved Programme release available at the source check",
    "absent": "No Programme release published at the source check",
    "withdrawn": "Programme withdrawn - obtain replacement instructions",
    "invalidated": "Programme relocation/review pending - do not use old geometry",
    "unobserved": "No confirmed hosting required a release lookup",
    "unadopted": "Hosting not adopted for this edition",
}
_FACT_LABELS = {
    "summary": "Reviewed summary",
    "content_note": "Reviewed content note",
    "room": "Current room label",
    "venue": "Current venue label",
    "reviewed_copy": "Selected reviewed rendition",
    "wayfinding_version": "Current wayfinding source",
    "service_day": "Released service day (UTC)",
    "role": "Your host role",
    "briefing": "Current owner instructions",
    "host_version": "Current host source",
    "status": "Retained work / demand state",
    "location": "Current instruction location - not an accepted relocation",
    "supervision": "Current supervision instructions",
    "department": "Department",
    "position": "Position",
    "commitment_version": "Retained work version",
    "demand_version": "Current demand source",
    "demand_status": "Current demand state",
    "rest_until": "Retained rest boundary (UTC)",
    "required_headcount": "Requested headcount - not attendance",
    "retained_work": "Retained work counts and original intervals (UTC)",
    "programme_link": "Programme binding and predecessor meaning",
    "technical": "Current technical instructions",
    "accessibility": "Current accessibility delivery instructions",
    "media": "Current media instructions",
    "delivery_version": "Current delivery source",
}


def _instant(value: datetime, zone: ZoneInfo) -> str:
    return escape(_utc(value).astimezone(zone).isoformat(sep=" ", timespec="seconds"))


def _card(entry: ContinuityEntry, index: int, zone: ZoneInfo) -> str:
    context = ""
    if entry.context is not None:
        context = (
            "<dl class='continuity-context'>"
            + "".join(
                f"<dt>{label}</dt><dd>{_instant(value, zone)}</dd>"
                for label, value in zip(
                    (
                        "Preparation starts",
                        "Delivery starts",
                        "Delivery ends",
                        "Teardown ends",
                    ),
                    entry.context,
                    strict=True,
                )
            )
            + "</dl><p>Placement context does not assign every phase to a host.</p>"
        )
    facts = "".join(
        f"<dt>{_FACT_LABELS[fact.code]}</dt>"
        f"<dd>{escape(fact.value) or 'None recorded'}</dd>"
        for fact in entry.facts
    )
    return (
        f"<article id='continuity-entry-{index}' class='continuity-card'>"
        f"<h3>{escape(entry.title)}</h3><p>{_KIND_LABELS[entry.kind]}</p>"
        f"<p><strong>From</strong> {_instant(entry.starts_at, zone)}<br>"
        f"<strong>Until</strong> {_instant(entry.ends_at, zone)}</p>"
        f"{context}<dl>{facts}</dl><p class='continuity-reference'>"
        f"Source row: {escape(entry.key)}</p></article>"
    )


def _group(
    name: str,
    rows: tuple[ContinuityEntry, ...],
    indexes: dict[str, int],
    zone: ZoneInfo,
) -> str:
    content = (
        "<ul>"
        + "".join(
            f"<li><a href='#continuity-entry-{indexes[row.key]}'>"
            f"{escape(row.title)}</a>"
            f" - {_KIND_LABELS[row.kind]}: {_instant(row.starts_at, zone)} "
            f"to {_instant(row.ends_at, zone)}</li>"
            for row in rows
        )
        + "</ul>"
        if rows
        else "<p>No relevant operative intervals in this group.</p>"
    )
    return (
        f"<section aria-labelledby='continuity-{name}'>"
        f"<h2 id='continuity-{name}'>{name.capitalize()}</h2>{content}</section>"
    )


def _source_details(projection: ContinuityProjection, zone: ZoneInfo) -> str:
    scope = projection.scope
    scope_text = (
        f"{scope.audience}; organization {scope.organization_id}; "
        f"edition {scope.edition_id}; purpose {scope.kind}"
    )
    if scope.actor_id is not None:
        scope_text += f"; exact person {scope.actor_id}"
    if scope.target_id is not None:
        scope_text += f"; target {scope.target_id}"
    scope_text += "; requested layers: " + (", ".join(scope.layers) or "none")
    pointer = (
        projection.pointer_version
        if projection.pointer_version is not None
        else "not observed"
    )
    published = (
        _instant(projection.published_at, zone)
        if projection.published_at
        else "not observed"
    )
    return (
        "<section aria-labelledby='continuity-provenance'>"
        "<h2 id='continuity-provenance'>Scope and source details</h2>"
        f"<p><strong>Scope:</strong> {escape(scope_text)}</p>"
        f"<p>Release pointer: {pointer}; "
        f"release: {projection.release_id or 'none observed'}; "
        f"published: {published}.</p>"
        f"<p>Hosting layer: {escape(projection.hosting_status)}; "
        f"work layer: {escape(projection.work_status)}.</p>"
        "<p class='continuity-reference'>Source contract: "
        f"{escape(projection.source_contract)}; SHA-256: "
        f"{projection.source_sha256}</p></section>"
    )


def render_continuity_body(
    projection: ContinuityProjection,
    *,
    at: datetime,
    expires_at: datetime,
    offline: bool = False,
) -> str:
    """Render escaped bounded cards after live or signed admission.

    Parameters
    ----------
    projection : ContinuityProjection
        Complete owner-authorized live data, or decoded verified offline payload.
    at : datetime
        Explicit live observation or offline verification time for frozen now/next.
    expires_at : datetime
        Copy disposal deadline, never a promise of freshness until that instant.
    offline : bool, default=False
        True only after signature, scope, expiry and persisted known-state checks.

    Returns
    -------
    str
        Escaped content fragment with no main landmark, page H1, script or mutation.

    Raises
    ------
    ContinuityInvalidError
        If the copy clock, expiry, mode or complete rendered byte budget is invalid.

    Notes
    -----
    This presentation function verifies no signature and grants no authority. The
    offline caller must persist newly verified source metadata before calling it.
    All user-controlled text is escaped; only code-owned labels and markup are raw.
    """
    encode_continuity_payload(projection)
    observed, at, expires_at = _utc(projection.observed_at), _utc(at), _utc(expires_at)
    if (
        type(offline) is not bool
        or not observed <= at < expires_at
        or expires_at - observed > MAX_CONTINUITY_AGE
    ):
        raise ContinuityInvalidError
    zone = ZoneInfo(projection.zone_name)
    grouped = programme_now_next(projection, at=at)
    entries = tuple(
        sorted(projection.entries, key=lambda row: (_utc(row.starts_at), row.key))
    )
    indexes = {row.key: index for index, row in enumerate(entries)}
    mode = (
        "Historical / degraded copy - disconnected"
        if offline
        else "Freshly checked online view - saved copies become historical"
    )
    warning = (
        "This device cannot know newer releases, withdrawals, permission "
        "or key changes. "
        "Signature verification does not prove current instructions or authority."
        if offline
        else "Refresh for a complete new authorized check. No last-good cache is used."
    )
    suppression = (
        "<p class='continuity-warning' role='status'>"
        "Normal Programme geometry is withheld. Do not reuse an earlier timetable. "
        "Retained work is not silently cancelled or relocated; obtain current "
        "instructions through the organizer's governed process.</p>"
        if projection.release_state in {"withdrawn", "invalidated"}
        else ""
    )
    content = (
        "<div class='programme-continuity'>"
        "<section class='continuity-source' aria-labelledby='continuity-source'>"
        f"<h2 id='continuity-source'>{mode}</h2>"
        f"<p><strong>{_STATE_LABELS[projection.release_state]}</strong></p>{suppression}"
        f"<p>{warning}</p><p>Now/next is frozen at {_instant(at, zone)}. "
        "It does not prove attendance, qualification or work performed.</p>"
        f"<p><strong>Time zone:</strong> {escape(projection.zone_name)}. "
        f"<strong>Source checked:</strong> {_instant(observed, zone)}. "
        "<strong>Source age at rendering:</strong> "
        f"{int((at - observed).total_seconds())} seconds.</p>"
        "<p><strong>Replace/dispose no later than:</strong> "
        f"{_instant(expires_at, zone)}. "
        "Replace sooner on any known change, withdrawal or stop-use. "
        "This is not a freshness guarantee; expiry cannot erase saved "
        "or printed copies.</p></section>"
        + _group("now", grouped.now, indexes, zone)
        + _group("next", grouped.next, indexes, zone)
        + "<section aria-labelledby='continuity-agenda'>"
        "<h2 id='continuity-agenda'>Complete run sheet</h2>"
        + (
            "".join(_card(row, index, zone) for index, row in enumerate(entries))
            if entries
            else "<p>No relevant rows in this authorized scope. "
            "This does not imply edition-wide absence.</p>"
        )
        + "</section>"
        + _source_details(projection, zone)
        + "<p>Private copies require controlled encrypted event storage "
        "and accountable paper custody. A download or print is not handoff, "
        "acknowledgement, acceptance or a write channel.</p></div>"
    )
    if len(content.encode("utf-8")) > MAX_CONTINUITY_HTML_BYTES:
        raise ContinuityInvalidError
    return content


def render_offline_continuity_html(
    projection: ContinuityProjection, *, at: datetime, expires_at: datetime
) -> bytes:
    """Wrap verified historical content in a self-contained script-free print document.

    Parameters
    ----------
    projection : ContinuityProjection
        Verified and decoded data after protected known state has been persisted.
    at : datetime
        Actual offline verification instant, not a supplied file timestamp.
    expires_at : datetime
        Exact signed expiry, not an extension chosen by the offline operator.

    Returns
    -------
    bytes
        Bounded escaped UTF-8 HTML with only a code-owned hash-authorized stylesheet.

    Raises
    ------
    ContinuityInvalidError
        If the complete standalone HTML exceeds the output budget.

    Notes
    -----
    This dated HTML is not a live verifier. Re-run verification to refresh now/next;
    dispose of copies when superseded, expired or withdrawn. No network is required.
    """
    body = render_continuity_body(
        projection, at=at, expires_at=expires_at, offline=True
    )
    css = (
        files("maru.scheduling")
        .joinpath("static/scheduling/continuity.css")
        .read_text(encoding="utf-8")
    )
    style_hash = base64.b64encode(hashlib.sha256(css.encode("utf-8")).digest()).decode(
        "ascii"
    )
    document = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; "
        f"style-src 'sha256-{style_hash}'; base-uri 'none'; form-action 'none'\">"
        "<title>Historical Programme continuity · Maru</title>"
        f"<style>{css}</style></head>"
        "<body><a class='continuity-skip' href='#continuity-main'>Skip to run sheet</a>"
        "<main id='continuity-main'><h1>Historical Programme continuity</h1>"
        "<p>Signature and known-state checks completed when this copy was generated. "
        "This HTML is a dated copy, not a live verifier. "
        "Use your browser's Print command "
        "for a paper fallback; keep all source warnings with it.</p>"
        f"{body}</main></body></html>"
    ).encode()
    if len(document) > MAX_CONTINUITY_HTML_BYTES:
        raise ContinuityInvalidError
    return document
