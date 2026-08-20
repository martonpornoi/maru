"""Bounded, purpose-built registration reporting presets."""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from io import StringIO
from typing import TYPE_CHECKING, cast

from django.db.models import Prefetch, QuerySet

from maru.participation.models import ParticipationCapacity
from maru.registration.models import (
    AttendeeRegistrationProfile,
    Entitlement,
    MediaReviewStatus,
    Registration,
    RegistrationSubmission,
)
from maru.registration.presentation import attendance_labels
from maru.registration.profile_choices import LANGUAGE_LABELS

if TYPE_CHECKING:
    from uuid import UUID

COMING_STATES = (
    Registration.State.CONFIRMED,
    Registration.State.CHECKED_IN,
)
MAX_SYNCHRONOUS_REPORT_ROWS = 5_000


@dataclass(frozen=True, slots=True)
class AttendeeReportFilters:
    """Describe attendee report filters.

    Attributes
    ----------
    search
        The search retained in this immutable projection.
    country_code
        The stable country code from the relevant closed catalog.
    level
        The level retained in this immutable projection.
    """

    search: str = ""
    country_code: str = ""
    level: str = ""


def attendee_report_queryset(
    *,
    organization_id: UUID,
    edition_id: UUID,
) -> QuerySet[Registration]:
    """Return the trusted, edition-scoped source for attendee reporting.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.

    Returns
    -------
    QuerySet[Registration]
        The matching attendee report queryset records in deterministic order.
    """
    return (
        Registration.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            state__in=COMING_STATES,
        )
        .select_related(
            "account",
            "edition",
            "participation",
            "product",
            "attendee_profile",
            "submission",
        )
        .prefetch_related(
            Prefetch(
                "entitlements",
                queryset=Entitlement.objects.filter(
                    status=Entitlement.Status.ACTIVE
                ).order_by("granted_at", "id"),
            ),
            Prefetch(
                "participation__capacities",
                queryset=ParticipationCapacity.objects.filter(
                    status__in=(
                        ParticipationCapacity.Status.PROPOSED,
                        ParticipationCapacity.Status.ACTIVE,
                    )
                ).order_by("code", "id"),
            ),
        )
        .order_by("account__display_name", "reference", "id")
    )


def _badge_name(registration: Registration) -> tuple[str, str]:
    submission = cast(
        "RegistrationSubmission | None",
        getattr(registration, "submission", None),
    )
    if submission is not None:
        for key in ("badge-name", "badge_name"):
            answer = submission.answers.get(key)
            if isinstance(answer, str) and answer.strip():
                return answer.strip(), "registration_answer"
        for item in submission.schema_snapshot:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", ""))
            label = str(item.get("label", ""))
            purpose = str(item.get("purpose", ""))
            meaning = f"{label} {purpose}".casefold()
            answer = submission.answers.get(key)
            if (
                "badge" in meaning
                and "name" in meaning
                and isinstance(answer, str)
                and answer.strip()
            ):
                return answer.strip(), "registration_answer"
    return registration.account.display_name, "platform_display_name"


def _profile(registration: Registration) -> AttendeeRegistrationProfile | None:
    return cast(
        "AttendeeRegistrationProfile | None",
        getattr(registration, "attendee_profile", None),
    )


def attendee_report_rows(registrations: list[Registration]) -> list[dict[str, object]]:
    """Create the minimized row projection shared by the page and CSV export.

    Parameters
    ----------
    registrations : list[Registration]
        The registrations evaluated while attendee report rows.

    Returns
    -------
    list[dict[str, object]]
        The matching attendee report rows records in deterministic order.
    """
    rows: list[dict[str, object]] = []
    for registration in registrations:
        profile = _profile(registration)
        badge_name, badge_name_source = _badge_name(registration)
        labels = attendance_labels(registration)
        language_codes = profile.spoken_language_codes if profile is not None else []
        rows.append(
            {
                "registration_id": registration.id,
                "reference": registration.reference,
                "badge_name": badge_name,
                "badge_name_source": badge_name_source,
                "display_name": registration.account.display_name,
                "pronouns": profile.pronouns if profile is not None else "",
                "spoken_language_codes": language_codes,
                "spoken_languages": [
                    LANGUAGE_LABELS[code]
                    for code in language_codes
                    if code in LANGUAGE_LABELS
                ],
                "country_code": profile.country_code if profile is not None else "",
                "registration_state": registration.state,
                "product_name": registration.product_name_snapshot,
                "attendance_labels": [label.as_dict() for label in labels],
                "profile_photo_status": (
                    profile.profile_photo_status
                    if profile is not None
                    else MediaReviewStatus.NONE
                ),
            }
        )
    return rows


def filter_attendee_report_rows(
    rows: list[dict[str, object]],
    filters: AttendeeReportFilters,
) -> list[dict[str, object]]:
    """Return filter attendee report rows.

    Parameters
    ----------
    rows : list[dict[str, object]]
        The database rows included in the integrity evaluation.
    filters : AttendeeReportFilters
        The filters evaluated while filter attendee report rows.

    Returns
    -------
    list[dict[str, object]]
        A disclosure-safe mapping for filter attendee report rows.
    """
    search = filters.search.strip().casefold()
    country_filter = filters.country_code.strip()
    country_code = (
        "unknown" if country_filter.casefold() == "unknown" else country_filter.upper()
    )
    level = filters.level.strip()
    filtered: list[dict[str, object]] = []
    for row in rows:
        if country_code == "unknown" and row["country_code"]:
            continue
        if country_code not in ("", "unknown") and row["country_code"] != country_code:
            continue
        labels = cast("list[dict[str, str]]", row["attendance_labels"])
        if level and all(label["code"] != level for label in labels):
            continue
        if search:
            searchable = " ".join(
                (
                    str(row["reference"]),
                    str(row["badge_name"]),
                    str(row["display_name"]),
                )
            ).casefold()
            if search not in searchable:
                continue
        filtered.append(row)
    return filtered


def attendee_report_summary(
    rows: list[dict[str, object]],
) -> dict[str, object]:
    """Return attendee report summary.

    Parameters
    ----------
    rows : list[dict[str, object]]
        The database rows included in the integrity evaluation.

    Returns
    -------
    dict[str, object]
        A disclosure-safe mapping for attendee report summary.
    """
    country_counts = Counter(str(row["country_code"]) or "unknown" for row in rows)
    level_counts: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        for label in cast("list[dict[str, str]]", row["attendance_labels"]):
            level_counts[(label["code"], label["label"], label["tone"])] += 1
    return {
        "coming": len(rows),
        "confirmed": sum(
            row["registration_state"] == Registration.State.CONFIRMED for row in rows
        ),
        "checked_in": sum(
            row["registration_state"] == Registration.State.CHECKED_IN for row in rows
        ),
        "countries": sum(code != "unknown" for code in country_counts),
        "volunteers": sum(
            any(
                label["code"] == "volunteer"
                for label in cast("list[dict[str, str]]", row["attendance_labels"])
            )
            for row in rows
        ),
        "approved_profile_photos": sum(
            row["profile_photo_status"] == MediaReviewStatus.APPROVED for row in rows
        ),
        "country_breakdown": [
            {
                "country_code": code,
                "count": count,
                "percentage": round((count / len(rows)) * 100, 1) if rows else 0,
            }
            for code, count in sorted(
                country_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
        "level_breakdown": [
            {
                "code": code,
                "label": label,
                "tone": tone,
                "count": count,
            }
            for (code, label, tone), count in sorted(
                level_counts.items(),
                key=lambda item: (-item[1], item[0][1]),
            )
        ],
    }


def _safe_csv_value(value: object) -> str:
    rendered = str(value)
    if rendered.startswith(("=", "+", "-", "@")):
        return f"'{rendered}"
    return rendered


def badge_export_csv(
    *,
    rows: list[dict[str, object]],
    edition_name: str,
    edition_id: UUID,
    generated_at: str,
) -> str:
    """Render an Excel-compatible, formula-neutralized UTF-8 CSV.

    Parameters
    ----------
    rows : list[dict[str, object]]
        The database rows included in the integrity evaluation.
    edition_name : str
        The human-readable edition name shown to authorized readers.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    generated_at : str
        The timezone-aware timestamp for generated.

    Returns
    -------
    str
        The normalized text for badge export csv.
    """
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        (
            "edition_name",
            "edition_id",
            "generated_at",
            "registration_reference",
            "badge_name",
            "badge_name_source",
            "display_name",
            "pronouns",
            "spoken_language_codes",
            "spoken_languages",
            "registration_country_code",
            "attendee_levels",
            "registration_state",
            "profile_photo_status",
        )
    )
    for row in rows:
        labels = cast("list[dict[str, str]]", row["attendance_labels"])
        writer.writerow(
            tuple(
                _safe_csv_value(value)
                for value in (
                    edition_name,
                    edition_id,
                    generated_at,
                    row["reference"],
                    row["badge_name"],
                    row["badge_name_source"],
                    row["display_name"],
                    row["pronouns"],
                    "|".join(cast("list[str]", row["spoken_language_codes"])),
                    "|".join(cast("list[str]", row["spoken_languages"])),
                    row["country_code"],
                    "|".join(label["label"] for label in labels),
                    row["registration_state"],
                    row["profile_photo_status"],
                )
            )
        )
    return "\ufeff" + output.getvalue()
