"""Inspect a dedicated synthetic Workforce rehearsal without changing its database.

This facilitator tool produces minimized counts, never credentials or row contents.
It does not authorize access, prove browser actions, or certify a release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
FORMAT_VERSION = 1


def _identity() -> str:
    """Bind a report to this checker and the current exact adoption catalog.

    Returns
    -------
    str
        SHA-256 of the two source files; not a whole-application certification.
    """
    paths = (Path(__file__), ROOT / "src/maru/events/adoption.py")
    return hashlib.sha256(b"\0".join(path.read_bytes() for path in paths)).hexdigest()


def _inventory(namespaces: set[str]) -> dict[str, int]:
    """Count every concrete model, including implicit through models.

    Parameters
    ----------
    namespaces : set[str]
        Exact installed module labels from the adoption catalog.

    Returns
    -------
    dict[str, int]
        Model-label counts, without loading any row contents.
    """
    from django.apps import apps  # noqa: PLC0415 -- after explicit Django setup
    from django.db import connection  # noqa: PLC0415

    counts = {}
    for namespace in sorted(namespaces):
        for model in apps.get_app_config(namespace).get_models(
            include_auto_created=True
        ):
            metadata = model._meta  # noqa: SLF001 -- documented Django model metadata API
            if not metadata.proxy:
                table = connection.ops.quote_name(metadata.db_table)
                with connection.cursor() as cursor:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 -- quoted registry table, never caller SQL
                    counts[metadata.label_lower] = cursor.fetchone()[0]
    return dict(sorted(counts.items()))


def _final_checks(edition_id: UUID, volunteer_email: str) -> dict[str, bool]:
    """Check the exact volunteer's retained outcome in a single-edition fixture.

    Parameters
    ----------
    edition_id : UUID
        Edition copied from the ordinary browser journey.
    volunteer_email : str
        Reserved synthetic address supplied by the facilitator.

    Returns
    -------
    dict[str, bool]
        Named assertions with no names, reasons, passwords or person identifiers.
    """
    from django.apps import apps  # noqa: PLC0415 -- evaluator, not application API
    from django.db import connection  # noqa: PLC0415

    get = apps.get_model
    edition = (
        get("events", "EventEdition")
        .objects.only(
            "id", "organization_id", "adoption_profile_code", "adoption_profile_version"
        )
        .get(pk=edition_id)
    )
    person = (
        get("identity", "Account")
        .objects.only("id")
        .get(email=volunteer_email, account_kind="person", is_active=True)
    )
    scope = {"organization_id": edition.organization_id, "edition_id": edition.pk}
    assignments = get("workforce", "PositionAssignment").objects.filter(
        **scope, account_id=person.pk
    )
    assignment = (
        assignments.select_related("role_assignment")
        .only(
            "id",
            "position_id",
            "status",
            "approved_by_id",
            "proposed_by_id",
            "participation_capacity_id",
            "role_assignment__id",
            "role_assignment__revoked_at",
            "role_assignment__organization_id",
            "role_assignment__edition_id",
            "role_assignment__principal_id",
        )
        .get()
    )
    role = assignment.role_assignment
    demands = get("workforce", "ShiftDemand").objects.filter(
        **scope, position_id=assignment.position_id
    )
    completed = (
        demands.filter(status="completed").only("id", "ends_at", "completed_at").get()
    )
    commitments = get("workforce", "ShiftCommitment").objects.filter(
        **scope,
        demand_id=completed.pk,
        position_assignment_id=assignment.pk,
        account_id=person.pk,
    )
    commitment = commitments.only(
        "id", "status", "confirmed_by_id", "completed_at"
    ).get()
    with connection.cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        observed_now = cursor.fetchone()[0]
    return {
        "exact_workforce_only_profile": (
            edition.adoption_profile_code == "workforce_only"
            and edition.adoption_profile_version == 1
        ),
        "one_organization": get("organizations", "Organization").objects.count() == 1,
        "one_edition": get("events", "EventEdition").objects.count() == 1,
        "one_position": get("workforce", "Position").objects.filter(**scope).count()
        == 1,
        "one_assignment": get("workforce", "PositionAssignment").objects.count() == 1,
        "assignment_ended": assignment.status == "ended",
        "independent_assignment_decision": (
            assignment.approved_by_id is not None
            and assignment.approved_by_id != assignment.proposed_by_id
        ),
        "assignment_has_no_participation_capacity": (
            assignment.participation_capacity_id is None
        ),
        "linked_authority_revoked": (
            role is not None
            and role.revoked_at is not None
            and role.organization_id == edition.organization_id
            and role.edition_id == edition.pk
            and role.principal_id == person.pk
        ),
        "one_workforce_application": (
            get("workforce", "VolunteerApplication")
            .objects.filter(
                account_id=person.pk, opportunity__position_id=assignment.position_id
            )
            .count()
            == 1
        ),
        "no_unfinished_shift": not demands.exclude(
            status__in=("completed", "cancelled")
        ).exists(),
        "commitment_completed": commitment.status == "completed",
        "independent_shift_confirmation": (
            commitment.confirmed_by_id is not None
            and commitment.confirmed_by_id != person.pk
        ),
        "completion_after_real_end": (
            completed.completed_at is not None
            and completed.ends_at <= completed.completed_at <= observed_now
            and commitment.completed_at is not None
            and completed.ends_at <= commitment.completed_at <= observed_now
        ),
    }


def _read_snapshot(
    *,
    phase: str,
    platform_email: str,
    edition_id: UUID | None,
    volunteer_email: str | None,
) -> dict[str, Any]:
    """Read one consistent snapshot under PostgreSQL enforced read-only mode.

    Parameters
    ----------
    phase : str
        Either baseline before organization creation or final after completion.
    platform_email : str
        The fixture's active bootstrap administrator.
    edition_id : UUID | None
        Exact final edition; absent for a baseline.
    volunteer_email : str | None
        Exact final synthetic volunteer; absent for a baseline.

    Returns
    -------
    dict[str, Any]
        Minimal identity, model counts and named checks.

    Raises
    ------
    RuntimeError
        If the backend is not PostgreSQL or the caller has an open transaction.
    """
    from django.apps import apps  # noqa: PLC0415 -- after explicit setup
    from django.db import connection, transaction  # noqa: PLC0415

    from maru.events.adoption import (  # noqa: PLC0415
        ADOPTION_MODULE_NAMESPACE_CATALOG,
        WORKFORCE_ONLY_MODULES,
    )

    if connection.vendor != "postgresql" or connection.in_atomic_block:
        raise RuntimeError("Use a fresh PostgreSQL inspection connection.")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '15s'")
        account = apps.get_model("identity", "Account")
        platform = account.objects.only("id").get(
            email=platform_email, account_kind="platform_administrator", is_active=True
        )
        checks = {
            "only_reserved_synthetic_accounts": not account.objects.exclude(
                email__iendswith=".invalid"
            ).exists(),
            "platform_has_no_membership": not apps.get_model(
                "organizations", "OrganizationMembership"
            )
            .objects.filter(account_id=platform.pk)
            .exists(),
            "platform_has_no_position_assignment": not apps.get_model(
                "workforce", "PositionAssignment"
            )
            .objects.filter(account_id=platform.pk)
            .exists(),
            "platform_has_no_role_assignment": not apps.get_model(
                "authorization", "RoleAssignment"
            )
            .objects.filter(principal_id=platform.pk)
            .exists(),
            "platform_has_no_participation": not apps.get_model(
                "participation", "Participation"
            )
            .objects.filter(account_id=platform.pk)
            .exists(),
        }
        unadopted = set(ADOPTION_MODULE_NAMESPACE_CATALOG - WORKFORCE_ONLY_MODULES)
        counts = _inventory(unadopted)
        if phase == "baseline":
            checks.update(
                {
                    "no_organizations": not apps.get_model(
                        "organizations", "Organization"
                    ).objects.exists(),
                    "no_editions": not apps.get_model(
                        "events", "EventEdition"
                    ).objects.exists(),
                    "no_workforce_rows": not any(_inventory({"workforce"}).values()),
                }
            )
        else:
            if edition_id is None or volunteer_email is None:
                raise RuntimeError(
                    "Final inspection requires exact edition and volunteer."
                )
            checks.update(_final_checks(edition_id, volunteer_email))
        return {
            "format_version": FORMAT_VERSION,
            "phase": phase,
            "observed_at": datetime.now(UTC).isoformat(),
            "checker_identity": _identity(),
            # Random bootstrap account identity binds both phases to the same fixture.
            "fixture_identity": hashlib.sha256(
                str(platform.pk).encode("ascii")
            ).hexdigest(),
            "unadopted_modules": sorted(unadopted),
            "model_counts": counts,
            "checks": checks,
        }


def evaluate(snapshot: dict[str, Any], baseline: dict[str, Any] | None) -> list[str]:
    """Evaluate explicit counts and compare a final report with its passed baseline.

    Parameters
    ----------
    snapshot : dict[str, Any]
        Current snapshot produced by the read-only collector.
    baseline : dict[str, Any] | None
        Earlier successful report required for final inspection.

    Returns
    -------
    list[str]
        Failed check names only, with no row contents.
    """
    failed = [name for name, passed in snapshot["checks"].items() if passed is not True]
    failed.extend(
        "nonzero:" + name
        for name, count in snapshot["model_counts"].items()
        if type(count) is not int or count != 0
    )
    if not snapshot["model_counts"] or not snapshot["unadopted_modules"]:
        failed.append("empty_unadopted_inventory")
    if snapshot["phase"] == "final":
        if (
            baseline is None
            or baseline.get("phase") != "baseline"
            or baseline.get("status") != "passed"
        ):
            failed.append("missing_passed_baseline")
        else:
            failed.extend(
                "baseline_mismatch:" + key
                for key in (
                    "format_version",
                    "checker_identity",
                    "fixture_identity",
                    "unadopted_modules",
                )
                if baseline.get(key) != snapshot[key]
            )
            if baseline.get("model_counts") != snapshot["model_counts"]:
                failed.append("baseline_mismatch:model_counts")
            expected_checks = {
                "only_reserved_synthetic_accounts",
                "platform_has_no_membership",
                "platform_has_no_position_assignment",
                "platform_has_no_role_assignment",
                "platform_has_no_participation",
                "no_organizations",
                "no_editions",
                "no_workforce_rows",
            }
            if (
                set(baseline.get("checks", {})) != expected_checks
                or not all(value is True for value in baseline["checks"].values())
                or baseline.get("failures") != []
            ):
                failed.append("invalid_baseline_checks")
    return sorted(failed)


def main() -> int:
    """Collect one report with explicitly acknowledged synthetic inspection access.

    Returns
    -------
    int
        Zero for passed, one for a failed or blocked check; no retries or mutations.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "final"))
    parser.add_argument(
        "--confirm-dedicated-synthetic", action="store_true", required=True
    )
    parser.add_argument("--platform-email", required=True)
    parser.add_argument("--edition", type=UUID)
    parser.add_argument("--volunteer-email")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.platform_email.casefold().endswith(".invalid") or (
        args.volunteer_email
        and not args.volunteer_email.casefold().endswith(".invalid")
    ):
        parser.error("Only reserved .invalid synthetic addresses are supported.")
    if args.phase == "final" and not all(
        (args.edition, args.volunteer_email, args.baseline)
    ):
        parser.error("Final requires --edition, --volunteer-email and --baseline.")
    if args.phase == "baseline" and any(
        (args.edition, args.volunteer_email, args.baseline)
    ):
        parser.error(
            "Baseline must run before the exercise; omit final-only arguments."
        )
    # Never overwrite evidence, including when database setup or a query is blocked.
    with args.output.open("x", encoding="utf-8") as output:
        try:
            baseline = (
                json.loads(args.baseline.read_text(encoding="utf-8"))
                if args.baseline
                else None
            )
            sys.path.insert(0, str(ROOT / "src"))
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "maru.settings.local")
            import django  # noqa: PLC0415 -- explicit command, never at import time

            django.setup()
            report = _read_snapshot(
                phase=args.phase,
                platform_email=args.platform_email,
                edition_id=args.edition,
                volunteer_email=args.volunteer_email,
            )
            failures = evaluate(report, baseline)
            report.update(status="failed" if failures else "passed", failures=failures)
        except Exception as error:  # noqa: BLE001 -- no DSNs or row data in errors
            report = {
                "format_version": FORMAT_VERSION,
                "phase": args.phase,
                "status": "blocked",
                "error_type": type(error).__name__,
                "message": "Inspection unavailable; no absence or acceptance claim.",
            }
        json.dump(report, output, indent=2)
        output.write("\n")
    print(json.dumps({"status": report["status"], "report": str(args.output)}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
