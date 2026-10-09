"""Permit one retained Guidance adoption edge with exact authenticated responsibility."""

import re
from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_setup = import_module("maru.events.migrations.0020_announcements_setup_integrity")
_edition = import_module("maru.events.migrations.0010_workforce_adoption_profile")
_lineage = import_module(
    "maru.authorization.migrations.0039_accountable_representation_lineage"
)

MANIFEST_DIGESTS = {
    "announcements_only": "d4a87b37716542a0ac4c175751cc29554c0b86e574cce8b0bcddd91c6a6419e0",
    "guidance_only": "1708d962b1dce4a1682ca5d961b7f4db661588ebfa66f2a577bff69037dbeda7",
    "announcements_guidance": "67cd777e8f7e04b040a183c07a240a5afb6404152aa54b358fa427749f6f55a5",
}

FORWARD_SQL = (
    _setup.FORWARD_SQL.replace("Announcements", "Guidance")
    .replace("announcements", "guidance")
    .replace("'guidance_operators'", "'workspace_operators'")
)
REVERSE_SQL = _setup.REVERSE_SQL.replace("announcements", "guidance")

FORWARD_SQL += r"""
CREATE FUNCTION public.maru_guidance_activation_guard()
RETURNS trigger AS $$
DECLARE plan public.events_guidanceactivationrequest%ROWTYPE; edition public.events_eventedition%ROWTYPE;
 actor uuid; org uuid; v_edition_id uuid; trace uuid; audit_id uuid; target uuid; v_operation varchar; v_target_type varchar; cap varchar;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Guidance activation evidence is append-only' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='events_guidanceactivationrequest' THEN plan:=NEW;
 ELSE SELECT * INTO plan FROM public.events_guidanceactivationrequest WHERE id=NEW.request_id; END IF;
 IF plan.id IS NULL THEN RAISE EXCEPTION 'Guidance activation requires the original plan' USING ERRCODE='23514'; END IF;
 org:=plan.organization_id; v_edition_id:=plan.edition_id;
 PERFORM 1 FROM public.organizations_organization WHERE id=org AND lifecycle='active' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Guidance requires an active organization' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM public.organizations_conventionseries s JOIN public.events_eventedition e ON e.series_id=s.id WHERE e.id=v_edition_id AND e.organization_id=org AND s.organization_id=org AND s.is_active FOR UPDATE OF s;
 IF NOT FOUND THEN RAISE EXCEPTION 'Guidance requires an active same-parent series' USING ERRCODE='23514'; END IF;
 SELECT * INTO edition FROM public.events_eventedition e WHERE e.id=v_edition_id AND e.organization_id=org FOR UPDATE;
 IF edition.id IS NULL OR edition.lifecycle NOT IN ('draft','preparing','ready','live') OR edition.aggregate_version IS DISTINCT FROM plan.expected_edition_version OR edition.adoption_revision IS DISTINCT FROM plan.expected_adoption_revision OR edition.adoption_profile_code IS DISTINCT FROM plan.source_profile_code OR edition.adoption_profile_version IS DISTINCT FROM plan.source_profile_version OR plan.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'Guidance plan is stale or outside a writable edition' USING ERRCODE='23514'; END IF;
 IF NOT ((plan.source_profile_code='announcements_only' AND plan.target_profile_code='announcements_guidance' AND plan.purpose='initial') OR (plan.source_profile_code=plan.target_profile_code AND plan.source_profile_code IN ('guidance_only','announcements_guidance') AND (plan.purpose='recovery' OR (plan.source_profile_code='guidance_only' AND plan.expected_adoption_revision=0)))) OR plan.source_profile_version<>1 OR plan.target_profile_version<>1 THEN RAISE EXCEPTION 'This Guidance adoption edge is not supported' USING ERRCODE='23514'; END IF;
 IF (plan.purpose='initial') IS DISTINCT FROM (NOT EXISTS(SELECT 1 FROM public.authorization_guidanceteam t WHERE t.organization_id=org AND t.edition_id=v_edition_id)) THEN RAISE EXCEPTION 'Guidance recovery cannot replace original ownership' USING ERRCODE='23514'; END IF;
 IF plan.operator_a_id>=plan.operator_b_id OR plan.reason='' OR plan.reason ~ '[[:cntrl:]]' OR plan.request_digest !~ '^[0-9a-f]{64}$' OR plan.source_manifest_digest IS DISTINCT FROM (CASE plan.source_profile_code WHEN 'announcements_only' THEN 'd4a87b37716542a0ac4c175751cc29554c0b86e574cce8b0bcddd91c6a6419e0' WHEN 'guidance_only' THEN '1708d962b1dce4a1682ca5d961b7f4db661588ebfa66f2a577bff69037dbeda7' WHEN 'announcements_guidance' THEN '67cd777e8f7e04b040a183c07a240a5afb6404152aa54b358fa427749f6f55a5' ELSE NULL END) OR plan.target_manifest_digest IS DISTINCT FROM (CASE plan.target_profile_code WHEN 'guidance_only' THEN '1708d962b1dce4a1682ca5d961b7f4db661588ebfa66f2a577bff69037dbeda7' WHEN 'announcements_guidance' THEN '67cd777e8f7e04b040a183c07a240a5afb6404152aa54b358fa427749f6f55a5' ELSE NULL END) THEN RAISE EXCEPTION 'Guidance plan must retain exact immutable terms and manifests' USING ERRCODE='23514'; END IF;
 IF (SELECT count(DISTINCT a.account_id) FROM public.organizations_representationappointment a JOIN public.organizations_organizationrepresentation r ON r.id=a.representation_id JOIN public.authorization_authorityissuance i ON i.role_assignment_id=a.role_assignment_id JOIN public.identity_account p ON p.id=a.account_id WHERE r.id=plan.representation_id AND r.organization_id=org AND r.state='active' AND r.aggregate_version=plan.representation_version AND a.state='active' AND a.role='controller' AND a.account_id IN (plan.operator_a_id,plan.operator_b_id) AND p.is_active AND p.account_kind='person' AND p.email_verified_at IS NOT NULL AND public.maru_authority_issuance_valid_v1(i.ordinal,p.id,'organizations.manage_representation',org,NULL,NULL,NULL,clock_timestamp(),NULL,clock_timestamp(),TRUE,FALSE,ARRAY[]::bigint[],0)) <> 2 THEN RAISE EXCEPTION 'Guidance requires two current accepted organization roots' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='events_guidanceactivationrequest' THEN
  actor:=plan.proposed_by_id; v_operation:='events.guidance_adoption.propose'; v_target_type:='events.guidance_activation_request'; target:=plan.id; cap:='events.create';
 ELSIF TG_TABLE_NAME='events_guidanceactivationdecision' THEN
  actor:=NEW.actor_id; v_operation:=CASE WHEN NEW.accepted THEN 'events.guidance_adoption.accept' ELSE 'events.guidance_adoption.decline' END; v_target_type:='events.guidance_activation_request'; target:=plan.id; cap:='organizations.manage_representation';
  IF actor NOT IN (plan.operator_a_id,plan.operator_b_id) OR NEW.request_digest IS DISTINCT FROM plan.request_digest OR EXISTS(SELECT 1 FROM public.events_guidanceactivationreceipt r WHERE r.request_id=plan.id) OR EXISTS(SELECT 1 FROM public.events_guidanceactivationdecision d WHERE d.request_id=plan.id AND NOT d.accepted) THEN RAISE EXCEPTION 'Guidance requires an actual named independent acceptance' USING ERRCODE='23514'; END IF;
 ELSE
  actor:=NEW.applied_by_id; v_operation:='events.guidance_adoption.apply'; v_target_type:='events.guidance_activation_receipt'; target:=NEW.id; cap:='events.create';
  IF actor IS DISTINCT FROM plan.proposed_by_id OR NEW.organization_id IS DISTINCT FROM org OR NEW.edition_id IS DISTINCT FROM v_edition_id OR NEW.result_edition_version<>plan.expected_edition_version+1 OR NEW.result_adoption_revision<>plan.expected_adoption_revision+1 OR (SELECT count(*) FROM public.events_guidanceactivationdecision d WHERE d.request_id=plan.id AND d.actor_id IN (plan.operator_a_id,plan.operator_b_id) AND d.accepted AND d.request_digest=plan.request_digest AND d.created_at<=plan.expires_at)<>2 THEN RAISE EXCEPTION 'Guidance apply requires both exact actual decisions' USING ERRCODE='23514'; END IF;
 END IF;
 IF cap='events.create' AND NOT EXISTS(SELECT 1 FROM public.identity_account p WHERE p.id=actor AND p.is_active AND p.account_kind='platform_administrator') THEN RAISE EXCEPTION 'Guidance setup requires current platform oversight' USING ERRCODE='23514'; END IF;
 audit_id:=NEW.source_audit_id; trace:=NEW.correlation_id;
 IF NOT EXISTS(SELECT 1 FROM public.audit_auditevent a JOIN public.audit_auditnativemutationwitness w ON w.audit_event_id=a.id AND w.transaction_stamp=public.maru_audit_current_native_transaction_stamp() WHERE a.id=audit_id AND a.principal_kind='account' AND a.principal_id=actor AND a.principal_context_id IS NULL AND a.organization_id=org AND a.event_edition_id=v_edition_id AND a.operation=v_operation AND a.capability_code=cap AND a.target_type=v_target_type AND a.target_id=target AND a.outcome='allow' AND a.correlation_id=trace AND a.reason_code='accepted_guidance_responsibility') THEN RAISE EXCEPTION 'Guidance activation requires its exact live native audit' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guidance_activation_graph_guard()
RETURNS trigger AS $$
DECLARE plan public.events_guidanceactivationrequest%ROWTYPE; latest public.events_guidanceactivationreceipt%ROWTYPE;
 edition public.events_eventedition%ROWTYPE; audit_id uuid; trace uuid; operation varchar; v_aggregate_id uuid; event_actor uuid; event_type varchar;
BEGIN
 IF TG_TABLE_NAME='events_eventedition' THEN SELECT * INTO edition FROM public.events_eventedition WHERE id=NEW.id;
 ELSE
  IF TG_TABLE_NAME='events_guidanceactivationrequest' THEN plan:=NEW; ELSE SELECT * INTO plan FROM public.events_guidanceactivationrequest WHERE id=NEW.request_id; END IF;
  SELECT * INTO edition FROM public.events_eventedition WHERE id=plan.edition_id;
  audit_id:=NEW.source_audit_id; trace:=NEW.correlation_id; v_aggregate_id:=NEW.id;
  IF TG_TABLE_NAME='events_guidanceactivationrequest' THEN event_actor:=NEW.proposed_by_id; event_type:='events.guidance_activation_request'; operation:='proposed'; ELSIF TG_TABLE_NAME='events_guidanceactivationdecision' THEN event_actor:=NEW.actor_id; event_type:='events.guidance_activation_decision'; operation:=CASE WHEN NEW.accepted THEN 'accepted' ELSE 'declined' END; ELSE event_actor:=NEW.applied_by_id; event_type:='events.guidance_activation_receipt'; operation:=CASE WHEN plan.purpose='recovery' THEN 'recovered' ELSE 'activated' END; END IF;
  IF NOT EXISTS(SELECT 1 FROM public.effects_domainevent e JOIN public.effects_outboxmessage o ON o.event_id=e.id AND o.destination='internal' WHERE e.event_name='events.guidance_adoption.changed.v1' AND e.schema_version=1 AND e.aggregate_version=1 AND e.actor_kind='account' AND e.actor_id=event_actor AND e.causation_id=audit_id AND e.correlation_id=trace AND e.organization_id=plan.organization_id AND e.event_edition_id=plan.edition_id AND e.aggregate_type=event_type AND e.aggregate_id=v_aggregate_id AND e.payload=jsonb_build_object('operation',operation)) THEN RAISE EXCEPTION 'Guidance activation requires its minimized event and outbox' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='events_guidanceactivationreceipt' THEN
   IF NOT EXISTS(SELECT 1 FROM public.authorization_guidanceauthoritysetupreceipt s JOIN public.authorization_guidanceteam t ON t.id=s.team_id WHERE s.activation_id=NEW.id AND t.organization_id=NEW.organization_id AND t.edition_id=NEW.edition_id) THEN RAISE EXCEPTION 'Guidance adoption receipt requires its actual qualified authority outputs' USING ERRCODE='23514'; END IF;
   IF NEW.result_adoption_revision>1 AND NOT EXISTS(SELECT 1 FROM public.events_guidanceactivationreceipt previous JOIN public.events_guidanceactivationrequest p ON p.id=previous.request_id WHERE previous.edition_id=NEW.edition_id AND previous.result_adoption_revision=NEW.result_adoption_revision-1 AND previous.result_edition_version<=plan.expected_edition_version AND p.target_profile_code=plan.source_profile_code AND p.target_profile_version=plan.source_profile_version) THEN RAISE EXCEPTION 'Guidance adoption revisions require their exact retained predecessor' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF edition.adoption_revision>0 THEN
  SELECT * INTO latest FROM public.events_guidanceactivationreceipt WHERE edition_id=edition.id ORDER BY result_adoption_revision DESC LIMIT 1;
  SELECT * INTO plan FROM public.events_guidanceactivationrequest WHERE id=latest.request_id;
  IF latest.id IS NULL OR edition.adoption_revision IS DISTINCT FROM latest.result_adoption_revision OR edition.aggregate_version<latest.result_edition_version OR edition.adoption_profile_code IS DISTINCT FROM plan.target_profile_code OR edition.adoption_profile_version IS DISTINCT FROM plan.target_profile_version THEN RAISE EXCEPTION 'Guidance receipt and persisted adoption head must agree' USING ERRCODE='23514'; END IF;
 ELSIF EXISTS(SELECT 1 FROM public.events_guidanceactivationreceipt WHERE edition_id=edition.id) THEN RAISE EXCEPTION 'Guidance receipt cannot substitute for a missing adoption transition' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guidance_activation_no_truncate()
RETURNS trigger AS $$
BEGIN
 IF public.maru_authority_provenance_test_reset_allowed() THEN RETURN NULL; END IF;
 RAISE EXCEPTION 'Guidance adoption evidence cannot be truncated' USING ERRCODE='23514';
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
"""


_RELATIONS = (
    "events_guidanceactivationrequest",
    "events_guidanceactivationdecision",
    "events_guidanceactivationreceipt",
)
for _relation in _RELATIONS:
    FORWARD_SQL += f"CREATE TRIGGER {_relation}_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{_relation} FOR EACH ROW EXECUTE FUNCTION public.maru_guidance_activation_guard();\n"
    FORWARD_SQL += f"CREATE CONSTRAINT TRIGGER {_relation}_graph AFTER INSERT ON public.{_relation} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.maru_guidance_activation_graph_guard();\n"
    FORWARD_SQL += f"CREATE TRIGGER {_relation}_no_truncate BEFORE TRUNCATE ON public.{_relation} FOR EACH STATEMENT EXECUTE FUNCTION public.maru_guidance_activation_no_truncate();\n"
    for _suffix in ("guard", "graph", "no_truncate"):
        REVERSE_SQL += f"DROP TRIGGER {_relation}_{_suffix} ON public.{_relation};\n"
FORWARD_SQL += "CREATE CONSTRAINT TRIGGER events_guidance_adoption_head AFTER INSERT OR UPDATE ON public.events_eventedition DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.maru_guidance_activation_graph_guard();\n"
REVERSE_SQL += (
    "DROP TRIGGER events_guidance_adoption_head ON public.events_eventedition;\n"
)
for _identity in (
    "maru_guidance_activation_guard()",
    "maru_guidance_activation_graph_guard()",
    "maru_guidance_activation_no_truncate()",
):
    FORWARD_SQL += f"REVOKE ALL ON FUNCTION public.{_identity} FROM PUBLIC;\n"
    REVERSE_SQL += f"DROP FUNCTION public.{_identity};\n"


# This predecessor trigger is invoked by PostgreSQL, not by the runtime login.
# Keep this hardening on unused reversal: the predecessor function survives, and
# restoring its older body must not reopen default PUBLIC execution.
FORWARD_SQL += (
    "REVOKE ALL ON FUNCTION "
    "public.maru_validate_edition_aggregate_version() FROM PUBLIC;\n"
)


def previous_source() -> str:
    match = re.search(
        r"CREATE OR REPLACE FUNCTION public.maru_validate_edition_aggregate_version\(\).*?AS \$\$(.*?)\$\$",
        _edition.FORWARD_SQL,
        re.DOTALL,
    )
    if match is None:
        raise RuntimeError("Frozen edition adoption guard is unavailable.")
    return match[1]


def next_source() -> str:
    source = previous_source()
    source = _lineage._once(
        source,
        """        IF NEW.aggregate_version != 1 THEN""",
        """        IF NEW.adoption_revision <> 0 OR NEW.adoption_profile_code='announcements_guidance' THEN
            RAISE EXCEPTION 'Combined Guidance adoption requires its accepted expansion' USING ERRCODE='23514';
        END IF;
        IF EXISTS(SELECT 1 FROM public.organizations_organizationrepresentation r WHERE r.organization_id=NEW.organization_id AND r.code='workspace_operators') AND (NEW.adoption_profile_code,NEW.adoption_profile_version) IS DISTINCT FROM ('guidance_only',1) THEN
            RAISE EXCEPTION 'Workspace operators support fresh Guidance only' USING ERRCODE='23514';
        END IF;
        IF NEW.aggregate_version != 1 THEN""",
    )
    source = _lineage._once(
        source,
        """       OR NEW.adoption_profile_code IS DISTINCT FROM OLD.adoption_profile_code
       OR NEW.adoption_profile_version IS DISTINCT FROM OLD.adoption_profile_version
""",
        "",
    )
    return _lineage._once(
        source,
        """    profile_changed :=""",
        """    IF NEW.adoption_profile_code IS DISTINCT FROM OLD.adoption_profile_code OR NEW.adoption_profile_version IS DISTINCT FROM OLD.adoption_profile_version OR NEW.adoption_revision IS DISTINCT FROM OLD.adoption_revision THEN
        IF NEW.adoption_revision <> OLD.adoption_revision+1 OR NEW.aggregate_version <> OLD.aggregate_version+1
           OR (to_jsonb(NEW)-ARRAY['adoption_profile_code','adoption_profile_version','adoption_revision','aggregate_version','updated_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['adoption_profile_code','adoption_profile_version','adoption_revision','aggregate_version','updated_at'])
           OR NOT EXISTS(
             SELECT 1 FROM public.events_guidanceactivationreceipt receipt JOIN public.events_guidanceactivationrequest plan ON plan.id=receipt.request_id JOIN public.audit_auditnativemutationwitness witness ON witness.audit_event_id=receipt.source_audit_id AND witness.transaction_stamp=public.maru_audit_current_native_transaction_stamp()
              WHERE receipt.edition_id=NEW.id AND receipt.organization_id=NEW.organization_id
                AND receipt.result_edition_version=NEW.aggregate_version AND receipt.result_adoption_revision=NEW.adoption_revision
                AND plan.expected_edition_version=OLD.aggregate_version AND plan.expected_adoption_revision=OLD.adoption_revision
                AND plan.source_profile_code=OLD.adoption_profile_code AND plan.source_profile_version=OLD.adoption_profile_version
                AND plan.target_profile_code=NEW.adoption_profile_code AND plan.target_profile_version=NEW.adoption_profile_version
           )
        THEN RAISE EXCEPTION 'Adoption changes require the exact live accepted transition receipt' USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END IF;

    profile_changed :=""",
    )


def _replace(schema_editor: Any, *, forward: bool) -> None:
    identity = "maru_validate_edition_aggregate_version()"
    previous, desired = previous_source(), next_source()
    if not forward:
        previous, desired = desired, previous
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("LOCK TABLE public.events_eventedition IN ACCESS EXCLUSIVE MODE")
        before = _lineage._state(cursor, identity)
        if before[3] != previous:
            raise RuntimeError("Refusing changed native edition adoption source.")
        cursor.execute(
            "CREATE OR REPLACE FUNCTION public.maru_validate_edition_aggregate_version() RETURNS trigger AS $$"
            + desired
            + "$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;"
        )
        after = _lineage._state(cursor, identity)
        if before[:3] != after[:3] or before[4:] != after[4:] or after[3] != desired:
            raise RuntimeError(
                "Edition adoption changed native helper identity or ACL."
            )


def install(apps: Any, schema_editor: Any) -> None:
    del apps
    _replace(schema_editor, forward=True)


def restore(apps: Any, schema_editor: Any) -> None:
    del apps
    _replace(schema_editor, forward=False)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0022_guidance_adoption_profiles"),
        ("authorization", "0047_guidance_qualified_lineage"),
    ]
    operations: ClassVar[list[object]] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
