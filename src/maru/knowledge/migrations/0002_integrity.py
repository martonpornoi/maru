"""Native exact-purpose authority, immutable review rounds and complete owner evidence."""

from django.db import migrations

TABLES = (
    "guidancecontrol", "guidanceitem", "guidancesettingsrevision",
    "guidancerevision", "guidancereview", "guidancecommandreceipt",
)
FUNCTIONS = (
    "maru_knowledge_row_guard()", "maru_knowledge_graph_guard()",
    "maru_knowledge_no_truncate()",
)

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_knowledge_row_guard()
RETURNS trigger AS $$
DECLARE
    body jsonb := to_jsonb(NEW);
    capability text;
BEGIN
    IF TG_OP='DELETE' THEN
        RAISE EXCEPTION 'Guidance history is retained' USING ERRCODE='23514';
    END IF;
    IF TG_OP='INSERT' THEN
        IF TG_TABLE_NAME='knowledge_guidanceitem' AND (
            (body->>'version')::bigint<>1 OR body->>'status'<>'draft' OR (body->>'withdrawn')::boolean
            OR body->>'current_revision_id' IS NOT NULL OR body->>'approved_revision_id' IS NOT NULL
            OR body->>'published_revision_id' IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'Guidance begins as an unavailable unreviewed draft' USING ERRCODE='23514';
        ELSIF TG_TABLE_NAME='knowledge_guidancecontrol' AND (
            (body->>'sequence')::bigint<>0 OR (body->>'settings_version')::bigint<>0 OR (body->>'stopped')::boolean
            OR body->>'current_settings_id' IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'Guidance control requires initial settings evidence' USING ERRCODE='23514';
        END IF;
    ELSIF TG_OP='UPDATE' THEN
        IF TG_TABLE_NAME NOT IN ('knowledge_guidancecontrol','knowledge_guidanceitem')
           OR NEW.id<>OLD.id OR NEW.organization_id<>OLD.organization_id
           OR NEW.edition_id<>OLD.edition_id OR NEW.created_at<>OLD.created_at THEN
            RAISE EXCEPTION 'Guidance evidence is immutable' USING ERRCODE='23514';
        END IF;
        IF TG_TABLE_NAME='knowledge_guidancecontrol' THEN
            IF NEW.sequence<>OLD.sequence+1 OR NEW.settings_version NOT IN (OLD.settings_version,OLD.settings_version+1) THEN
                RAISE EXCEPTION 'Guidance control advances with one exact receipt' USING ERRCODE='23514';
            END IF;
        ELSE
            IF NEW.language_code<>OLD.language_code OR NOT (
                NEW.version=OLD.version+1 OR (OLD.version=1 AND NEW.version=1
                    AND OLD.current_revision_id IS NULL AND NEW.current_revision_id IS NOT NULL
                    AND NEW.status='draft' AND NOT NEW.withdrawn
                    AND NEW.approved_revision_id IS NULL AND NEW.published_revision_id IS NULL)
            ) THEN
                RAISE EXCEPTION 'Guidance preserves its language and contiguous version' USING ERRCODE='23514';
            END IF;
        END IF;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.events_eventedition edition
        JOIN public.organizations_conventionseries series ON series.id=edition.series_id
        WHERE edition.id=NEW.edition_id AND edition.organization_id=NEW.organization_id
          AND series.organization_id=NEW.organization_id
          AND edition.adoption_profile_code IN ('guidance_only','announcements_guidance')
          AND edition.adoption_profile_version=1
    ) THEN
        RAISE EXCEPTION 'Guidance requires its exact adopted edition' USING ERRCODE='23514';
    END IF;
    IF body ? 'actor_id' AND NOT EXISTS (
        SELECT 1 FROM public.identity_account actor WHERE actor.id=(body->>'actor_id')::uuid
        AND actor.is_active AND actor.email_verified_at IS NOT NULL AND actor.account_kind='person'
    ) THEN
        RAISE EXCEPTION 'Guidance evidence requires a verified ordinary person' USING ERRCODE='23514';
    END IF;
    IF TG_TABLE_NAME='knowledge_guidancerevision' AND public.maru_guidance_team_ready(
        NEW.organization_id, NEW.edition_id, (body->>'team_id')::uuid, (body->>'team_activation_receipt_id')::uuid
    ) IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'Guidance needs its exact accepted team ownership' USING ERRCODE='23514';
    END IF;
    IF TG_TABLE_NAME='knowledge_guidancecommandreceipt' THEN
        capability := CASE NEW.operation
            WHEN 'settings_update' THEN 'knowledge.manage_settings'
            WHEN 'stop' THEN 'knowledge.manage_settings' WHEN 'resume' THEN 'knowledge.manage_settings'
            WHEN 'create' THEN 'knowledge.compose' WHEN 'revise' THEN 'knowledge.compose'
            WHEN 'request_review' THEN 'knowledge.compose' WHEN 'withdraw' THEN 'knowledge.withdraw'
            WHEN 'approve' THEN 'knowledge.review' WHEN 'changes_requested' THEN 'knowledge.review' END;
        IF capability IS NULL OR public.maru_guidance_actor_allowed(
            NEW.actor_id,NEW.organization_id,NEW.edition_id,capability
        ) IS DISTINCT FROM true THEN
            RAISE EXCEPTION 'Guidance requires current qualified exact-purpose authority' USING ERRCODE='23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.events_eventedition edition
            JOIN public.organizations_organization org ON org.id=edition.organization_id
            JOIN public.organizations_conventionseries series ON series.id=edition.series_id
            WHERE edition.id=NEW.edition_id AND org.lifecycle='active' AND series.is_active
              AND edition.lifecycle IN ('draft','preparing','ready','live')
        ) THEN
            RAISE EXCEPTION 'The edition does not admit Guidance writes' USING ERRCODE='23514';
        END IF;
        IF NEW.operation IN ('create','revise','request_review','approve','changes_requested','resume') AND NOT EXISTS (
            SELECT 1 FROM public.knowledge_guidancecontrol control
            JOIN public.knowledge_guidancesettingsrevision rules ON rules.id=control.current_settings_id
            JOIN public.events_eventedition edition ON edition.id=control.edition_id
            WHERE control.edition_id=NEW.edition_id AND NOT control.stopped
              AND rules.review_on >= (statement_timestamp() AT TIME ZONE edition.time_zone)::date
        ) THEN
            RAISE EXCEPTION 'Current rules and open Guidance work are required' USING ERRCODE='23514';
        END IF;
        IF NEW.operation IN ('request_review','approve','changes_requested') AND NOT EXISTS (
            SELECT 1 FROM public.knowledge_guidanceitem item
            JOIN public.knowledge_guidancerevision revision ON revision.id=item.current_revision_id
            JOIN public.events_eventedition edition ON edition.id=item.edition_id
            WHERE item.id=NEW.item_id AND item.edition_id=NEW.edition_id
              AND revision.language_code=ANY(edition.language_codes)
        ) THEN
            RAISE EXCEPTION 'Guidance review requires a currently configured language' USING ERRCODE='23514';
        END IF;
        IF NEW.operation='withdraw' AND octet_length(body::text)>8192 THEN
            RAISE EXCEPTION 'Guidance withdrawal evidence exceeds its reserved budget' USING ERRCODE='23514';
        END IF;
        IF NEW.operation IN ('revise','withdraw','stop','resume') AND length(btrim(NEW.reason))=0 THEN
            RAISE EXCEPTION 'Guidance changes require an accountable reason' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_knowledge_no_truncate()
RETURNS trigger AS $$
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed() THEN RETURN NULL; END IF;
    RAISE EXCEPTION 'Guidance evidence cannot be truncated' USING ERRCODE='23514';
END;
$$ LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_knowledge_graph_guard()
RETURNS trigger AS $$
DECLARE
    body jsonb := to_jsonb(NEW);
    receipt public.knowledge_guidancecommandreceipt;
    revision public.knowledge_guidancerevision;
    previous public.knowledge_guidancerevision;
    item public.knowledge_guidanceitem;
    rules public.knowledge_guidancesettingsrevision;
    control public.knowledge_guidancecontrol;
    head_receipt public.knowledge_guidancecommandreceipt;
    expected_capability text;
    reference_id uuid;
    current_count bigint;
    retained_bytes bigint;
    expected_revision_id uuid;
    expected_approved_id uuid;
    expected_status text;
    expected_withdrawn boolean;
BEGIN
    IF TG_TABLE_NAME='knowledge_guidancecommandreceipt' THEN
        receipt := NEW;
    ELSIF body ? 'command_receipt_id' THEN
        SELECT * INTO receipt FROM public.knowledge_guidancecommandreceipt
        WHERE id=(body->>'command_receipt_id')::uuid;
    ELSIF TG_TABLE_NAME='knowledge_guidancecontrol' THEN
        IF NEW.sequence=0 THEN
            IF NOT EXISTS (SELECT 1 FROM public.knowledge_guidancecommandreceipt
                WHERE edition_id=NEW.edition_id AND control_sequence=1 AND operation='settings_update') THEN
                RAISE EXCEPTION 'An empty control requires initial rules evidence' USING ERRCODE='23514';
            END IF;
            RETURN NULL;
        END IF;
        SELECT * INTO receipt FROM public.knowledge_guidancecommandreceipt
        WHERE edition_id=NEW.edition_id AND control_sequence=NEW.sequence;
        IF (TG_OP='UPDATE' AND (
            (NEW.settings_version<>OLD.settings_version AND receipt.operation NOT IN ('settings_update','stop','resume'))
            OR (NEW.current_settings_id IS DISTINCT FROM OLD.current_settings_id AND receipt.operation<>'settings_update')
            OR (NEW.stopped IS DISTINCT FROM OLD.stopped AND receipt.operation NOT IN ('stop','resume'))
            OR (receipt.operation IN ('settings_update','stop','resume') AND NEW.settings_version<>OLD.settings_version+1)
            OR (receipt.operation='stop' AND (OLD.stopped OR NOT NEW.stopped))
            OR (receipt.operation='resume' AND (NOT OLD.stopped OR NEW.stopped))
            OR (receipt.operation='settings_update' AND receipt.object_id IS DISTINCT FROM NEW.current_settings_id)
        )) OR (receipt.operation IN ('settings_update','stop','resume') AND receipt.resulting_version<>NEW.settings_version) THEN
            RAISE EXCEPTION 'Guidance settings transitions need their exact operation' USING ERRCODE='23514';
        END IF;
    ELSE
        SELECT * INTO receipt FROM public.knowledge_guidancecommandreceipt
        WHERE item_id=NEW.id AND resulting_version=NEW.version;
        IF NEW.current_revision_id IS NOT NULL THEN
            SELECT * INTO revision FROM public.knowledge_guidancerevision WHERE id=NEW.current_revision_id;
            IF revision.item_id IS DISTINCT FROM NEW.id OR revision.organization_id<>NEW.organization_id
               OR revision.edition_id<>NEW.edition_id THEN
                RAISE EXCEPTION 'The working copy must belong to this guide' USING ERRCODE='23514';
            END IF;
        ELSIF TG_OP<>'INSERT' OR NEW.version<>1 OR receipt.operation<>'create' THEN
            RAISE EXCEPTION 'Guidance requires its first exact copy' USING ERRCODE='23514';
        END IF;
        IF NEW.approved_revision_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.knowledge_guidancerevision source
            JOIN public.knowledge_guidancereview decision ON decision.revision_id=source.id
            WHERE source.id=NEW.approved_revision_id AND source.item_id=NEW.id
              AND source.organization_id=NEW.organization_id AND source.edition_id=NEW.edition_id
              AND decision.decision='approve'
        ) THEN
            RAISE EXCEPTION 'The retained approved copy needs independent evidence' USING ERRCODE='23514';
        END IF;
        IF TG_OP='UPDATE' AND (
            (NEW.current_revision_id IS DISTINCT FROM OLD.current_revision_id AND receipt.operation NOT IN ('create','revise'))
            OR (NEW.approved_revision_id IS DISTINCT FROM OLD.approved_revision_id AND receipt.operation<>'approve')
            OR (NEW.published_revision_id IS DISTINCT FROM OLD.published_revision_id AND receipt.operation NOT IN ('approve','withdraw'))
            OR (NEW.withdrawn IS DISTINCT FROM OLD.withdrawn AND receipt.operation NOT IN ('approve','withdraw'))
            OR (receipt.operation IN ('settings_update','stop','resume'))
            OR (receipt.operation='request_review' AND (OLD.status<>'draft' OR NEW.status<>'in_review'
                OR receipt.object_id IS DISTINCT FROM NEW.current_revision_id OR revision.review_by IS NULL
                OR EXISTS (SELECT 1 FROM public.knowledge_guidancereview decision
                    JOIN public.knowledge_guidancecommandreceipt proof ON proof.id=decision.command_receipt_id
                    WHERE decision.revision_id=NEW.current_revision_id AND proof.control_sequence<receipt.control_sequence)))
            OR (receipt.operation IN ('approve','changes_requested') AND (OLD.status<>'in_review'
                OR NEW.status<>(CASE receipt.operation WHEN 'approve' THEN 'approved' ELSE 'changes_requested' END)
                OR NOT EXISTS (SELECT 1 FROM public.knowledge_guidancereview decision
                    WHERE decision.id=receipt.object_id AND decision.revision_id=NEW.current_revision_id)))
            OR (receipt.operation='approve' AND (NEW.approved_revision_id IS DISTINCT FROM NEW.current_revision_id
                OR NEW.published_revision_id IS DISTINCT FROM NEW.current_revision_id OR NEW.withdrawn))
            OR (receipt.operation='revise' AND revision.command_receipt_id IS DISTINCT FROM receipt.id)
            OR (receipt.operation IN ('create','revise') AND NEW.status<>'draft')
            OR (receipt.operation='withdraw' AND (OLD.status='withdrawn' OR NEW.status<>'withdrawn'
                OR NOT NEW.withdrawn OR NEW.published_revision_id IS NOT NULL))
        ) THEN
            RAISE EXCEPTION 'Guidance transition differs from its exact command' USING ERRCODE='23514';
        END IF;
    END IF;
    expected_capability := CASE receipt.operation
        WHEN 'settings_update' THEN 'knowledge.manage_settings'
        WHEN 'stop' THEN 'knowledge.manage_settings' WHEN 'resume' THEN 'knowledge.manage_settings'
        WHEN 'create' THEN 'knowledge.compose' WHEN 'revise' THEN 'knowledge.compose'
        WHEN 'request_review' THEN 'knowledge.compose' WHEN 'withdraw' THEN 'knowledge.withdraw'
        WHEN 'approve' THEN 'knowledge.review' WHEN 'changes_requested' THEN 'knowledge.review' END;
    IF receipt.id IS NULL OR receipt.organization_id <> NEW.organization_id OR receipt.edition_id <> NEW.edition_id
       OR (body ? 'command_receipt_id' AND (receipt.actor_id <> (body->>'actor_id')::uuid
           OR receipt.occurred_at <> (body->>'occurred_at')::timestamptz))
       OR NOT EXISTS (
        SELECT 1 FROM public.audit_auditevent audit
        JOIN public.audit_auditnativemutationwitness witness ON witness.audit_event_id = audit.id
          AND witness.transaction_stamp = public.maru_audit_current_native_transaction_stamp()
        JOIN public.effects_domainevent event ON event.causation_id = audit.id
        JOIN public.effects_outboxmessage outbox ON outbox.event_id = event.id AND outbox.destination = 'internal'
        WHERE audit.principal_kind = 'account' AND audit.principal_id = receipt.actor_id
          AND audit.organization_id = receipt.organization_id AND audit.event_edition_id = receipt.edition_id
          AND audit.operation = 'knowledge.command.' || receipt.operation
          AND audit.capability_code = expected_capability AND audit.outcome = 'allow'
          AND audit.target_type = 'knowledge.record' AND audit.target_id = receipt.object_id
          AND audit.occurred_at = receipt.occurred_at AND audit.correlation_id = receipt.correlation_id
          AND audit.source_channel = receipt.source_channel
          AND audit.idempotency_key_hash = encode(sha256(convert_to(receipt.idempotency_key::text, 'UTF8')), 'hex')
          AND event.event_name = 'knowledge.changed.v1' AND event.schema_version = 1
          AND event.organization_id = receipt.organization_id AND event.event_edition_id = receipt.edition_id
          AND event.aggregate_type = 'knowledge.edition' AND event.aggregate_id = receipt.edition_id
          AND event.aggregate_version = receipt.control_sequence AND event.actor_id = receipt.actor_id
          AND event.actor_kind = 'account' AND event.retention_class = 'guidance-evidence'
          AND audit.retention_class = 'guidance-evidence'
          AND event.occurred_at = receipt.occurred_at AND event.correlation_id = receipt.correlation_id
          AND event.payload = jsonb_build_object('operation', receipt.operation)
       ) THEN
        RAISE EXCEPTION 'Guidance requires its atomic native receipt audit and event' USING ERRCODE = '23514';
    END IF;


    IF TG_TABLE_NAME='knowledge_guidancecommandreceipt' THEN
        IF (NEW.operation IN ('settings_update','stop','resume'))<>(NEW.item_id IS NULL) THEN
            RAISE EXCEPTION 'A receipt requires its exact aggregate kind' USING ERRCODE='23514';
        END IF;
        SELECT count(*) INTO current_count FROM public.knowledge_guidancecommandreceipt
            WHERE edition_id=NEW.edition_id AND control_sequence<=NEW.control_sequence;
        IF current_count<>NEW.control_sequence THEN
            RAISE EXCEPTION 'Guidance edition receipts cannot skip' USING ERRCODE='23514';
        END IF;
        -- Every deferred receipt validates the final persisted head, permitting
        -- several valid commands in one outer transaction without stale equality.
        SELECT * INTO control FROM public.knowledge_guidancecontrol
            WHERE edition_id=NEW.edition_id AND organization_id=NEW.organization_id;
        SELECT * INTO head_receipt FROM public.knowledge_guidancecommandreceipt
            WHERE edition_id=NEW.edition_id ORDER BY control_sequence DESC LIMIT 1;
        SELECT object_id INTO reference_id FROM public.knowledge_guidancecommandreceipt
            WHERE edition_id=NEW.edition_id AND operation='settings_update'
            ORDER BY control_sequence DESC LIMIT 1;
        SELECT count(*) INTO current_count FROM public.knowledge_guidancecommandreceipt
            WHERE edition_id=NEW.edition_id AND operation IN ('settings_update','stop','resume');
        IF control.id IS NULL OR control.sequence IS DISTINCT FROM head_receipt.control_sequence
           OR control.settings_version IS DISTINCT FROM current_count
           OR control.current_settings_id IS DISTINCT FROM reference_id
           OR control.stopped IS DISTINCT FROM COALESCE((
               SELECT operation='stop' FROM public.knowledge_guidancecommandreceipt
               WHERE edition_id=NEW.edition_id AND operation IN ('stop','resume')
               ORDER BY control_sequence DESC LIMIT 1),false) THEN
            RAISE EXCEPTION 'A receipt requires its exact persisted edition head' USING ERRCODE='23514';
        END IF;
        CASE NEW.operation
        WHEN 'settings_update' THEN SELECT id INTO reference_id FROM public.knowledge_guidancesettingsrevision
            WHERE id=NEW.object_id AND command_receipt_id=NEW.id AND number=NEW.resulting_version;
        WHEN 'stop','resume' THEN SELECT id INTO reference_id FROM public.knowledge_guidancecontrol
            WHERE id=NEW.object_id AND edition_id=NEW.edition_id;
        WHEN 'create' THEN SELECT source.id INTO reference_id FROM public.knowledge_guidanceitem source
            JOIN public.knowledge_guidancerevision first_copy ON first_copy.item_id=source.id AND first_copy.number=1
            WHERE source.id=NEW.object_id AND source.id=NEW.item_id
              AND first_copy.command_receipt_id=NEW.id AND NEW.resulting_version=1;
        WHEN 'withdraw' THEN SELECT id INTO reference_id FROM public.knowledge_guidanceitem
            WHERE id=NEW.object_id AND id=NEW.item_id;
        WHEN 'revise' THEN SELECT id INTO reference_id FROM public.knowledge_guidancerevision
            WHERE id=NEW.object_id AND item_id=NEW.item_id AND command_receipt_id=NEW.id;
        WHEN 'request_review' THEN SELECT id INTO reference_id FROM public.knowledge_guidancerevision
            WHERE id=NEW.object_id AND item_id=NEW.item_id AND review_by IS NOT NULL;
        WHEN 'approve','changes_requested' THEN SELECT decision.id INTO reference_id
            FROM public.knowledge_guidancereview decision JOIN public.knowledge_guidancerevision source ON source.id=decision.revision_id
            WHERE decision.id=NEW.object_id AND decision.command_receipt_id=NEW.id AND source.item_id=NEW.item_id;
        ELSE RAISE EXCEPTION 'Unknown Guidance receipt operation' USING ERRCODE='23514';
        END CASE;
        IF reference_id IS NULL THEN
            RAISE EXCEPTION 'A receipt needs its exact owned result' USING ERRCODE='23514';
        END IF;
        IF NEW.item_id IS NOT NULL THEN
            SELECT * INTO item FROM public.knowledge_guidanceitem
                WHERE id=NEW.item_id AND edition_id=NEW.edition_id AND organization_id=NEW.organization_id;
            SELECT * INTO head_receipt FROM public.knowledge_guidancecommandreceipt
                WHERE item_id=NEW.item_id ORDER BY resulting_version DESC LIMIT 1;
            expected_status := CASE head_receipt.operation
                WHEN 'create' THEN 'draft' WHEN 'revise' THEN 'draft'
                WHEN 'request_review' THEN 'in_review' WHEN 'approve' THEN 'approved'
                WHEN 'changes_requested' THEN 'changes_requested' WHEN 'withdraw' THEN 'withdrawn' END;
            SELECT source.id INTO expected_revision_id FROM public.knowledge_guidancerevision source
                JOIN public.knowledge_guidancecommandreceipt proof ON proof.id=source.command_receipt_id
                WHERE source.item_id=NEW.item_id AND proof.operation IN ('create','revise')
                ORDER BY proof.resulting_version DESC LIMIT 1;
            SELECT decision.revision_id INTO expected_approved_id FROM public.knowledge_guidancereview decision
                JOIN public.knowledge_guidancecommandreceipt proof ON proof.id=decision.command_receipt_id
                WHERE proof.item_id=NEW.item_id AND proof.operation='approve'
                ORDER BY proof.resulting_version DESC LIMIT 1;
            SELECT COALESCE((SELECT operation='withdraw' FROM public.knowledge_guidancecommandreceipt
                WHERE item_id=NEW.item_id AND operation IN ('approve','withdraw')
                ORDER BY resulting_version DESC LIMIT 1),false) INTO expected_withdrawn;
            IF item.id IS NULL OR item.version IS DISTINCT FROM head_receipt.resulting_version
               OR expected_status IS NULL OR item.status IS DISTINCT FROM expected_status
               OR item.current_revision_id IS DISTINCT FROM expected_revision_id
               OR item.approved_revision_id IS DISTINCT FROM expected_approved_id
               OR item.withdrawn IS DISTINCT FROM expected_withdrawn
               OR item.published_revision_id IS DISTINCT FROM (CASE WHEN expected_withdrawn THEN NULL ELSE expected_approved_id END) THEN
                RAISE EXCEPTION 'A receipt requires its exact persisted Guidance head' USING ERRCODE='23514';
            END IF;
            SELECT count(*) INTO current_count FROM public.knowledge_guidancecommandreceipt
                WHERE item_id=NEW.item_id AND resulting_version<=NEW.resulting_version;
            IF current_count<>NEW.resulting_version OR NEW.resulting_version>4096 THEN
                RAISE EXCEPTION 'Guidance versions must be contiguous and bounded' USING ERRCODE='23514';
            END IF;
            SELECT sum(octet_length(record::text)) INTO retained_bytes FROM (
                SELECT to_jsonb(row) AS record FROM public.knowledge_guidancerevision row WHERE row.item_id=NEW.item_id
                UNION ALL SELECT to_jsonb(row) FROM public.knowledge_guidancereview row JOIN public.knowledge_guidancerevision rev ON rev.id=row.revision_id WHERE rev.item_id=NEW.item_id
                UNION ALL SELECT to_jsonb(row) FROM public.knowledge_guidancesettingsrevision row WHERE row.id IN (SELECT settings_revision_id FROM public.knowledge_guidancerevision WHERE item_id=NEW.item_id)
                UNION ALL SELECT to_jsonb(row) FROM public.knowledge_guidancecommandreceipt row WHERE row.item_id=NEW.item_id OR row.id IN (SELECT command_receipt_id FROM public.knowledge_guidancesettingsrevision WHERE id IN (SELECT settings_revision_id FROM public.knowledge_guidancerevision WHERE item_id=NEW.item_id))
            ) retained;
            IF retained_bytes>8388608 THEN
                RAISE EXCEPTION 'Guidance evidence exceeds its complete export budget' USING ERRCODE='23514';
            END IF;
            -- Every deferred receipt checks the final persisted head. An earlier
            -- ordinary command must not demand a second reserve after withdrawal.
            IF head_receipt.operation<>'withdraw' AND retained_bytes+8192>8388608 THEN
                RAISE EXCEPTION 'Guidance must retain space for one reasoned withdrawal' USING ERRCODE='23514';
            END IF;
        END IF;
        IF (SELECT count(*) FROM public.knowledge_guidanceitem WHERE edition_id=NEW.edition_id)>500 THEN
            RAISE EXCEPTION 'Guidance exceeds the complete current inventory budget' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME='knowledge_guidancesettingsrevision' THEN
        IF receipt.operation<>'settings_update' OR receipt.object_id<>NEW.id OR receipt.resulting_version<>NEW.number
           OR length(btrim(NEW.policy_name))=0 OR length(btrim(NEW.record_owner))=0
           OR length(NEW.policy_description)>2000
           OR (NEW.policy_url='' AND length(btrim(NEW.policy_description))=0)
           OR (NEW.policy_url<>'' AND NEW.policy_url !~ '^https://[^/@]+([/:?#]|$)')
           OR NEW.review_on<(SELECT (receipt.occurred_at AT TIME ZONE edition.time_zone)::date
               FROM public.events_eventedition edition WHERE edition.id=NEW.edition_id) THEN
            RAISE EXCEPTION 'Rules require actual readable current confirmation' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME='knowledge_guidancerevision' THEN
        SELECT * INTO item FROM public.knowledge_guidanceitem WHERE id=NEW.item_id;
        SELECT * INTO rules FROM public.knowledge_guidancesettingsrevision WHERE id=NEW.settings_revision_id;
        SELECT * INTO previous FROM public.knowledge_guidancerevision WHERE id=NEW.previous_revision_id;
        SELECT object_id INTO reference_id FROM public.knowledge_guidancecommandreceipt
            WHERE edition_id=NEW.edition_id AND operation='settings_update' AND control_sequence<receipt.control_sequence
            ORDER BY control_sequence DESC LIMIT 1;
        IF item.id IS NULL OR rules.id IS NULL OR item.organization_id<>NEW.organization_id OR item.edition_id<>NEW.edition_id
           OR rules.organization_id<>NEW.organization_id OR rules.edition_id<>NEW.edition_id
           OR NEW.settings_revision_id IS DISTINCT FROM reference_id
           OR receipt.operation NOT IN ('create','revise') OR receipt.item_id<>NEW.item_id
           OR (receipt.operation='revise' AND receipt.object_id IS DISTINCT FROM NEW.id)
           OR (receipt.operation='create' AND (receipt.object_id IS DISTINCT FROM NEW.item_id OR NEW.number<>1))
           OR length(btrim(NEW.title))=0 OR length(btrim(NEW.body))=0 OR length(NEW.body) NOT BETWEEN 1 AND 12000
           OR NEW.language_code<>item.language_code OR NOT EXISTS (
               SELECT 1 FROM public.events_eventedition edition WHERE edition.id=NEW.edition_id AND NEW.language_code=ANY(edition.language_codes))
           OR NEW.number NOT BETWEEN 1 AND 256 OR length(btrim(NEW.team_label))=0
           OR (NEW.number=1 AND (NEW.previous_revision_id IS NOT NULL OR NEW.base_approved_revision_id IS NOT NULL))
           OR (NEW.number>1 AND (previous.id IS NULL OR previous.item_id<>NEW.item_id OR previous.number+1<>NEW.number))
           OR jsonb_typeof(NEW.placements)<>'array' OR jsonb_array_length(NEW.placements)>2
           OR EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.placements) p WHERE jsonb_typeof(p)<>'string'
               OR (p#>>'{}') NOT IN ('knowledge.compose','announcements.compose'))
           OR (SELECT count(DISTINCT p) FROM jsonb_array_elements(NEW.placements) p)<>jsonb_array_length(NEW.placements)
           OR (NEW.placements ? 'announcements.compose' AND NOT EXISTS (
               SELECT 1 FROM public.events_eventedition edition WHERE edition.id=NEW.edition_id AND edition.adoption_profile_code='announcements_guidance')) THEN
            RAISE EXCEPTION 'Guidance revision needs exact scope, metadata and contiguous history' USING ERRCODE='23514';
        END IF;
        IF previous.id IS NOT NULL THEN
            IF NEW.round_id=previous.round_id AND EXISTS (
                SELECT 1 FROM public.knowledge_guidancereview decision
                JOIN public.knowledge_guidancecommandreceipt proof ON proof.id=decision.command_receipt_id
                WHERE decision.revision_id=previous.id AND decision.decision='approve'
                  AND proof.control_sequence<receipt.control_sequence
            ) THEN
                RAISE EXCEPTION 'An approved baseline starts a fresh review round' USING ERRCODE='23514';
            END IF;
            IF NEW.round_id<>previous.round_id AND EXISTS (
                SELECT 1 FROM public.knowledge_guidancerevision earlier
                WHERE earlier.item_id=NEW.item_id AND earlier.round_id=NEW.round_id AND earlier.number<NEW.number
            ) THEN
                RAISE EXCEPTION 'A new review round cannot reuse earlier authorship' USING ERRCODE='23514';
            END IF;
            IF NEW.round_id=previous.round_id THEN
                IF NEW.base_approved_revision_id IS DISTINCT FROM previous.base_approved_revision_id THEN
                    RAISE EXCEPTION 'Draft authorship cannot be reset' USING ERRCODE='23514';
                END IF;
            ELSIF NEW.base_approved_revision_id IS DISTINCT FROM previous.id OR NOT EXISTS (
                SELECT 1 FROM public.knowledge_guidancereview decision
                JOIN public.knowledge_guidancecommandreceipt proof ON proof.id=decision.command_receipt_id
                WHERE decision.revision_id=previous.id AND decision.decision='approve'
                  AND proof.control_sequence<receipt.control_sequence
            ) THEN
                RAISE EXCEPTION 'A new review round requires an approved baseline' USING ERRCODE='23514';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME='knowledge_guidancereview' THEN
        SELECT * INTO revision FROM public.knowledge_guidancerevision WHERE id=NEW.revision_id;
        IF revision.id IS NULL OR revision.organization_id<>NEW.organization_id OR revision.edition_id<>NEW.edition_id
           OR revision.review_by IS NULL OR receipt.operation<>NEW.decision OR receipt.object_id<>NEW.id
           OR receipt.item_id<>revision.item_id
           OR EXISTS (SELECT 1 FROM public.knowledge_guidancerevision author
               WHERE author.item_id=revision.item_id AND author.round_id=revision.round_id
                 AND author.number<=revision.number AND author.actor_id=NEW.actor_id)
           OR NOT EXISTS (SELECT 1 FROM public.knowledge_guidancecommandreceipt request
               WHERE request.operation='request_review' AND request.object_id=NEW.revision_id
                 AND request.item_id=revision.item_id AND request.resulting_version=receipt.resulting_version-1
                 AND request.control_sequence<receipt.control_sequence) THEN
            RAISE EXCEPTION 'Review needs the current exact submission and independent editor' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public, pg_temp;
"""

FORWARD_SQL += "\n".join(
    f"""
CREATE TRIGGER kno_{index}_row_guard BEFORE INSERT OR UPDATE OR DELETE ON public.knowledge_{table}
FOR EACH ROW EXECUTE FUNCTION public.maru_knowledge_row_guard();
CREATE CONSTRAINT TRIGGER kno_{index}_graph_guard AFTER INSERT OR UPDATE ON public.knowledge_{table}
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.maru_knowledge_graph_guard();
CREATE TRIGGER kno_{index}_no_truncate BEFORE TRUNCATE ON public.knowledge_{table}
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_knowledge_no_truncate();
""" for index, table in enumerate(TABLES)
)
FORWARD_SQL += "\n".join(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC;" for signature in FUNCTIONS)
REVERSE_SQL = "\n".join(
    f"DROP TRIGGER kno_{index}_{kind} ON public.knowledge_{table};"
    for index, table in enumerate(TABLES) for kind in ("row_guard", "graph_guard", "no_truncate")
) + "\n" + "\n".join(f"DROP FUNCTION public.{signature};" for signature in reversed(FUNCTIONS))


class Migration(migrations.Migration):
    dependencies = [
        ("knowledge", "0001_initial"),
        ("events", "0024_guidance_adoption_downgrade_fence"),
        ("authorization", "0046_guidance_authority_integrity"),
        ("audit", "0009_native_mutation_witness"),
        ("effects", "0003_effect_replay_receipts"),
    ]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
