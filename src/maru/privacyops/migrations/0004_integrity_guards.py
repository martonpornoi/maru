from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION maru_prevent_privacy_receipt_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'privacy disposal evidence is append-only'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER privacy_disposal_receipt_append_only
BEFORE UPDATE OR DELETE ON privacyops_disposalreceipt
FOR EACH ROW EXECUTE FUNCTION maru_prevent_privacy_receipt_mutation();

CREATE FUNCTION maru_guard_post_edition_correction()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'post-edition corrections require retention'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'proposed'
       AND NEW.status IN ('approved', 'rejected')
       AND NEW.decided_by_id IS NOT NULL
       AND NEW.decided_at IS NOT NULL
       AND NEW.decision_reason != ''
       AND (
           to_jsonb(NEW)
               - ARRAY[
                   'status', 'decided_by_id', 'decided_at',
                   'decision_reason', 'updated_at'
               ]
           =
           to_jsonb(OLD)
               - ARRAY[
                   'status', 'decided_by_id', 'decided_at',
                   'decision_reason', 'updated_at'
               ]
       )
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'invalid post-edition correction transition'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER privacy_post_edition_correction_guard
BEFORE UPDATE OR DELETE ON privacyops_posteditioncorrection
FOR EACH ROW EXECUTE FUNCTION maru_guard_post_edition_correction();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS privacy_post_edition_correction_guard
    ON privacyops_posteditioncorrection;
DROP FUNCTION IF EXISTS maru_guard_post_edition_correction();
DROP TRIGGER IF EXISTS privacy_disposal_receipt_append_only
    ON privacyops_disposalreceipt;
DROP FUNCTION IF EXISTS maru_prevent_privacy_receipt_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("privacyops", "0003_alter_disposalreceipt_downstream_receipts"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
