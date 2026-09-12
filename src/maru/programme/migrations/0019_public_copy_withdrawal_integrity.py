"""Require exact native copy withdrawal and same-transaction release invalidation."""

import re
from importlib import import_module
from typing import ClassVar

from django.db import migrations

_operational = import_module("maru.programme.migrations.0017_operational_public_review")
_decisions = import_module(
    "maru.programme.migrations.0014_placement_decision_integrity"
)
_native = import_module("maru.programme.migrations.0016_release_dependency_mutations")
_schema = import_module("maru.programme.migrations.0018_public_copy_withdrawal")
_old_receipt = _operational._receipt  # noqa: SLF001 - frozen historical SQL
_old_evidence = _decisions._evidence  # noqa: SLF001 - frozen historical SQL
_independent = (
    "'public_rendition_record', 'accessibility_fit_record', 'staffing_absence_record'"
)
_expanded = "'public_rendition_withdraw', " + _independent
_receipt = _old_receipt.replace(_independent, _expanded)
_result_marker = "    ELSIF NEW.operation = 'public_rendition_record' THEN"
if _receipt.count(_result_marker) != 1:
    raise RuntimeError("The frozen Programme public-copy result proof changed.")
_receipt = _receipt.replace(
    _result_marker,
    """    ELSIF NEW.operation = 'public_rendition_withdraw' THEN
        SELECT EXISTS (
            SELECT 1 FROM public.programme_programmepublicrenditionwithdrawal withdrawal
            WHERE withdrawal.id = NEW.result_object_id
              AND withdrawal.item_id = NEW.item_id
              AND withdrawal.organization_id = NEW.organization_id
              AND withdrawal.edition_id = NEW.edition_id
              AND withdrawal.item_version = NEW.resulting_item_version
              AND withdrawal.actor_id = NEW.actor_id AND withdrawal.reason = NEW.reason
        ) INTO result_matches;
    ELSIF NEW.operation = 'public_rendition_record' THEN""",
)
_version_marker = "    ELSIF NEW.operation IN (" + _expanded + ") THEN"
if _receipt.count(_version_marker) != 1:
    raise RuntimeError("The frozen Programme independent-version branch changed.")
_receipt = _receipt.replace(
    _version_marker,
    """    ELSIF NEW.operation = 'public_rendition_withdraw' THEN
        IF NEW.resulting_control_version IS NOT NULL
           OR NEW.expected_version <> NEW.resulting_item_version THEN
            RAISE EXCEPTION 'copy withdrawal must preserve the current item version'
              USING ERRCODE = '23514';
        END IF;
"""
    + _version_marker,
)
_closed = (
    ") THEN\n        RAISE EXCEPTION "
    "'Closed Programme planning admits only exact personal withdrawal'"
)
if _receipt.count(_closed) != 1:
    raise RuntimeError("The frozen Programme closed-edition receipt branch changed.")
_receipt = _receipt.replace(
    _closed,
    ") AND NEW.operation <> 'public_rendition_withdraw' THEN\n"
    "        RAISE EXCEPTION "
    "'Closed Programme planning admits only exact personal withdrawal'",
)
_evidence = _old_evidence.replace(_independent, _expanded)


def _native_function(name: str) -> str:
    match = re.search(
        rf"CREATE FUNCTION public\.{re.escape(name)}\(.*?"
        r"SET search_path = pg_catalog, public, pg_temp;",
        _native.FORWARD_SQL,
        re.DOTALL,
    )
    if match is None:
        raise RuntimeError("Missing frozen Programme native release function.")
    return match.group().replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


_old_sources = _native_function("maru_programme_release_mutation_sources")
_source_marker = "    WHERE state <> 'confirmed';"
if _old_sources.count(_source_marker) != 1:
    raise RuntimeError("The frozen native Programme source selection changed.")
_sources = _old_sources.replace(
    _source_marker,
    """    WHERE state <> 'confirmed'
    UNION ALL
    SELECT 'programme_public_copy'::text, withdrawal.rendition_id
    FROM receipt
    JOIN public.programme_programmepublicrenditionwithdrawal withdrawal
      ON withdrawal.id = receipt.result_object_id
     AND withdrawal.item_id = receipt.item_id
     AND withdrawal.organization_id = receipt.organization_id
     AND withdrawal.edition_id = receipt.edition_id
     AND withdrawal.item_version = receipt.resulting_item_version
     AND withdrawal.actor_id = receipt.actor_id AND withdrawal.reason = receipt.reason
    WHERE receipt.operation = 'public_rendition_withdraw';""",
)
_old_native_guard = _native_function("maru_programme_release_receipt_guard")
_native_guard = _old_native_guard.replace(
    "'accessibility_fit_record', 'staffing_absence_record'",
    "'accessibility_fit_record', 'staffing_absence_record', "
    "'public_rendition_withdraw'",
)

WITHDRAWAL_SQL = r"""
CREATE FUNCTION public.maru_programme_public_withdrawal_guard()
RETURNS trigger AS $$
DECLARE item_row record; copy_row record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'public copy withdrawal is retained immutable history'
          USING ERRCODE = '23514';
    END IF;
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'copy withdrawal requires READ COMMITTED'
          USING ERRCODE = '23514';
    END IF;
    SELECT * INTO item_row FROM public.programme_programmeitem
    WHERE id = NEW.item_id FOR UPDATE;
    SELECT * INTO copy_row FROM public.programme_programmepublicrendition
    WHERE id = NEW.rendition_id FOR UPDATE;
    IF item_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR item_row.edition_id IS DISTINCT FROM NEW.edition_id
       OR item_row.aggregate_version IS DISTINCT FROM NEW.item_version
       OR copy_row.item_id IS DISTINCT FROM NEW.item_id
       OR copy_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR copy_row.edition_id IS DISTINCT FROM NEW.edition_id
       OR NOT EXISTS (
        SELECT 1 FROM public.events_eventedition edition
        JOIN public.organizations_conventionseries series
          ON series.id = edition.series_id
         AND series.organization_id = edition.organization_id
        WHERE edition.id = NEW.edition_id
          AND edition.organization_id = NEW.organization_id
       ) OR NOT EXISTS (
        SELECT 1 FROM public.identity_account WHERE id = NEW.actor_id AND is_active
          AND email_verified_at IS NOT NULL AND account_kind = 'person'
        FOR KEY SHARE NOWAIT
       ) OR btrim(NEW.reason) = '' OR NEW.reason <> normalize(NEW.reason, NFC)
         OR NEW.reason ~ '[[:cntrl:]]' THEN
        RAISE EXCEPTION 'copy withdrawal requires exact native scope and attribution'
          USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_programme_public_withdrawal_evidence()
RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.programme_programmecommandreceipt receipt
        JOIN public.programme_programmeitem item ON item.id = receipt.item_id
        JOIN public.audit_auditevent audit
          ON audit.organization_id = receipt.organization_id
         AND audit.event_edition_id = receipt.edition_id
         AND audit.principal_kind = 'account' AND audit.principal_id = receipt.actor_id
         AND audit.target_type = 'programme.item' AND audit.target_id = receipt.item_id
         AND audit.operation = 'programme.command.public_rendition_withdraw'
         AND audit.capability_code = 'programme.approve_public_copy'
         AND audit.correlation_id = receipt.correlation_id
         AND audit.source_channel = receipt.source_channel
         AND audit.idempotency_key_hash = encode(sha256(convert_to(
             receipt.idempotency_key::text, 'UTF8')), 'hex')
         AND audit.occurred_at = NEW.occurred_at AND audit.outcome = 'allow'
         AND 'audit' = ANY(audit.obligations)
        JOIN public.audit_auditnativemutationwitness witness
          ON witness.audit_event_id = audit.id
         AND witness.transaction_stamp =
             public.maru_audit_current_native_transaction_stamp()
        JOIN public.effects_domainevent event ON event.causation_id = audit.id
         AND event.event_name = 'programme.item.changed.v1' AND event.schema_version = 1
         AND event.organization_id = receipt.organization_id
         AND event.event_edition_id = receipt.edition_id
         AND event.aggregate_type = 'programme.public_copy_withdrawal'
         AND event.aggregate_id = NEW.rendition_id AND event.aggregate_version = 1
         AND event.actor_kind = 'account' AND event.actor_id = receipt.actor_id
         AND event.correlation_id = receipt.correlation_id
         AND event.occurred_at = NEW.occurred_at
         AND event.payload = jsonb_build_object(
             'action', 'withdraw_public_copy', 'layer', 'public_copy',
             'item_kind', item.kind, 'provenance', item.provenance_kind,
             'lifecycle', item.lifecycle, 'concern', 'public_copy'
         )
        JOIN public.effects_outboxmessage outbox ON outbox.event_id = event.id
         AND outbox.organization_id = receipt.organization_id
         AND outbox.destination = 'internal' AND outbox.workload_pool = 'default'
        WHERE receipt.operation = 'public_rendition_withdraw'
          AND receipt.result_object_id = NEW.id AND receipt.item_id = NEW.item_id
          AND receipt.organization_id = NEW.organization_id
          AND receipt.edition_id = NEW.edition_id AND receipt.actor_id = NEW.actor_id
          AND receipt.reason = NEW.reason
          AND receipt.expected_version = NEW.item_version
          AND receipt.resulting_item_version = NEW.item_version
          AND receipt.resulting_control_version IS NULL
    ) THEN
        RAISE EXCEPTION 'copy withdrawal lacks its exact new receipt audit and effects'
          USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER programme_public_withdrawal_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.programme_programmepublicrenditionwithdrawal
FOR EACH ROW EXECUTE FUNCTION public.maru_programme_public_withdrawal_guard();
CREATE CONSTRAINT TRIGGER programme_public_withdrawal_evidence
AFTER INSERT ON public.programme_programmepublicrenditionwithdrawal
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_programme_public_withdrawal_evidence();
CREATE TRIGGER programme_public_withdrawal_no_truncate
BEFORE TRUNCATE ON public.programme_programmepublicrenditionwithdrawal
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();
REVOKE ALL ON FUNCTION public.maru_programme_public_withdrawal_guard(),
    public.maru_programme_public_withdrawal_evidence() FROM PUBLIC;
"""
FORWARD_SQL = "\n".join(  # noqa: FLY002 - preserve ordered frozen SQL fragments.
    (_receipt, _evidence, _sources, _native_guard, WITHDRAWAL_SQL)
)
REVERSE_SQL = "\n".join(  # noqa: FLY002 - ordered reciprocal recovery fragments.
    (
        "DROP TRIGGER programme_public_withdrawal_guard "
        "ON public.programme_programmepublicrenditionwithdrawal;",
        "DROP TRIGGER programme_public_withdrawal_evidence "
        "ON public.programme_programmepublicrenditionwithdrawal;",
        "DROP TRIGGER programme_public_withdrawal_no_truncate "
        "ON public.programme_programmepublicrenditionwithdrawal;",
        "DROP FUNCTION public.maru_programme_public_withdrawal_evidence();",
        "DROP FUNCTION public.maru_programme_public_withdrawal_guard();",
        _old_native_guard,
        _old_sources,
        _old_evidence,
        _old_receipt,
    )
)


class Migration(migrations.Migration):
    """Protect exact disclosure withdrawal while preserving operational cleanup."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("programme", "0018_public_copy_withdrawal"),
        ("scheduling", "0017_atomic_release_graph"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, _schema.refuse_used_copy_withdrawal_downgrade
        ),
    ]
