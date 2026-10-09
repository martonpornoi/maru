"""Native ownership, immutable revision rounds and atomic evidence graph."""

from django.db import migrations

TABLES = (
    "announcementcontrol", "announcement", "announcementsettingsrevision",
    "announcementrevision", "announcementvariant", "announcementreview",
    "announcementpublicationreport", "announcementcommandreceipt",
)
FUNCTIONS = (
    "maru_announcements_row_guard()", "maru_announcements_graph_guard()",
    "maru_announcements_no_truncate()",
)

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_announcements_row_guard()
RETURNS trigger AS $$
DECLARE
    body jsonb := to_jsonb(NEW);
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Announcement history is retained' USING ERRCODE = '23514';
    END IF;
    IF TG_OP='INSERT' AND TG_TABLE_NAME='announcements_announcement' AND (
        (body->>'version')::bigint<>1 OR body->>'status'<>'draft'
        OR body->>'current_revision_id' IS NOT NULL OR body->>'approved_revision_id' IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'An announcement must start as an unreviewed draft' USING ERRCODE='23514';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF TG_TABLE_NAME NOT IN ('announcements_announcementcontrol', 'announcements_announcement')
           OR NEW.id <> OLD.id OR NEW.organization_id <> OLD.organization_id
           OR NEW.edition_id <> OLD.edition_id OR NEW.created_at <> OLD.created_at THEN
            RAISE EXCEPTION 'Announcement evidence is immutable' USING ERRCODE = '23514';
        END IF;
        IF TG_TABLE_NAME = 'announcements_announcementcontrol' THEN
            IF NEW.sequence <> OLD.sequence + 1
               OR NEW.settings_version NOT IN (OLD.settings_version, OLD.settings_version + 1) THEN
                RAISE EXCEPTION 'Announcement control requires contiguous evidence' USING ERRCODE = '23514';
            END IF;
        ELSIF NOT (NEW.version = OLD.version + 1 OR
            (OLD.version = 1 AND NEW.version = 1 AND OLD.current_revision_id IS NULL
             AND NEW.current_revision_id IS NOT NULL AND NEW.status = 'draft')) THEN
            RAISE EXCEPTION 'Announcement version must advance exactly once' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.events_eventedition edition
        JOIN public.organizations_conventionseries series ON series.id = edition.series_id
        WHERE edition.id = NEW.edition_id AND edition.organization_id = NEW.organization_id
          AND series.organization_id = NEW.organization_id
          AND edition.adoption_profile_code = 'announcements_only'
          AND edition.adoption_profile_version = 1
    ) THEN
        RAISE EXCEPTION 'Announcement scope requires its exact adopted edition' USING ERRCODE = '23514';
    END IF;
    IF body ? 'actor_id' AND NOT EXISTS (
        SELECT 1 FROM public.identity_account actor WHERE actor.id = (body->>'actor_id')::uuid
          AND actor.is_active AND actor.email_verified_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Announcement writes require a current verified actor' USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME='announcements_announcementcommandreceipt' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.events_eventedition edition
            JOIN public.organizations_organization org ON org.id=edition.organization_id
            JOIN public.organizations_conventionseries series ON series.id=edition.series_id
            WHERE edition.id=NEW.edition_id AND org.lifecycle='active' AND series.is_active
              AND edition.lifecycle IN ('draft','preparing','ready','live')
        ) THEN
            RAISE EXCEPTION 'The edition does not admit announcement writes' USING ERRCODE='23514';
        END IF;
        IF body->>'operation' IN ('create','revise','request_review','approve','changes_requested','resume')
           AND NOT EXISTS (
            SELECT 1 FROM public.announcements_announcementcontrol control
            JOIN public.announcements_announcementsettingsrevision rules ON rules.id=control.current_settings_id
            JOIN public.events_eventedition edition ON edition.id=control.edition_id
            WHERE control.edition_id=NEW.edition_id AND NOT control.stopped
              AND rules.review_on >= (statement_timestamp() AT TIME ZONE edition.time_zone)::date
        ) THEN
            RAISE EXCEPTION 'Current rules and open announcement work are required' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_announcements_no_truncate()
RETURNS trigger AS $$
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed() THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'Announcement evidence cannot be truncated' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_announcements_graph_guard()
RETURNS trigger AS $$
DECLARE
    body jsonb := to_jsonb(NEW);
    receipt public.announcements_announcementcommandreceipt;
    revision public.announcements_announcementrevision;
    previous public.announcements_announcementrevision;
    item public.announcements_announcement;
    settings public.announcements_announcementsettingsrevision;
    variant public.announcements_announcementvariant;
    prior_report public.announcements_announcementpublicationreport;
    control public.announcements_announcementcontrol;
    head_receipt public.announcements_announcementcommandreceipt;
    state_receipt public.announcements_announcementcommandreceipt;
    expected_capability text;
    expected_operation text;
    reference_id uuid;
    aggregate_id uuid;
    current_count bigint;
    retained_bytes bigint;
    expected_revision_id uuid;
    expected_approved_id uuid;
    expected_status text;
BEGIN
    IF TG_TABLE_NAME = 'announcements_announcementcommandreceipt' THEN
        receipt := NEW;
    ELSIF body ? 'command_receipt_id' THEN
        SELECT * INTO receipt FROM public.announcements_announcementcommandreceipt
        WHERE id = (body->>'command_receipt_id')::uuid;
    ELSIF TG_TABLE_NAME = 'announcements_announcementcontrol' THEN
        IF NEW.sequence = 0 THEN
            IF NOT EXISTS (SELECT 1 FROM public.announcements_announcementcommandreceipt
                WHERE edition_id = NEW.edition_id AND control_sequence = 1
                  AND operation = 'settings_update') THEN
                RAISE EXCEPTION 'An empty control requires initial settings evidence' USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END IF;
        SELECT * INTO receipt FROM public.announcements_announcementcommandreceipt
        WHERE edition_id = NEW.edition_id AND control_sequence = NEW.sequence;
        IF (TG_OP = 'UPDATE' AND (
            (NEW.settings_version <> OLD.settings_version AND receipt.operation NOT IN ('settings_update','stop','resume'))
            OR (NEW.current_settings_id IS DISTINCT FROM OLD.current_settings_id AND receipt.operation <> 'settings_update')
            OR (NEW.stopped IS DISTINCT FROM OLD.stopped AND receipt.operation NOT IN ('stop','resume'))
            OR (receipt.operation IN ('settings_update','stop','resume') AND NEW.settings_version <> OLD.settings_version + 1)
            OR (receipt.operation='stop' AND (OLD.stopped OR NOT NEW.stopped))
            OR (receipt.operation='resume' AND (NOT OLD.stopped OR NEW.stopped))
            OR (receipt.operation='settings_update' AND receipt.object_id IS DISTINCT FROM NEW.current_settings_id)
        )) OR (receipt.operation IN ('settings_update','stop','resume') AND receipt.resulting_version <> NEW.settings_version) THEN
            RAISE EXCEPTION 'Settings transitions require their own exact operation' USING ERRCODE = '23514';
        END IF;
        IF NEW.current_settings_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.announcements_announcementsettingsrevision setting
            WHERE setting.id = NEW.current_settings_id AND setting.organization_id = NEW.organization_id
              AND setting.edition_id = NEW.edition_id AND setting.number <= NEW.settings_version
        ) THEN
            RAISE EXCEPTION 'Current rules belong to this edition' USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT * INTO receipt FROM public.announcements_announcementcommandreceipt
        WHERE announcement_id = NEW.id AND resulting_version = NEW.version;
        IF NEW.current_revision_id IS NOT NULL THEN
            SELECT * INTO revision FROM public.announcements_announcementrevision WHERE id = NEW.current_revision_id;
            IF revision.announcement_id IS DISTINCT FROM NEW.id OR revision.organization_id <> NEW.organization_id
               OR revision.edition_id <> NEW.edition_id THEN
                RAISE EXCEPTION 'Current copy must belong to its announcement' USING ERRCODE = '23514';
            END IF;
        ELSIF TG_OP <> 'INSERT' OR NEW.version <> 1 OR receipt.operation <> 'create' THEN
            RAISE EXCEPTION 'An announcement requires its first revision' USING ERRCODE = '23514';
        END IF;
        IF NEW.approved_revision_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.announcements_announcementrevision source
            JOIN public.announcements_announcementreview decision ON decision.revision_id = source.id
            WHERE source.id = NEW.approved_revision_id AND source.announcement_id = NEW.id
              AND source.organization_id = NEW.organization_id AND source.edition_id = NEW.edition_id
              AND decision.decision = 'approve'
        ) THEN
            RAISE EXCEPTION 'Approved copy requires independent evidence' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' THEN
            IF OLD.status = 'cancelled' AND receipt.operation NOT IN ('record_publication','correct_publication','withdraw_report')
               OR (NEW.current_revision_id IS DISTINCT FROM OLD.current_revision_id AND receipt.operation NOT IN ('create','revise'))
               OR (NEW.approved_revision_id IS DISTINCT FROM OLD.approved_revision_id AND receipt.operation <> 'approve')
               OR (receipt.operation = 'request_review' AND (OLD.status <> 'draft' OR NEW.status <> 'in_review'
                   OR receipt.object_id IS DISTINCT FROM NEW.current_revision_id))
               OR (receipt.operation IN ('approve','changes_requested') AND (OLD.status <> 'in_review'
                   OR NEW.status <> (CASE receipt.operation WHEN 'approve' THEN 'approved' ELSE 'changes_requested' END)
                   OR NOT EXISTS (SELECT 1 FROM public.announcements_announcementreview decision
                       WHERE decision.id=receipt.object_id AND decision.revision_id=NEW.current_revision_id)))
               OR (receipt.operation='approve' AND NEW.approved_revision_id IS DISTINCT FROM NEW.current_revision_id)
               OR (receipt.operation='revise' AND revision.command_receipt_id IS DISTINCT FROM receipt.id)
               OR (receipt.operation IN ('create','revise') AND NEW.status <> 'draft')
               OR (receipt.operation = 'cancel' AND NEW.status <> 'cancelled')
               OR (receipt.operation IN ('record_publication','correct_publication','withdraw_report') AND
                   (NEW.status <> OLD.status OR NEW.current_revision_id IS DISTINCT FROM OLD.current_revision_id
                    OR NEW.approved_revision_id IS DISTINCT FROM OLD.approved_revision_id)) THEN
                RAISE EXCEPTION 'Announcement transition differs from its command' USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;

    expected_capability := CASE receipt.operation
        WHEN 'settings_update' THEN 'announcements.manage_settings'
        WHEN 'stop' THEN 'announcements.manage_settings' WHEN 'resume' THEN 'announcements.manage_settings'
        WHEN 'create' THEN 'announcements.compose' WHEN 'revise' THEN 'announcements.compose'
        WHEN 'request_review' THEN 'announcements.compose' WHEN 'cancel' THEN 'announcements.compose'
        WHEN 'approve' THEN 'announcements.review' WHEN 'changes_requested' THEN 'announcements.review'
        ELSE 'announcements.record_publication' END;
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
          AND audit.operation = 'announcements.command.' || receipt.operation
          AND audit.capability_code = expected_capability AND audit.outcome = 'allow'
          AND audit.target_type = 'announcements.record' AND audit.target_id = receipt.object_id
          AND audit.occurred_at = receipt.occurred_at AND audit.correlation_id = receipt.correlation_id
          AND audit.source_channel = receipt.source_channel
          AND audit.idempotency_key_hash = encode(sha256(convert_to(receipt.idempotency_key::text, 'UTF8')), 'hex')
          AND event.event_name = 'announcements.changed.v1' AND event.schema_version = 1
          AND event.organization_id = receipt.organization_id AND event.event_edition_id = receipt.edition_id
          AND event.aggregate_type = 'announcements.edition' AND event.aggregate_id = receipt.edition_id
          AND event.aggregate_version = receipt.control_sequence AND event.actor_id = receipt.actor_id
          AND event.occurred_at = receipt.occurred_at AND event.correlation_id = receipt.correlation_id
          AND event.payload = jsonb_build_object('operation', receipt.operation)
       ) THEN
        RAISE EXCEPTION 'Announcement requires its atomic native receipt audit and event' USING ERRCODE = '23514';
    END IF;

    IF TG_TABLE_NAME = 'announcements_announcementcommandreceipt' THEN
        IF (NEW.operation IN ('settings_update','stop','resume')) <> (NEW.announcement_id IS NULL) THEN
            RAISE EXCEPTION 'Receipt operation requires its exact aggregate kind' USING ERRCODE='23514';
        END IF;
        SELECT count(*) INTO current_count FROM public.announcements_announcementcommandreceipt
        WHERE edition_id = NEW.edition_id AND control_sequence <= NEW.control_sequence;
        IF current_count <> NEW.control_sequence THEN
            RAISE EXCEPTION 'Announcement receipt sequence cannot skip' USING ERRCODE = '23514';
        END IF;
        -- Deferred receipts all validate the final persisted head, so several
        -- valid commands may still be committed in one outer transaction.
        SELECT * INTO control FROM public.announcements_announcementcontrol
            WHERE edition_id=NEW.edition_id AND organization_id=NEW.organization_id;
        SELECT * INTO head_receipt FROM public.announcements_announcementcommandreceipt
            WHERE edition_id=NEW.edition_id ORDER BY control_sequence DESC LIMIT 1;
        SELECT object_id INTO reference_id FROM public.announcements_announcementcommandreceipt
            WHERE edition_id=NEW.edition_id AND operation='settings_update'
            ORDER BY control_sequence DESC LIMIT 1;
        SELECT count(*) INTO current_count FROM public.announcements_announcementcommandreceipt
            WHERE edition_id=NEW.edition_id AND operation IN ('settings_update','stop','resume');
        IF control.id IS NULL OR control.sequence IS DISTINCT FROM head_receipt.control_sequence
           OR control.settings_version IS DISTINCT FROM current_count
           OR control.current_settings_id IS DISTINCT FROM reference_id
           OR control.stopped IS DISTINCT FROM COALESCE((
               SELECT operation='stop' FROM public.announcements_announcementcommandreceipt
               WHERE edition_id=NEW.edition_id AND operation IN ('stop','resume')
               ORDER BY control_sequence DESC LIMIT 1), false) THEN
            RAISE EXCEPTION 'Receipt requires its exact persisted edition head' USING ERRCODE='23514';
        END IF;
        CASE NEW.operation
        WHEN 'settings_update' THEN SELECT id INTO reference_id FROM public.announcements_announcementsettingsrevision
            WHERE id=NEW.object_id AND command_receipt_id=NEW.id AND number=NEW.resulting_version;
        WHEN 'stop', 'resume' THEN SELECT id INTO reference_id FROM public.announcements_announcementcontrol
            WHERE id=NEW.object_id AND edition_id=NEW.edition_id;
        WHEN 'create' THEN SELECT announcement.id INTO reference_id FROM public.announcements_announcement announcement
            JOIN public.announcements_announcementrevision first_copy ON first_copy.announcement_id=announcement.id AND first_copy.number=1
            WHERE announcement.id=NEW.object_id AND announcement.id=NEW.announcement_id
              AND first_copy.command_receipt_id=NEW.id AND NEW.resulting_version=1;
        WHEN 'cancel' THEN SELECT id INTO reference_id FROM public.announcements_announcement
            WHERE id=NEW.object_id AND id=NEW.announcement_id;
        WHEN 'revise' THEN SELECT id INTO reference_id FROM public.announcements_announcementrevision
            WHERE id=NEW.object_id AND announcement_id=NEW.announcement_id AND command_receipt_id=NEW.id;
        WHEN 'request_review' THEN SELECT id INTO reference_id FROM public.announcements_announcementrevision
            WHERE id=NEW.object_id AND announcement_id=NEW.announcement_id;
        WHEN 'approve', 'changes_requested' THEN SELECT decision.id INTO reference_id
            FROM public.announcements_announcementreview decision JOIN public.announcements_announcementrevision source ON source.id=decision.revision_id
            WHERE decision.id=NEW.object_id AND decision.command_receipt_id=NEW.id AND source.announcement_id=NEW.announcement_id;
        ELSE SELECT report.id INTO reference_id FROM public.announcements_announcementpublicationreport report
            JOIN public.announcements_announcementvariant copy ON copy.id=report.variant_id
            JOIN public.announcements_announcementrevision source ON source.id=copy.revision_id
            WHERE report.id=NEW.object_id AND report.command_receipt_id=NEW.id AND source.announcement_id=NEW.announcement_id;
        END CASE;
        IF reference_id IS NULL THEN
            RAISE EXCEPTION 'Receipt result is not its exact owned record' USING ERRCODE = '23514';
        END IF;
        IF NEW.announcement_id IS NOT NULL THEN
            SELECT * INTO item FROM public.announcements_announcement
                WHERE id=NEW.announcement_id AND edition_id=NEW.edition_id AND organization_id=NEW.organization_id;
            SELECT * INTO head_receipt FROM public.announcements_announcementcommandreceipt
                WHERE announcement_id=NEW.announcement_id ORDER BY resulting_version DESC LIMIT 1;
            SELECT * INTO state_receipt FROM public.announcements_announcementcommandreceipt
                WHERE announcement_id=NEW.announcement_id
                  AND operation IN ('create','revise','request_review','approve','changes_requested','cancel')
                ORDER BY resulting_version DESC LIMIT 1;
            expected_status := CASE state_receipt.operation
                WHEN 'create' THEN 'draft' WHEN 'revise' THEN 'draft'
                WHEN 'request_review' THEN 'in_review' WHEN 'approve' THEN 'approved'
                WHEN 'changes_requested' THEN 'changes_requested' WHEN 'cancel' THEN 'cancelled' END;
            SELECT source.id INTO expected_revision_id FROM public.announcements_announcementrevision source
                JOIN public.announcements_announcementcommandreceipt proof ON proof.id=source.command_receipt_id
                WHERE source.announcement_id=NEW.announcement_id AND proof.operation IN ('create','revise')
                ORDER BY proof.resulting_version DESC LIMIT 1;
            SELECT decision.revision_id INTO expected_approved_id FROM public.announcements_announcementreview decision
                JOIN public.announcements_announcementcommandreceipt proof ON proof.id=decision.command_receipt_id
                WHERE proof.announcement_id=NEW.announcement_id AND proof.operation='approve'
                ORDER BY proof.resulting_version DESC LIMIT 1;
            IF item.id IS NULL OR item.version IS DISTINCT FROM head_receipt.resulting_version
               OR expected_status IS NULL OR item.status IS DISTINCT FROM expected_status
               OR item.current_revision_id IS DISTINCT FROM expected_revision_id
               OR item.approved_revision_id IS DISTINCT FROM expected_approved_id THEN
                RAISE EXCEPTION 'Receipt requires its exact persisted announcement head' USING ERRCODE='23514';
            END IF;
            SELECT count(*) INTO current_count FROM public.announcements_announcementcommandreceipt
            WHERE announcement_id=NEW.announcement_id AND resulting_version <= NEW.resulting_version;
            IF current_count <> NEW.resulting_version OR NEW.resulting_version > 4096 THEN
                RAISE EXCEPTION 'Announcement command versions must be contiguous and bounded' USING ERRCODE='23514';
            END IF;
            SELECT sum(octet_length(record::text)) INTO retained_bytes FROM (
                SELECT to_jsonb(row) AS record FROM public.announcements_announcementrevision row WHERE row.announcement_id=NEW.announcement_id
                UNION ALL SELECT to_jsonb(row) FROM public.announcements_announcementvariant row JOIN public.announcements_announcementrevision rev ON rev.id=row.revision_id WHERE rev.announcement_id=NEW.announcement_id
                UNION ALL SELECT to_jsonb(row) FROM public.announcements_announcementreview row JOIN public.announcements_announcementrevision rev ON rev.id=row.revision_id WHERE rev.announcement_id=NEW.announcement_id
                UNION ALL SELECT to_jsonb(row) FROM public.announcements_announcementpublicationreport row JOIN public.announcements_announcementvariant copy ON copy.id=row.variant_id JOIN public.announcements_announcementrevision rev ON rev.id=copy.revision_id WHERE rev.announcement_id=NEW.announcement_id
                UNION ALL SELECT to_jsonb(row) FROM public.announcements_announcementsettingsrevision row WHERE row.id IN (SELECT settings_revision_id FROM public.announcements_announcementrevision WHERE announcement_id=NEW.announcement_id)
                UNION ALL SELECT to_jsonb(row) FROM public.announcements_announcementcommandreceipt row WHERE row.announcement_id=NEW.announcement_id OR row.id IN (SELECT command_receipt_id FROM public.announcements_announcementsettingsrevision WHERE id IN (SELECT settings_revision_id FROM public.announcements_announcementrevision WHERE announcement_id=NEW.announcement_id))
            ) retained;
            IF retained_bytes > 8388608 THEN
                RAISE EXCEPTION 'Announcement retained evidence exceeds its complete export bound' USING ERRCODE='23514';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'announcements_announcementsettingsrevision' THEN
        IF receipt.operation <> 'settings_update' OR receipt.object_id <> NEW.id OR receipt.resulting_version <> NEW.number
           OR NEW.review_on < (SELECT (receipt.occurred_at AT TIME ZONE edition.time_zone)::date FROM public.events_eventedition edition WHERE edition.id=NEW.edition_id)
           OR jsonb_typeof(NEW.channels) <> 'array' OR jsonb_array_length(NEW.channels) NOT BETWEEN 1 AND 16
           OR EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.channels) c WHERE
               jsonb_typeof(c) <> 'object' OR NOT c ?& array['code','label','url']
               OR (SELECT count(*) FROM jsonb_object_keys(c)) <> 3
               OR jsonb_typeof(c->'code') <> 'string' OR c->>'code' !~ '^[a-z][a-z0-9_-]{0,39}$'
               OR jsonb_typeof(c->'label') <> 'string' OR length(c->>'label') NOT BETWEEN 1 AND 100
               OR jsonb_typeof(c->'url') <> 'string' OR length(c->>'url') > 2000
               OR (c->>'url' <> '' AND c->>'url' !~ '^https://[^/@]+([/:?#]|$)'))
           OR EXISTS (SELECT 1 FROM public.announcements_announcementsettingsrevision prior,
               jsonb_array_elements(prior.channels) old_channel, jsonb_array_elements(NEW.channels) channel
               WHERE prior.edition_id=NEW.edition_id AND prior.number < NEW.number
                 AND old_channel->>'code'=channel->>'code' AND old_channel->>'url'=''
                 AND old_channel->>'label' <> channel->>'label')
           OR (SELECT count(DISTINCT c->>'code') FROM jsonb_array_elements(NEW.channels) c) <> jsonb_array_length(NEW.channels) THEN
            RAISE EXCEPTION 'Record rules require closed explicit channel settings' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'announcements_announcementrevision' THEN
        SELECT * INTO item FROM public.announcements_announcement WHERE id=NEW.announcement_id;
        SELECT * INTO settings FROM public.announcements_announcementsettingsrevision WHERE id=NEW.settings_revision_id;
        SELECT * INTO previous FROM public.announcements_announcementrevision WHERE id=NEW.previous_revision_id;
        IF item.id IS NULL OR settings.id IS NULL OR item.organization_id <> NEW.organization_id OR item.edition_id <> NEW.edition_id
           OR settings.organization_id <> NEW.organization_id OR settings.edition_id <> NEW.edition_id
           OR receipt.operation NOT IN ('create','revise') OR receipt.announcement_id <> NEW.announcement_id
           OR (receipt.operation='revise' AND receipt.object_id IS DISTINCT FROM NEW.id)
           OR (receipt.operation='create' AND (receipt.object_id IS DISTINCT FROM NEW.announcement_id OR NEW.number<>1))
           OR length(NEW.body) NOT BETWEEN 1 AND 8000
           OR NOT EXISTS (SELECT 1 FROM public.events_eventedition edition WHERE edition.id=NEW.edition_id
               AND NEW.language_code=ANY(edition.language_codes))
           OR NEW.number NOT BETWEEN 1 AND 256
           OR (NEW.number=1 AND (NEW.previous_revision_id IS NOT NULL OR NEW.base_approved_revision_id IS NOT NULL))
           OR (NEW.number>1 AND (previous.id IS NULL OR previous.announcement_id <> NEW.announcement_id
               OR previous.number + 1 <> NEW.number)) THEN
            RAISE EXCEPTION 'Copy revision requires contiguous exact scope' USING ERRCODE = '23514';
        END IF;
        IF previous.id IS NOT NULL THEN
            IF NEW.round_id = previous.round_id THEN
                IF NEW.base_approved_revision_id IS DISTINCT FROM previous.base_approved_revision_id THEN
                    RAISE EXCEPTION 'Draft authorship cannot be reset' USING ERRCODE = '23514';
                END IF;
            ELSIF NEW.base_approved_revision_id IS DISTINCT FROM previous.id OR NOT EXISTS (
                SELECT 1 FROM public.announcements_announcementreview review
                JOIN public.announcements_announcementcommandreceipt proof ON proof.id=review.command_receipt_id
                WHERE review.revision_id=previous.id AND review.decision='approve'
                  AND proof.control_sequence < receipt.control_sequence
            ) THEN
                RAISE EXCEPTION 'A new review round needs an approved baseline' USING ERRCODE = '23514';
            END IF;
        END IF;
        IF (SELECT count(*) FROM public.announcements_announcementvariant WHERE revision_id=NEW.id) NOT BETWEEN 1 AND 32
           OR (SELECT sum(text_bytes) FROM public.announcements_announcementrevision WHERE announcement_id=NEW.announcement_id) > 8388608 THEN
            RAISE EXCEPTION 'Announcement copy exceeds its complete export bound' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'announcements_announcementvariant' THEN
        SELECT * INTO revision FROM public.announcements_announcementrevision WHERE id=NEW.revision_id;
        SELECT * INTO settings FROM public.announcements_announcementsettingsrevision WHERE id=revision.settings_revision_id;
        IF revision.id IS NULL OR revision.organization_id <> NEW.organization_id OR revision.edition_id <> NEW.edition_id
           OR revision.actor_id <> NEW.actor_id OR revision.command_receipt_id <> NEW.command_receipt_id
           OR revision.occurred_at <> NEW.occurred_at
           OR length(NEW.body) NOT BETWEEN 1 AND 8000
           OR NOT EXISTS (SELECT 1 FROM public.events_eventedition edition WHERE edition.id=NEW.edition_id
               AND NEW.language_code=ANY(edition.language_codes))
           OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(settings.channels) c WHERE
               c->>'code'=NEW.channel_code AND c->>'label'=NEW.channel_label AND c->>'url'=NEW.channel_url)
           OR NEW.copy_digest <> encode(sha256(convert_to('{"body":' || to_jsonb(NEW.body)::text || ',"headline":' || to_jsonb(NEW.headline)::text || '}', 'UTF8')), 'hex') THEN
            RAISE EXCEPTION 'Variant requires exact source copy and destination' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'announcements_announcementreview' THEN
        SELECT * INTO revision FROM public.announcements_announcementrevision WHERE id=NEW.revision_id;
        IF revision.id IS NULL OR revision.organization_id <> NEW.organization_id OR revision.edition_id <> NEW.edition_id
           OR receipt.operation <> NEW.decision OR receipt.object_id <> NEW.id OR receipt.announcement_id <> revision.announcement_id
           OR EXISTS (SELECT 1 FROM public.announcements_announcementrevision author WHERE
               author.announcement_id=revision.announcement_id AND author.round_id=revision.round_id AND author.actor_id=NEW.actor_id)
           OR NOT EXISTS (SELECT 1 FROM public.announcements_announcementcommandreceipt request WHERE
               request.operation='request_review' AND request.object_id=NEW.revision_id
               AND request.control_sequence < receipt.control_sequence) THEN
            RAISE EXCEPTION 'Review requires the exact submitted copy and a different editor' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'announcements_announcementpublicationreport' THEN
        SELECT * INTO variant FROM public.announcements_announcementvariant WHERE id=NEW.variant_id;
        SELECT * INTO revision FROM public.announcements_announcementrevision WHERE id=variant.revision_id;
        SELECT * INTO prior_report FROM public.announcements_announcementpublicationreport WHERE id=NEW.supersedes_report_id;
        IF variant.id IS NULL OR variant.organization_id <> NEW.organization_id OR variant.edition_id <> NEW.edition_id
           OR receipt.object_id <> NEW.id OR receipt.announcement_id <> revision.announcement_id
           OR receipt.operation <> (CASE WHEN NEW.supersedes_report_id IS NULL THEN 'record_publication' WHEN NEW.withdrawn THEN 'withdraw_report' ELSE 'correct_publication' END)
           OR (NEW.supersedes_report_id IS NOT NULL AND (prior_report.id IS NULL OR prior_report.variant_id <> NEW.variant_id
               OR NOT EXISTS (SELECT 1 FROM public.announcements_announcementcommandreceipt proof
                   WHERE proof.id=prior_report.command_receipt_id AND proof.control_sequence<receipt.control_sequence)))
           OR (NEW.publication_url <> '' AND NEW.publication_url !~ '^https://[^/@]+([/:?#]|$)')
           OR NEW.published_at > NEW.occurred_at
           OR (NEW.withdrawn AND (NEW.publication_url <> '' OR NEW.published_at IS NOT NULL))
           OR NOT EXISTS (SELECT 1 FROM public.announcements_announcementreview review
               JOIN public.announcements_announcementcommandreceipt proof ON proof.id=review.command_receipt_id
               WHERE review.revision_id=revision.id AND review.decision='approve'
                 AND proof.control_sequence < receipt.control_sequence)
           OR (SELECT count(*) FROM public.announcements_announcementpublicationreport report
               JOIN public.announcements_announcementvariant copy ON copy.id=report.variant_id
               JOIN public.announcements_announcementrevision source ON source.id=copy.revision_id
               WHERE source.announcement_id=revision.announcement_id) > 2048 THEN
            RAISE EXCEPTION 'Publication report requires exact approved copy and retained lineage' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public, pg_temp;
"""

FORWARD_SQL += "\n".join(
    f"""
CREATE TRIGGER ann_{index}_row_guard BEFORE INSERT OR UPDATE OR DELETE ON public.announcements_{table}
FOR EACH ROW EXECUTE FUNCTION public.maru_announcements_row_guard();
CREATE CONSTRAINT TRIGGER ann_{index}_graph_guard AFTER INSERT OR UPDATE ON public.announcements_{table}
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.maru_announcements_graph_guard();
CREATE TRIGGER ann_{index}_no_truncate BEFORE TRUNCATE ON public.announcements_{table}
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_announcements_no_truncate();
""" for index, table in enumerate(TABLES)
)
FORWARD_SQL += "\n".join(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC;" for signature in FUNCTIONS)
REVERSE_SQL = "\n".join(
    f"DROP TRIGGER ann_{index}_{kind} ON public.announcements_{table};"
    for index, table in enumerate(TABLES) for kind in ("row_guard", "graph_guard", "no_truncate")
) + "\n" + "\n".join(f"DROP FUNCTION public.{signature};" for signature in reversed(FUNCTIONS))


class Migration(migrations.Migration):
    dependencies = [
        ("announcements", "0001_initial"),
        ("events", "0021_announcements_setup_downgrade_fence"),
        ("authorization", "0042_announcements_operator_lineage"),
        ("audit", "0009_native_mutation_witness"),
        ("effects", "0003_effect_replay_receipts"),
    ]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
