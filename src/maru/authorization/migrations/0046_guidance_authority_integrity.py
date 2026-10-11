"""Qualify the closed Guidance role graph through the existing exact authority lineage."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_previous = import_module(
    "maru.authorization.migrations.0044_workspace_operator_lineage"
)
_lineage = import_module(
    "maru.authorization.migrations.0039_accountable_representation_lineage"
)

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_guidance_recipe_capabilities(recipe character varying)
RETURNS character varying[] AS $$
SELECT CASE recipe
 WHEN 'guidance-access-controller' THEN ARRAY['authorization.manage_guidance_access']::varchar[]
 WHEN 'guidance-operator' THEN ARRAY['knowledge.view_current','knowledge.view_working','knowledge.compose','knowledge.review','knowledge.withdraw','knowledge.manage_settings','knowledge.export_evidence']::varchar[]
 WHEN 'guidance-reader' THEN ARRAY['knowledge.view_current']::varchar[]
 WHEN 'guidance-editor' THEN ARRAY['knowledge.view_current','knowledge.view_working','knowledge.compose']::varchar[]
 WHEN 'guidance-reviewer' THEN ARRAY['knowledge.view_current','knowledge.view_working','knowledge.review']::varchar[]
 ELSE NULL END;
$$ LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guidance_required_control(target_kind character varying, target_id uuid)
RETURNS character varying AS $$
DECLARE bundle_code varchar; codes varchar[]; direct_code varchar;
BEGIN
 IF target_kind = 'capability_grant' THEN
   SELECT capability_code INTO direct_code FROM public.authorization_capabilitygrant WHERE id=target_id;
   IF NOT FOUND THEN RETURN 'guidance.target_unavailable'; END IF;
   IF direct_code = 'authorization.manage_guidance_access' OR direct_code LIKE 'knowledge.%' THEN
     RETURN 'guidance.direct_grants_forbidden';
   END IF;
   RETURN 'authorization.grant_direct';
 END IF;
 IF target_kind = 'role_bundle' THEN
   SELECT code, capability_codes INTO bundle_code, codes FROM public.authorization_rolebundle WHERE id=target_id;
 ELSE
   SELECT b.code, b.capability_codes INTO bundle_code, codes FROM public.authorization_roleassignment a JOIN public.authorization_rolebundle b ON b.id=a.role_bundle_id WHERE a.id=target_id;
 END IF;
 IF NOT FOUND THEN RETURN 'guidance.target_unavailable'; END IF;
 IF public.maru_guidance_recipe_capabilities(bundle_code) IS NULL AND NOT COALESCE(codes && ARRAY['authorization.manage_guidance_access','knowledge.view_current','knowledge.view_working','knowledge.compose','knowledge.review','knowledge.withdraw','knowledge.manage_settings','knowledge.export_evidence']::varchar[],FALSE) THEN
   RETURN 'authorization.manage_roles';
 END IF;
 RETURN CASE WHEN target_kind='role_bundle' OR bundle_code='guidance-access-controller' THEN 'organizations.manage_representation' ELSE 'authorization.manage_guidance_access' END;
END;
$$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guidance_expected_source(target_kind character varying, target_id uuid, control_role character varying)
RETURNS bigint AS $$
DECLARE bundle public.authorization_rolebundle%ROWTYPE; assignment public.authorization_roleassignment%ROWTYPE;
 setup public.authorization_guidanceauthoritysetupreceipt%ROWTYPE;
 plan public.events_guidanceactivationrequest%ROWTYPE;
 request public.authorization_guidanceaccessrequest%ROWTYPE;
 decision public.authorization_guidanceaccessdecision%ROWTYPE;
 team public.authorization_guidanceteam%ROWTYPE;
 is_a boolean; expected_name varchar; result bigint;
BEGIN
 IF public.maru_guidance_required_control(target_kind,target_id) IN ('authorization.grant_direct','authorization.manage_roles') THEN RETURN 0; END IF;
 IF control_role NOT IN ('actor','approver') THEN RETURN NULL; END IF;
 IF target_kind = 'capability_grant' THEN RETURN NULL; END IF;
 IF target_kind = 'role_bundle' THEN SELECT * INTO bundle FROM public.authorization_rolebundle WHERE id=target_id;
 ELSE
   SELECT * INTO assignment FROM public.authorization_roleassignment WHERE id=target_id;
   IF NOT FOUND OR assignment.edition_id IS NULL OR assignment.department_id IS NOT NULL OR assignment.resource_binding_id IS NOT NULL THEN RETURN NULL; END IF;
   SELECT * INTO bundle FROM public.authorization_rolebundle WHERE id=assignment.role_bundle_id;
 END IF;
 expected_name := CASE bundle.code WHEN 'guidance-access-controller' THEN 'Manage Guidance access' WHEN 'guidance-operator' THEN 'Guidance operator' WHEN 'guidance-reader' THEN 'Read approved Guidance' WHEN 'guidance-editor' THEN 'Write Guidance' WHEN 'guidance-reviewer' THEN 'Review Guidance' END;
 IF expected_name IS NULL OR bundle.name IS DISTINCT FROM expected_name OR bundle.version IS DISTINCT FROM 1 OR bundle.capability_codes IS DISTINCT FROM public.maru_guidance_recipe_capabilities(bundle.code) THEN RETURN NULL; END IF;
 IF target_kind='role_bundle' THEN
   SELECT s.* INTO setup FROM public.authorization_guidancerecipequalification q JOIN public.authorization_guidanceauthoritysetupreceipt s ON s.id=q.setup_id WHERE q.role_bundle_id=bundle.id;
 ELSE
   SELECT * INTO setup FROM public.authorization_guidanceauthoritysetupreceipt WHERE target_id IN (controller_a_id,controller_b_id,content_a_id,content_b_id);
 END IF;
 IF FOUND THEN
   SELECT r.* INTO plan FROM public.events_guidanceactivationreceipt a JOIN public.events_guidanceactivationrequest r ON r.id=a.request_id WHERE a.id=setup.activation_id;
   SELECT * INTO team FROM public.authorization_guidanceteam WHERE id=setup.team_id;
   IF plan.id IS NULL OR team.id IS NULL OR team.organization_id IS DISTINCT FROM plan.organization_id OR team.edition_id IS DISTINCT FROM plan.edition_id OR bundle.organization_id IS DISTINCT FROM plan.organization_id THEN RETURN NULL; END IF;
   IF target_kind='role_bundle' THEN
     IF bundle.created_by_id IS DISTINCT FROM plan.operator_a_id OR bundle.approved_by_id IS DISTINCT FROM plan.operator_b_id THEN RETURN NULL; END IF;
     RETURN CASE control_role WHEN 'actor' THEN setup.root_a_id ELSE setup.root_b_id END;
   END IF;
   is_a := target_id IN (setup.controller_a_id,setup.content_a_id);
   IF assignment.organization_id IS DISTINCT FROM plan.organization_id OR assignment.edition_id IS DISTINCT FROM plan.edition_id OR assignment.expires_at IS NOT NULL OR assignment.principal_id IS DISTINCT FROM (CASE WHEN is_a THEN plan.operator_a_id ELSE plan.operator_b_id END) OR assignment.granted_by_id IS DISTINCT FROM assignment.principal_id OR assignment.approved_by_id IS DISTINCT FROM (CASE WHEN is_a THEN plan.operator_b_id ELSE plan.operator_a_id END) THEN RETURN NULL; END IF;
   IF target_id IN (setup.controller_a_id,setup.controller_b_id) THEN
     IF bundle.code <> 'guidance-access-controller' THEN RETURN NULL; END IF;
     RETURN CASE WHEN (is_a AND control_role='actor') OR (NOT is_a AND control_role='approver') THEN setup.root_a_id ELSE setup.root_b_id END;
   END IF;
   IF bundle.code <> 'guidance-operator' THEN RETURN NULL; END IF;
   SELECT ordinal INTO result FROM public.authorization_authorityissuance WHERE role_assignment_id=CASE WHEN (is_a AND control_role='actor') OR (NOT is_a AND control_role='approver') THEN setup.controller_a_id ELSE setup.controller_b_id END;
   RETURN result;
 END IF;
 IF target_kind='role_bundle' OR bundle.code='guidance-access-controller' THEN RETURN NULL; END IF;
 SELECT * INTO decision FROM public.authorization_guidanceaccessdecision WHERE assignment_id=target_id AND accepted;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO request FROM public.authorization_guidanceaccessrequest WHERE id=decision.request_id;
 IF decision.actor_id IS DISTINCT FROM request.approver_id OR decision.request_digest IS DISTINCT FROM request.request_digest OR decision.created_at > request.decision_deadline OR assignment.organization_id IS DISTINCT FROM request.organization_id OR assignment.edition_id IS DISTINCT FROM request.edition_id OR assignment.principal_id IS DISTINCT FROM request.recipient_id OR assignment.granted_by_id IS DISTINCT FROM request.requested_by_id OR assignment.approved_by_id IS DISTINCT FROM request.approver_id OR assignment.role_bundle_id IS DISTINCT FROM request.role_bundle_id OR assignment.effective_from IS DISTINCT FROM request.effective_from OR assignment.expires_at IS DISTINCT FROM request.expires_at OR assignment.reason IS DISTINCT FROM request.reason THEN RETURN NULL; END IF;
 RETURN CASE control_role WHEN 'actor' THEN request.actor_source_id ELSE request.approver_source_id END;
END;
$$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guidance_actor_allowed(p_actor uuid, p_organization uuid, p_edition uuid, p_capability text)
RETURNS boolean AS $$
 SELECT p_capability = ANY(ARRAY['authorization.manage_guidance_access','knowledge.view_current','knowledge.view_working','knowledge.compose','knowledge.review','knowledge.withdraw','knowledge.manage_settings','knowledge.export_evidence'])
 AND EXISTS(SELECT 1 FROM public.identity_account p WHERE p.id=p_actor AND p.account_kind='person' AND p.is_active AND p.email_verified_at IS NOT NULL)
 AND EXISTS(SELECT 1 FROM public.events_eventedition e JOIN public.organizations_conventionseries s ON s.id=e.series_id JOIN public.organizations_organization o ON o.id=e.organization_id WHERE e.id=p_edition AND e.organization_id=p_organization AND s.organization_id=o.id AND o.lifecycle='active' AND s.is_active AND e.adoption_profile_code IN ('guidance_only','announcements_guidance') AND e.adoption_profile_version=1)
 AND EXISTS(SELECT 1 FROM public.authorization_roleassignment a JOIN public.authorization_rolebundle b ON b.id=a.role_bundle_id JOIN public.authorization_authorityissuance i ON i.role_assignment_id=a.id WHERE a.principal_id=p_actor AND a.organization_id=p_organization AND a.edition_id=p_edition AND a.department_id IS NULL AND a.resource_binding_id IS NULL AND p_capability=ANY(b.capability_codes) AND public.maru_authority_issuance_valid_v1(i.ordinal,p_actor,p_capability::varchar,p_organization,p_edition,NULL,NULL,clock_timestamp(),NULL,clock_timestamp(),TRUE,FALSE,ARRAY[]::bigint[],0));
$$ LANGUAGE sql VOLATILE SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guidance_team_ready(p_organization uuid, p_edition uuid, p_team uuid, p_activation uuid)
RETURNS boolean AS $$
 SELECT EXISTS(SELECT 1 FROM public.authorization_guidanceteam t JOIN public.authorization_guidanceauthoritysetupreceipt s ON s.team_id=t.id JOIN public.authorization_roleassignment a ON a.id=s.controller_a_id JOIN public.authorization_roleassignment b ON b.id=s.controller_b_id JOIN public.authorization_authorityissuance ai ON ai.role_assignment_id=a.id JOIN public.authorization_authorityissuance bi ON bi.role_assignment_id=b.id
 WHERE t.id=p_team AND t.organization_id=p_organization AND t.edition_id=p_edition AND t.original_activation_id=p_activation
 AND public.maru_guidance_actor_allowed(a.principal_id,p_organization,p_edition,'authorization.manage_guidance_access')
 AND public.maru_guidance_actor_allowed(b.principal_id,p_organization,p_edition,'authorization.manage_guidance_access')
 AND public.maru_authority_issuance_valid_v1(ai.ordinal,a.principal_id,'authorization.manage_guidance_access',p_organization,p_edition,NULL,NULL,clock_timestamp(),NULL,clock_timestamp(),TRUE,FALSE,ARRAY[]::bigint[],0)
 AND public.maru_authority_issuance_valid_v1(bi.ordinal,b.principal_id,'authorization.manage_guidance_access',p_organization,p_edition,NULL,NULL,clock_timestamp(),NULL,clock_timestamp(),TRUE,FALSE,ARRAY[]::bigint[],0));
$$ LANGUAGE sql VOLATILE SET search_path = pg_catalog, public, pg_temp;
"""


FORWARD_SQL += r"""
CREATE FUNCTION public.maru_guidance_authority_evidence_guard()
RETURNS trigger AS $$
DECLARE actor uuid; org uuid; edition uuid; trace uuid; audit_id uuid; target uuid; v_operation varchar; v_target_type varchar; cap varchar := 'authorization.manage_guidance_access';
 plan public.events_guidanceactivationrequest%ROWTYPE; activation public.events_guidanceactivationreceipt%ROWTYPE;
 request public.authorization_guidanceaccessrequest%ROWTYPE; assignment public.authorization_roleassignment%ROWTYPE;
 setup public.authorization_guidanceauthoritysetupreceipt%ROWTYPE; source record; role_codes varchar[];
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Guidance responsibility evidence is append-only' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='authorization_guidanceteam' THEN
   SELECT * INTO activation FROM public.events_guidanceactivationreceipt WHERE id=NEW.original_activation_id;
   SELECT * INTO plan FROM public.events_guidanceactivationrequest WHERE id=activation.request_id;
   IF activation.id IS NULL OR plan.purpose <> 'initial' OR NEW.organization_id IS DISTINCT FROM activation.organization_id OR NEW.edition_id IS DISTINCT FROM activation.edition_id THEN RAISE EXCEPTION 'Guidance team requires its exact original activation' USING ERRCODE='23514'; END IF;
   IF NOT EXISTS(SELECT 1 FROM public.audit_auditnativemutationwitness w WHERE w.audit_event_id=activation.source_audit_id AND w.transaction_stamp=public.maru_audit_current_native_transaction_stamp()) THEN RAISE EXCEPTION 'Guidance team requires live activation evidence' USING ERRCODE='23514'; END IF;
   RETURN NEW;
 ELSIF TG_TABLE_NAME='authorization_guidancerecipequalification' THEN
   SELECT * INTO setup FROM public.authorization_guidanceauthoritysetupreceipt WHERE id=NEW.setup_id;
   IF setup.id IS NULL OR NOT EXISTS(SELECT 1 FROM public.audit_auditnativemutationwitness w WHERE w.audit_event_id=setup.source_audit_id AND w.transaction_stamp=public.maru_audit_current_native_transaction_stamp()) THEN RAISE EXCEPTION 'Guidance recipe requires live setup qualification' USING ERRCODE='23514'; END IF;
   RETURN NEW;
 ELSIF TG_TABLE_NAME='authorization_guidanceauthoritysetupreceipt' THEN
   SELECT * INTO activation FROM public.events_guidanceactivationreceipt WHERE id=NEW.activation_id;
   SELECT * INTO plan FROM public.events_guidanceactivationrequest WHERE id=activation.request_id;
   IF plan.id IS NULL OR NOT EXISTS(SELECT 1 FROM public.authorization_guidanceteam t WHERE t.id=NEW.team_id AND t.organization_id=activation.organization_id AND t.edition_id=activation.edition_id) THEN RAISE EXCEPTION 'Guidance setup requires its accepted owner graph' USING ERRCODE='23514'; END IF;
   FOR source IN SELECT i.ordinal,a.principal_id FROM public.authorization_authorityissuance i JOIN public.authorization_roleassignment a ON a.id=i.role_assignment_id JOIN public.organizations_representationappointment appointment ON appointment.role_assignment_id=a.id JOIN public.organizations_organizationrepresentation representation ON representation.id=appointment.representation_id
    WHERE i.ordinal IN (NEW.root_a_id,NEW.root_b_id) AND a.organization_id=activation.organization_id AND a.edition_id IS NULL AND a.department_id IS NULL AND a.resource_binding_id IS NULL AND representation.id=plan.representation_id AND representation.state='active' AND representation.aggregate_version=plan.representation_version AND appointment.state='active' AND appointment.account_id=a.principal_id
   LOOP
    IF source.principal_id IS DISTINCT FROM (CASE WHEN source.ordinal=NEW.root_a_id THEN plan.operator_a_id ELSE plan.operator_b_id END) OR NOT public.maru_authority_issuance_valid_v1(source.ordinal,source.principal_id,'organizations.manage_representation',activation.organization_id,NULL,NULL,NULL,clock_timestamp(),NULL,clock_timestamp(),TRUE,FALSE,ARRAY[]::bigint[],0) THEN RAISE EXCEPTION 'Guidance bootstrap source is not its current accepted root' USING ERRCODE='23514'; END IF;
   END LOOP;
   IF (SELECT count(*) FROM public.authorization_authorityissuance i JOIN public.authorization_roleassignment a ON a.id=i.role_assignment_id JOIN public.organizations_representationappointment appointment ON appointment.role_assignment_id=a.id WHERE i.ordinal IN (NEW.root_a_id,NEW.root_b_id) AND appointment.representation_id=plan.representation_id AND appointment.state='active' AND a.principal_id IN (plan.operator_a_id,plan.operator_b_id)) <> 2 THEN RAISE EXCEPTION 'Guidance setup requires both exact linked roots' USING ERRCODE='23514'; END IF;
   actor:=plan.operator_a_id; org:=activation.organization_id; edition:=activation.edition_id;
   v_operation:='authorization.guidance.setup'; v_target_type:='authorization.guidance_setup_receipt'; cap:='organizations.manage_representation';
 ELSIF TG_TABLE_NAME='authorization_guidanceaccessrequest' THEN
   actor:=NEW.requested_by_id; org:=NEW.organization_id; edition:=NEW.edition_id;
   v_operation:='authorization.guidance.access.request'; v_target_type:='authorization.guidance_access_request';
   IF NEW.approver_id IN (NEW.requested_by_id,NEW.recipient_id) OR NEW.decision_deadline<=clock_timestamp() OR NEW.effective_from>clock_timestamp() OR (NEW.expires_at IS NOT NULL AND NEW.expires_at<=NEW.effective_from)
    OR NOT EXISTS(SELECT 1 FROM public.authorization_guidanceteam t WHERE t.id=NEW.team_id AND t.organization_id=org AND t.edition_id=edition)
    OR NOT EXISTS(SELECT 1 FROM public.authorization_rolebundle b WHERE b.id=NEW.role_bundle_id AND b.organization_id=org AND b.code IN ('guidance-reader','guidance-editor','guidance-reviewer','guidance-operator') AND b.version=1 AND b.capability_codes=public.maru_guidance_recipe_capabilities(b.code))
    OR NOT EXISTS(SELECT 1 FROM public.identity_account p WHERE p.id=NEW.recipient_id AND p.is_active AND p.account_kind='person' AND p.email_verified_at IS NOT NULL)
    OR NOT public.maru_guidance_actor_allowed(NEW.requested_by_id,org,edition,'authorization.manage_guidance_access') OR NOT public.maru_guidance_actor_allowed(NEW.approver_id,org,edition,'authorization.manage_guidance_access')
    OR NOT public.maru_authority_issuance_valid_v1(NEW.actor_source_id,NEW.requested_by_id,'authorization.manage_guidance_access',org,edition,NULL,NULL,NEW.effective_from,NEW.expires_at,clock_timestamp(),TRUE,TRUE,ARRAY[]::bigint[],0)
    OR NOT public.maru_authority_issuance_valid_v1(NEW.approver_source_id,NEW.approver_id,'authorization.manage_guidance_access',org,edition,NULL,NULL,NEW.effective_from,NEW.expires_at,clock_timestamp(),TRUE,TRUE,ARRAY[]::bigint[],0)
   THEN RAISE EXCEPTION 'Guidance access request lacks exact current purpose authority' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='authorization_guidanceaccessdecision' THEN
   SELECT * INTO request FROM public.authorization_guidanceaccessrequest WHERE id=NEW.request_id;
   actor:=NEW.actor_id; org:=request.organization_id; edition:=request.edition_id;
   v_operation:=CASE WHEN NEW.accepted THEN 'authorization.guidance.access.accept' ELSE 'authorization.guidance.access.decline' END; v_target_type:='authorization.guidance_access_decision';
   IF request.id IS NULL OR actor IS DISTINCT FROM request.approver_id OR NEW.request_digest IS DISTINCT FROM request.request_digest OR request.decision_deadline<=clock_timestamp() OR (NEW.accepted IS DISTINCT FROM (NEW.assignment_id IS NOT NULL))
    OR NOT public.maru_guidance_actor_allowed(actor,org,edition,'authorization.manage_guidance_access')
    OR NOT public.maru_authority_issuance_valid_v1(request.actor_source_id,request.requested_by_id,'authorization.manage_guidance_access',org,edition,NULL,NULL,request.effective_from,request.expires_at,clock_timestamp(),TRUE,TRUE,ARRAY[]::bigint[],0)
    OR NOT public.maru_authority_issuance_valid_v1(request.approver_source_id,request.approver_id,'authorization.manage_guidance_access',org,edition,NULL,NULL,request.effective_from,request.expires_at,clock_timestamp(),TRUE,TRUE,ARRAY[]::bigint[],0)
    OR NOT EXISTS(SELECT 1 FROM public.identity_account p WHERE p.id=request.recipient_id AND p.is_active AND p.account_kind='person' AND p.email_verified_at IS NOT NULL)
   THEN RAISE EXCEPTION 'Guidance decision requires the actual named independent approver' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='authorization_guidancerevocationreceipt' THEN
   SELECT * INTO assignment FROM public.authorization_roleassignment WHERE id=NEW.assignment_id FOR UPDATE;
   SELECT capability_codes INTO role_codes FROM public.authorization_rolebundle WHERE id=assignment.role_bundle_id;
   actor:=NEW.actor_id; org:=assignment.organization_id; edition:=assignment.edition_id;
   v_operation:='authorization.guidance.access.revoke'; v_target_type:='authorization.guidance_revocation_receipt';
   IF assignment.id IS NULL OR assignment.revoked_at IS NOT NULL OR NEW.revoked_at>clock_timestamp() OR NOT COALESCE(role_codes && ARRAY['authorization.manage_guidance_access','knowledge.view_current','knowledge.view_working','knowledge.compose','knowledge.review','knowledge.withdraw','knowledge.manage_settings','knowledge.export_evidence']::varchar[],FALSE)
    OR NOT public.maru_guidance_actor_allowed(actor,org,edition,'authorization.manage_guidance_access')
    OR NOT public.maru_authority_issuance_valid_v1(NEW.source_id,actor,'authorization.manage_guidance_access',org,edition,NULL,NULL,clock_timestamp(),NULL,clock_timestamp(),TRUE,FALSE,ARRAY[]::bigint[],0)
   THEN RAISE EXCEPTION 'Guidance revocation requires current purpose authority' USING ERRCODE='23514'; END IF;
 ELSE RAISE EXCEPTION 'Unknown Guidance evidence relation' USING ERRCODE='23514';
 END IF;
 audit_id:=NEW.source_audit_id; trace:=NEW.correlation_id; target:=NEW.id;
 IF NOT EXISTS(SELECT 1 FROM public.events_eventedition e JOIN public.organizations_organization o ON o.id=e.organization_id JOIN public.organizations_conventionseries s ON s.id=e.series_id WHERE e.id=edition AND e.organization_id=org AND s.organization_id=org AND o.lifecycle='active' AND s.is_active AND (e.lifecycle IN ('draft','preparing','ready','live') OR TG_TABLE_NAME='authorization_guidancerevocationreceipt') AND e.adoption_profile_code IN ('guidance_only','announcements_guidance') AND e.adoption_profile_version=1)
 OR NOT EXISTS(SELECT 1 FROM public.audit_auditevent a JOIN public.audit_auditnativemutationwitness w ON w.audit_event_id=a.id AND w.transaction_stamp=public.maru_audit_current_native_transaction_stamp() WHERE a.id=audit_id AND a.principal_kind='account' AND a.principal_id=actor AND a.principal_context_id IS NULL AND a.organization_id=org AND a.event_edition_id=edition AND a.operation=v_operation AND a.capability_code=cap AND a.target_type=v_target_type AND a.target_id=target AND a.outcome='allow' AND a.correlation_id=trace AND a.reason_code='accepted_guidance_responsibility') THEN RAISE EXCEPTION 'Guidance evidence requires its live exact native audit and scope' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guidance_authority_graph_guard()
RETURNS trigger AS $$
DECLARE output_id uuid; kind varchar; setup public.authorization_guidanceauthoritysetupreceipt%ROWTYPE; role_id uuid; revocation public.authorization_guidancerevocationreceipt%ROWTYPE; assignment public.authorization_roleassignment%ROWTYPE;
 event_operation varchar; event_aggregate uuid; event_type varchar; event_actor uuid; event_org uuid; event_edition uuid;
BEGIN
 IF TG_TABLE_NAME='authorization_guidanceaccessrequest' THEN
  event_actor:=NEW.requested_by_id; event_operation:='requested'; event_aggregate:=NEW.id; event_type:='authorization.guidance_access_request'; event_org:=NEW.organization_id; event_edition:=NEW.edition_id;
 ELSIF TG_TABLE_NAME='authorization_guidanceaccessdecision' THEN
  event_actor:=NEW.actor_id; event_operation:=CASE WHEN NEW.accepted THEN 'accepted' ELSE 'declined' END; event_aggregate:=NEW.id; event_type:='authorization.guidance_access_decision';
  SELECT organization_id,edition_id INTO event_org,event_edition FROM public.authorization_guidanceaccessrequest WHERE id=NEW.request_id;
 ELSIF TG_TABLE_NAME='authorization_guidancerevocationreceipt' THEN
  event_actor:=NEW.actor_id; event_operation:='revoked'; event_aggregate:=NEW.id; event_type:='authorization.guidance_revocation_receipt';
  SELECT organization_id,edition_id INTO event_org,event_edition FROM public.authorization_roleassignment WHERE id=NEW.assignment_id;
 END IF;
 IF event_operation IS NOT NULL THEN
 IF NOT EXISTS(SELECT 1 FROM public.effects_domainevent e JOIN public.effects_outboxmessage o ON o.event_id=e.id AND o.destination='internal' WHERE e.event_name='authorization.guidance_access.changed.v1' AND e.schema_version=1 AND e.aggregate_version=1 AND e.actor_kind='account' AND e.actor_id=event_actor AND e.causation_id=NEW.source_audit_id AND e.correlation_id=NEW.correlation_id AND e.organization_id=event_org AND e.event_edition_id=event_edition AND e.aggregate_type=event_type AND e.aggregate_id=event_aggregate AND e.payload=jsonb_build_object('operation',event_operation)) THEN RAISE EXCEPTION 'Guidance access evidence requires its minimized event and outbox' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='authorization_guidanceauthoritysetupreceipt' THEN
  SELECT * INTO setup FROM public.authorization_guidanceauthoritysetupreceipt WHERE id=NEW.id;
  FOREACH output_id IN ARRAY ARRAY[setup.controller_a_id,setup.controller_b_id,setup.content_a_id,setup.content_b_id] LOOP
   IF public.maru_guidance_expected_source('role_assignment',output_id,'actor') IS NULL OR public.maru_guidance_expected_source('role_assignment',output_id,'approver') IS NULL THEN RAISE EXCEPTION 'Guidance setup receipt requires all four exact role outputs' USING ERRCODE='23514'; END IF;
   PERFORM public.maru_assert_authority_target_complete('role_assignment',output_id);
  END LOOP;
  IF (SELECT count(DISTINCT effective_from) FROM public.authorization_roleassignment WHERE id IN (setup.controller_a_id,setup.controller_b_id,setup.content_a_id,setup.content_b_id)) <> 1 THEN RAISE EXCEPTION 'Guidance bootstrap role terms must match' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='authorization_guidanceteam' THEN
  IF NOT EXISTS(SELECT 1 FROM public.authorization_guidanceauthoritysetupreceipt s WHERE s.team_id=NEW.id AND s.activation_id=NEW.original_activation_id) THEN RAISE EXCEPTION 'Guidance team must retain its original actual setup result' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='authorization_guidancerecipequalification' THEN
  IF public.maru_guidance_expected_source('role_bundle',NEW.role_bundle_id,'actor') IS NULL OR public.maru_guidance_expected_source('role_bundle',NEW.role_bundle_id,'approver') IS NULL THEN RAISE EXCEPTION 'Guidance recipe qualification requires its exact immutable role' USING ERRCODE='23514'; END IF;
  PERFORM public.maru_assert_authority_target_complete('role_bundle',NEW.role_bundle_id);
 ELSIF TG_TABLE_NAME='authorization_guidanceaccessdecision' THEN
  IF NEW.accepted THEN
   IF public.maru_guidance_expected_source('role_assignment',NEW.assignment_id,'actor') IS NULL OR public.maru_guidance_expected_source('role_assignment',NEW.assignment_id,'approver') IS NULL THEN RAISE EXCEPTION 'Accepted Guidance decision requires its exact assignment' USING ERRCODE='23514'; END IF;
   PERFORM public.maru_assert_authority_target_complete('role_assignment',NEW.assignment_id);
  END IF;
 ELSIF TG_TABLE_NAME='authorization_guidancerevocationreceipt' THEN
  SELECT * INTO assignment FROM public.authorization_roleassignment WHERE id=NEW.assignment_id;
  IF assignment.revoked_at IS DISTINCT FROM NEW.revoked_at OR assignment.revoked_by_id IS DISTINCT FROM NEW.actor_id OR assignment.revocation_reason IS DISTINCT FROM NEW.reason THEN RAISE EXCEPTION 'Guidance revocation receipt requires its actual assignment transition' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME IN ('authorization_rolebundle','authorization_roleassignment','authorization_capabilitygrant') THEN
  kind := CASE TG_TABLE_NAME WHEN 'authorization_rolebundle' THEN 'role_bundle' WHEN 'authorization_roleassignment' THEN 'role_assignment' ELSE 'capability_grant' END;
  IF public.maru_guidance_required_control(kind,NEW.id) IN ('authorization.grant_direct','authorization.manage_roles') THEN RETURN NULL; END IF;
  IF public.maru_guidance_expected_source(kind,NEW.id,'actor') IS NULL OR public.maru_guidance_expected_source(kind,NEW.id,'approver') IS NULL THEN RAISE EXCEPTION 'Protected Guidance authority requires exact accepted target evidence' USING ERRCODE='23514'; END IF;
  PERFORM public.maru_assert_authority_target_complete(kind,NEW.id);
  IF kind='role_assignment' THEN
   SELECT * INTO assignment FROM public.authorization_roleassignment WHERE id=NEW.id;
   IF assignment.revoked_at IS NOT NULL THEN
    SELECT * INTO revocation FROM public.authorization_guidancerevocationreceipt WHERE assignment_id=NEW.id;
    IF revocation.id IS NULL OR assignment.revoked_at IS DISTINCT FROM revocation.revoked_at OR assignment.revoked_by_id IS DISTINCT FROM revocation.actor_id OR assignment.revocation_reason IS DISTINCT FROM revocation.reason THEN RAISE EXCEPTION 'Protected Guidance revocation requires exact purpose-backed evidence' USING ERRCODE='23514'; END IF;
   END IF;
  END IF;
 END IF;
 RETURN NULL;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guidance_authority_no_truncate()
RETURNS trigger AS $$
BEGIN
 IF public.maru_authority_provenance_test_reset_allowed() THEN RETURN NULL; END IF;
 RAISE EXCEPTION 'Guidance responsibility evidence cannot be truncated' USING ERRCODE='23514';
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;
"""

_EVIDENCE_RELATIONS = (
    "authorization_guidanceteam",
    "authorization_guidanceauthoritysetupreceipt",
    "authorization_guidancerecipequalification",
    "authorization_guidanceaccessrequest",
    "authorization_guidanceaccessdecision",
    "authorization_guidancerevocationreceipt",
)
for _relation in _EVIDENCE_RELATIONS:
    FORWARD_SQL += f"CREATE TRIGGER {_relation}_evidence BEFORE INSERT OR UPDATE OR DELETE ON public.{_relation} FOR EACH ROW EXECUTE FUNCTION public.maru_guidance_authority_evidence_guard();\n"
    FORWARD_SQL += f"CREATE TRIGGER {_relation}_no_truncate BEFORE TRUNCATE ON public.{_relation} FOR EACH STATEMENT EXECUTE FUNCTION public.maru_guidance_authority_no_truncate();\n"
    FORWARD_SQL += f"CREATE CONSTRAINT TRIGGER {_relation}_graph AFTER INSERT ON public.{_relation} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.maru_guidance_authority_graph_guard();\n"
for _relation in (
    "authorization_rolebundle",
    "authorization_roleassignment",
    "authorization_capabilitygrant",
):
    FORWARD_SQL += f"CREATE CONSTRAINT TRIGGER {_relation}_guidance_graph AFTER INSERT OR UPDATE ON public.{_relation} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.maru_guidance_authority_graph_guard();\n"

NEW_FUNCTION_IDENTITIES = (
    "maru_guidance_recipe_capabilities(character varying)",
    "maru_guidance_required_control(character varying, uuid)",
    "maru_guidance_expected_source(character varying, uuid, character varying)",
    "maru_guidance_actor_allowed(uuid, uuid, uuid, text)",
    "maru_guidance_team_ready(uuid, uuid, uuid, uuid)",
)

_TRIGGER_IDENTITIES = (
    "maru_guidance_authority_evidence_guard()",
    "maru_guidance_authority_graph_guard()",
    "maru_guidance_authority_no_truncate()",
)
for _identity in (*NEW_FUNCTION_IDENTITIES, *_TRIGGER_IDENTITIES):
    FORWARD_SQL += f"REVOKE ALL ON FUNCTION public.{_identity} FROM PUBLIC;\n"
REVERSE_SQL = ""
for _relation in _EVIDENCE_RELATIONS:
    for _suffix in ("evidence", "no_truncate", "graph"):
        REVERSE_SQL += f"DROP TRIGGER {_relation}_{_suffix} ON public.{_relation};\n"
for _relation in (
    "authorization_rolebundle",
    "authorization_roleassignment",
    "authorization_capabilitygrant",
):
    REVERSE_SQL += f"DROP TRIGGER {_relation}_guidance_graph ON public.{_relation};\n"
for _identity in (*_TRIGGER_IDENTITIES, *reversed(NEW_FUNCTION_IDENTITIES)):
    REVERSE_SQL += f"DROP FUNCTION public.{_identity};\n"

_IDENTITIES = (
    _lineage._BUNDLE,
    _lineage._ASSIGNMENT,
    "maru_validate_authority_control_insert()",
)


def previous_source(identity: str) -> str:
    return _previous.next_source(identity)


def next_source(identity: str) -> str:
    source = previous_source(identity)
    once = _lineage._once
    if identity == _lineage._ASSIGNMENT:
        source = once(
            source,
            """               CASE
                   WHEN source_kind = 'grant'
                       THEN 'authorization.grant_direct'
                   ELSE 'authorization.manage_roles'
               END,""",
            """               public.maru_guidance_required_control(CASE WHEN source_kind='grant' THEN 'capability_grant' ELSE 'role_assignment' END, COALESCE(grant_id,assignment_id)),""",
        )
        return once(
            source,
            """           OR (require_current AND principal_active IS DISTINCT FROM TRUE)
           OR NOT public.maru_authority_issuance_valid_v1(""",
            """           OR (require_current AND principal_active IS DISTINCT FROM TRUE)
           OR public.maru_guidance_expected_source(CASE WHEN source_kind='grant' THEN 'capability_grant' ELSE 'role_assignment' END,COALESCE(grant_id,assignment_id),control_record.role) IS NULL
           OR public.maru_guidance_expected_source(CASE WHEN source_kind='grant' THEN 'capability_grant' ELSE 'role_assignment' END,COALESCE(grant_id,assignment_id),control_record.role) NOT IN (0,control_record.source_issuance_id)
           OR NOT public.maru_authority_issuance_valid_v1(""",
        )
    if identity == _lineage._BUNDLE:
        source = once(
            source,
            """               'authorization.manage_roles',
               bundle_organization,""",
            """               public.maru_guidance_required_control('role_bundle',target_bundle),
               bundle_organization,""",
        )
        return once(
            source,
            """           OR principal_kind IS DISTINCT FROM 'person'
           OR NOT public.maru_authority_issuance_valid_v1(""",
            """           OR principal_kind IS DISTINCT FROM 'person'
           OR public.maru_guidance_expected_source('role_bundle',target_bundle,control_record.role) IS NULL
           OR public.maru_guidance_expected_source('role_bundle',target_bundle,control_record.role) NOT IN (0,control_record.source_issuance_id)
           OR NOT public.maru_authority_issuance_valid_v1(""",
        )
    source = once(
        source,
        """        CASE
            WHEN issuance.capability_grant_id IS NOT NULL
                THEN 'authorization.grant_direct'
            ELSE 'authorization.manage_roles'
        END,""",
        """        public.maru_guidance_required_control(CASE WHEN issuance.capability_grant_id IS NOT NULL THEN 'capability_grant' WHEN issuance.role_bundle_id IS NOT NULL THEN 'role_bundle' ELSE 'role_assignment' END,COALESCE(issuance.capability_grant_id,issuance.role_bundle_id,issuance.role_assignment_id)),""",
    )
    return once(
        source,
        """    IF NEW.policy_version IS DISTINCT FROM issuance_policy_version""",
        """    IF EXISTS (
      SELECT 1 FROM public.authorization_authorityissuance i WHERE i.ordinal=NEW.issuance_id
       AND (public.maru_guidance_expected_source(CASE WHEN i.capability_grant_id IS NOT NULL THEN 'capability_grant' WHEN i.role_bundle_id IS NOT NULL THEN 'role_bundle' ELSE 'role_assignment' END,COALESCE(i.capability_grant_id,i.role_bundle_id,i.role_assignment_id),NEW.role) IS NULL
       OR public.maru_guidance_expected_source(CASE WHEN i.capability_grant_id IS NOT NULL THEN 'capability_grant' WHEN i.role_bundle_id IS NOT NULL THEN 'role_bundle' ELSE 'role_assignment' END,COALESCE(i.capability_grant_id,i.role_bundle_id,i.role_assignment_id),NEW.role) NOT IN (0,NEW.source_issuance_id))
    ) THEN RAISE EXCEPTION 'Guidance controls require their exact accepted source' USING ERRCODE='23514'; END IF;
    IF NEW.policy_version IS DISTINCT FROM issuance_policy_version""",
    )


def _replace(schema_editor: Any, *, forward: bool) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "LOCK TABLE public.authorization_rolebundle, public.authorization_roleassignment, public.authorization_authorityissuance, public.authorization_authoritycontrol IN ACCESS EXCLUSIVE MODE"
        )
        for identity in _IDENTITIES:
            previous, desired = previous_source(identity), next_source(identity)
            if not forward:
                previous, desired = desired, previous
            before = _lineage._state(cursor, identity)
            if before[3] != previous:
                raise RuntimeError(
                    f"Refusing changed authority function source: {identity}."
                )
            cursor.execute(_previous._sql(identity, desired))
            after = _lineage._state(cursor, identity)
            if (
                after[:3] != before[:3]
                or after[4:] != before[4:]
                or after[3] != desired
            ):
                raise RuntimeError(
                    "Guidance qualification changed authority helper identity or ACL."
                )


def install(apps: Any, schema_editor: Any) -> None:
    del apps
    _replace(schema_editor, forward=True)


def restore(apps: Any, schema_editor: Any) -> None:
    del apps
    _replace(schema_editor, forward=False)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0045_guidance_authority_records")
    ]
    operations: ClassVar[list[object]] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
