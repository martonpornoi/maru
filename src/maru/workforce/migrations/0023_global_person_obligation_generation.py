"""Join exact native work changes to minimized global person-work freshness."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_previous = import_module("maru.workforce.migrations.0022_release_dependency_mutations")


def _definition(name: str) -> str:
    start = _previous.FORWARD_SQL.index(f"CREATE FUNCTION public.{name}(")
    ending = "SET search_path = pg_catalog, public, pg_temp;"
    end = _previous.FORWARD_SQL.index(ending, start) + len(ending)
    return _previous.FORWARD_SQL[start:end].replace(
        "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
    )


def _replace(statement: str, original: str, replacement: str) -> str:
    if statement.count(original) != 1:
        raise RuntimeError("The frozen Workforce release source definition changed.")
    return statement.replace(original, replacement)


_sources = _definition("maru_workforce_release_mutation_sources")
_valid = _definition("maru_workforce_release_change_valid")
_guard = _definition("maru_workforce_release_receipt_guard")
_original = f"{_sources}\n{_valid}\n{_guard}"
_start = _sources.index("        SELECT 'commitment',")
_end = _sources.index("        UNION ALL", _start)
_commitment = _sources[_start:_end]
_person = _replace(
    _commitment,
    "'workforce_demand', receipt.demand_id",
    "'workforce_person_obligations', commitment.account_id",
)
_sources = _replace(
    _sources, _commitment, _commitment + "        UNION ALL\n" + _person
)
_sources = _replace(
    _sources,
    "           receipt.organization_id, receipt.edition_id\n"
    "    FROM receipts receipt JOIN native event",
    "           CASE WHEN receipt.kind = 'workforce_person_obligations' "
    "THEN NULL::uuid\n"
    "                ELSE receipt.organization_id END,\n"
    "           CASE WHEN receipt.kind = 'workforce_person_obligations' "
    "THEN NULL::uuid\n"
    "                ELSE receipt.edition_id END\n"
    "    FROM receipts receipt JOIN native event",
)
_valid = _replace(
    _valid,
    "reference.organization_id = organization AND reference.edition_id = edition",
    "reference.organization_id IS NOT DISTINCT FROM organization\n"
    "          AND reference.edition_id IS NOT DISTINCT FROM edition",
)
_person_evidence = r"""
    IF TG_ARGV[0] = 'commitment' THEN
        SELECT account_id INTO source FROM public.workforce_shiftcommitment
        WHERE id = NEW.commitment_id AND demand_id = NEW.demand_id
          AND organization_id = NEW.organization_id AND edition_id = NEW.edition_id;
        SELECT id INTO tracked_dependency_id
        FROM public.scheduling_schedulingreleasedependencykey
        WHERE kind = 'workforce_person_obligations' AND source_id = source;
        IF tracked_dependency_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.scheduling_schedulingreleasedependencychange change
            JOIN public.audit_auditnativemutationwitness witness
              ON witness.audit_event_id = change.source_audit_id
            CROSS JOIN LATERAL
              public.maru_workforce_release_mutation_sources(
                  witness.audit_event_id) reference
            WHERE change.dependency_id = tracked_dependency_id
              AND witness.transaction_stamp =
                  public.maru_audit_current_native_transaction_stamp()
              AND reference.receipt_kind = 'commitment'
              AND reference.receipt_id = NEW.id
              AND reference.kind = 'workforce_person_obligations'
              AND reference.source_id = source
              AND reference.organization_id IS NULL AND reference.edition_id IS NULL
        ) THEN
            RAISE EXCEPTION
                'Workforce person change requires its native release invalidation'
                USING ERRCODE = '23514';
        END IF;
    END IF;
"""
_guard = _replace(_guard, "    RETURN NULL;", _person_evidence + "    RETURN NULL;")
_serialization = r"""
CREATE FUNCTION public.maru_workforce_release_person_guard()
RETURNS trigger AS $$
DECLARE person uuid;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Workforce person obligations require READ COMMITTED'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.account_id IS DISTINCT FROM OLD.account_id THEN
        RAISE EXCEPTION 'Workforce obligation identity is immutable'
            USING ERRCODE = '23514';
    END IF;
    person := CASE WHEN TG_OP = 'DELETE' THEN OLD.account_id ELSE NEW.account_id END;
    -- Native commands already hold their whole person union before work rows.
    -- An inverted raw writer must not wait here while holding a narrower row.
    PERFORM id FROM public.identity_account WHERE id = person FOR UPDATE NOWAIT;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workforce obligation requires its exact account'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN
        IF EXISTS (SELECT 1 FROM public.scheduling_schedulingreleasedependencykey
                   WHERE kind = 'workforce_person_obligations'
                     AND source_id = person) THEN
            RAISE EXCEPTION 'Tracked Workforce obligations are retained'
                USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_workforce_release_person_guard() FROM PUBLIC;
CREATE TRIGGER aa0_workforce_release_person_serialization
BEFORE INSERT OR UPDATE OR DELETE ON public.workforce_shiftcommitment
FOR EACH ROW EXECUTE FUNCTION public.maru_workforce_release_person_guard();
"""
FORWARD_SQL = f"{_sources}\n{_valid}\n{_guard}\n{_serialization}"
REVERSE_SQL = (
    """
DROP TRIGGER aa0_workforce_release_person_serialization
ON public.workforce_shiftcommitment;
DROP FUNCTION public.maru_workforce_release_person_guard();
"""
    + _original
)


def refuse_tracked_person_work_downgrade(apps: Any, schema_editor: Any) -> None:
    """Preserve native global generation evidence after its first capture."""
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingreleasedependencykey "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if (
        apps.get_model("scheduling", "SchedulingReleaseDependencyKey")
        .objects.filter(kind="workforce_person_obligations")
        .exists()
    ):
        raise RuntimeError(
            "Global person-work sources exist; retain native guards and fix forward."
        )


class Migration(migrations.Migration):
    """Advance no foreign-tenant key and disclose no foreign work identity."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("workforce", "0022_release_dependency_mutations"),
        ("scheduling", "0013_person_obligation_dependency_kind"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_tracked_person_work_downgrade
        ),
    ]
