"""Bind the reserved authority-cutover audit to its marker transaction."""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_guard_authority_provenance_activation_audit()
RETURNS trigger AS $$
BEGIN
    IF NEW.operation IS DISTINCT FROM
        'authorization.authority_provenance.activate'
    THEN
        RETURN NEW;
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM public.authorization_authorityprovenanceactivation AS marker
          JOIN public.identity_account AS actor
            ON actor.id = marker.activated_by_id
          JOIN public.authorization_provenanceactivationlatch AS latch
            ON latch.singleton IS TRUE
           AND latch.generation = 1
           AND latch.xmin = pg_current_xact_id()::xid
         WHERE marker.singleton IS TRUE
           AND marker.contract_version = 'adr-0044-v1'
           AND marker.policy_version = '2026-08-01.3'
           AND marker.reason ~ '[^[:space:]]'
           AND marker.xmin = pg_current_xact_id()::xid
           AND actor.account_kind = 'platform_administrator'
           AND actor.is_active IS TRUE
           AND NEW.principal_kind = 'platform_administrator'
           AND NEW.schema_version = 1
           AND NEW.principal_id = marker.activated_by_id
           AND NEW.principal_context_id IS NULL
           AND NEW.organization_id IS NULL
           AND NEW.event_edition_id IS NULL
           AND NEW.capability_code = 'authorization.manage_roles'
           AND NEW.target_type =
                'authorization.authority_provenance_activation'
           AND NEW.target_id IS NULL
           AND NEW.outcome = 'allow'
           AND NEW.reason_code = 'exact_lineage_cutover'
           AND NEW.correlation_id = marker.correlation_id
           AND NEW.occurred_at = marker.activated_at
           AND NEW.source_channel ~ '[^[:space:]]'
           AND NEW.causation_id IS NULL
           AND NEW.request_id IS NULL
           AND NEW.idempotency_key_hash = ''
           AND NEW.obligations = ARRAY[
               'reason',
               'audit',
               'stopped_processes'
           ]::varchar[]
           AND NEW.changed_fields = ARRAY[
               'authority_provenance_activation'
           ]::varchar[]
           AND NEW.delegated IS FALSE
           AND NEW.elevated IS TRUE
           AND NEW.break_glass IS FALSE
           AND NEW.safe_metadata = jsonb_build_object(
               'contract_version',
               'adr-0044-v1',
               'policy_version',
               '2026-08-01.3'
           )
           AND NEW.retention_class = 'security-extended'
           AND NEW.integrity_batch_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'reserved authority activation audit requires its exact marker'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

REVOKE ALL ON FUNCTION
    public.maru_guard_authority_provenance_activation_audit()
FROM PUBLIC;

CREATE TRIGGER authorization_activation_audit_reserved_guard
BEFORE INSERT ON public.audit_auditevent
FOR EACH ROW EXECUTE FUNCTION
    public.maru_guard_authority_provenance_activation_audit();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS authorization_activation_audit_reserved_guard
    ON public.audit_auditevent;
DROP FUNCTION IF EXISTS
    public.maru_guard_authority_provenance_activation_audit();
"""


EXACT_DURABLE_STATE_SQL = r"""
SELECT
    (SELECT COUNT(*)
       FROM public.authorization_authorityprovenanceactivation),
    (SELECT COUNT(*)
       FROM public.audit_auditevent
      WHERE operation = 'authorization.authority_provenance.activate'),
    (SELECT COUNT(*)
       FROM public.authorization_provenanceactivationlatch),
    EXISTS (
        SELECT 1
          FROM public.authorization_provenanceactivationlatch AS latch
         WHERE latch.singleton IS TRUE
           AND latch.generation = 0
    ),
    EXISTS (
        SELECT 1
          FROM public.authorization_authorityprovenanceactivation AS marker
          JOIN public.identity_account AS actor
            ON actor.id = marker.activated_by_id
          JOIN public.audit_auditevent AS event
            ON event.operation =
                'authorization.authority_provenance.activate'
           AND event.correlation_id = marker.correlation_id
           AND event.principal_id = marker.activated_by_id
           AND event.occurred_at = marker.activated_at
          JOIN public.authorization_provenanceactivationlatch AS latch
            ON latch.singleton IS TRUE
           AND latch.generation = 1
         WHERE marker.singleton IS TRUE
           AND marker.contract_version = 'adr-0044-v1'
           AND marker.policy_version = '2026-08-01.3'
           AND marker.reason ~ '[^[:space:]]'
           AND actor.account_kind = 'platform_administrator'
           AND actor.is_active IS TRUE
           AND event.principal_kind = 'platform_administrator'
           AND event.schema_version = 1
           AND event.principal_context_id IS NULL
           AND event.organization_id IS NULL
           AND event.event_edition_id IS NULL
           AND event.capability_code = 'authorization.manage_roles'
           AND event.target_type =
                'authorization.authority_provenance_activation'
           AND event.target_id IS NULL
           AND event.outcome = 'allow'
           AND event.reason_code = 'exact_lineage_cutover'
           AND event.source_channel ~ '[^[:space:]]'
           AND event.causation_id IS NULL
           AND event.request_id IS NULL
           AND event.idempotency_key_hash = ''
           AND event.obligations = ARRAY[
               'reason',
               'audit',
               'stopped_processes'
           ]::varchar[]
           AND event.changed_fields = ARRAY[
               'authority_provenance_activation'
           ]::varchar[]
           AND event.delegated IS FALSE
           AND event.elevated IS TRUE
           AND event.break_glass IS FALSE
           AND event.safe_metadata = jsonb_build_object(
               'contract_version',
               'adr-0044-v1',
               'policy_version',
               '2026-08-01.3'
           )
           AND event.retention_class = 'security-extended'
    )
"""


def _lock_activation_evidence(schema_editor) -> None:  # type: ignore[no-untyped-def]
    schema_editor.execute(
        """
        LOCK TABLE
            public.audit_auditevent,
            public.authorization_authorityprovenanceactivation,
            public.authorization_provenanceactivationlatch
        IN ACCESS EXCLUSIVE MODE
        """
    )


def _durable_state(schema_editor) -> tuple[int, int, int, bool, bool]:  # type: ignore[no-untyped-def]
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(EXACT_DURABLE_STATE_SQL)
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Authority activation evidence preflight returned no state.")
    return (int(row[0]), int(row[1]), int(row[2]), bool(row[3]), bool(row[4]))


def validate_reserved_activation_audit_upgrade(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    """Reject legacy reserved events that cannot be paired exactly."""

    del apps
    _lock_activation_evidence(schema_editor)
    marker_count, audit_count, latch_count, dormant_latch, exact_pair = _durable_state(
        schema_editor
    )
    dormant = (
        marker_count == 0 and audit_count == 0 and latch_count == 1 and dormant_latch
    )
    active = marker_count == 1 and audit_count == 1 and latch_count == 1 and exact_pair
    if not (dormant or active):
        raise RuntimeError(
            "Cannot install the reserved authority activation audit guard: "
            "existing cutover evidence is not one exact marker/audit pair. "
            "Restore one consistent database point before retrying."
        )


def refuse_reserved_activation_audit_guard_downgrade(  # type: ignore[no-untyped-def]
    apps,
    schema_editor,
) -> None:
    """Only a pristine dormant deployment may remove the reciprocal guard."""

    del apps
    _lock_activation_evidence(schema_editor)
    marker_count, audit_count, latch_count, dormant_latch, _exact_pair = _durable_state(
        schema_editor
    )
    if not (
        marker_count == 0 and audit_count == 0 and latch_count == 1 and dormant_latch
    ):
        raise RuntimeError(
            "Cannot remove the reserved authority activation audit guard after "
            "cutover evidence exists. Keep compatible code and fix forward, or "
            "restore the whole database to one consistent pre-activation point."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("audit", "0005_authority_activation_evidence_guards"),
        ("authorization", "0007_authority_provenance_activation_guards"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            validate_reserved_activation_audit_upgrade,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_reserved_activation_audit_guard_downgrade,
        ),
    ]
