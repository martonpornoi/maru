from django.db import migrations

FORWARD_SQL = """
CREATE FUNCTION maru_prevent_registration_evidence_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'registration evidence is append-only'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER registration_financial_ledger_append_only
BEFORE UPDATE OR DELETE ON registration_financialledgerentry
FOR EACH ROW EXECUTE FUNCTION maru_prevent_registration_evidence_mutation();

CREATE TRIGGER registration_receipt_append_only
BEFORE UPDATE OR DELETE ON registration_receiptrecord
FOR EACH ROW EXECUTE FUNCTION maru_prevent_registration_evidence_mutation();

CREATE TRIGGER registration_settlement_allocation_append_only
BEFORE UPDATE OR DELETE ON registration_settlementallocation
FOR EACH ROW EXECUTE FUNCTION maru_prevent_registration_evidence_mutation();

CREATE TRIGGER registration_settlement_batch_append_only
BEFORE UPDATE OR DELETE ON registration_settlementbatch
FOR EACH ROW EXECUTE FUNCTION maru_prevent_registration_evidence_mutation();

CREATE TRIGGER registration_webhook_receipt_append_only
BEFORE UPDATE OR DELETE ON registration_paymentwebhookreceipt
FOR EACH ROW EXECUTE FUNCTION maru_prevent_registration_evidence_mutation();

CREATE TRIGGER registration_receipt_command_append_only
BEFORE UPDATE OR DELETE ON registration_registrationcommandreceipt
FOR EACH ROW EXECUTE FUNCTION maru_prevent_registration_evidence_mutation();

CREATE TRIGGER registration_media_safety_append_only
BEFORE UPDATE OR DELETE ON registration_mediasafetyreceipt
FOR EACH ROW EXECUTE FUNCTION maru_prevent_registration_evidence_mutation();

CREATE TRIGGER registration_lifecycle_run_append_only
BEFORE UPDATE OR DELETE ON registration_registrationlifecyclerun
FOR EACH ROW EXECUTE FUNCTION maru_prevent_registration_evidence_mutation();

CREATE FUNCTION maru_guard_financial_operation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'financial operations require a terminal state'
            USING ERRCODE = '23514';
    END IF;
    IF (
        to_jsonb(NEW)
            - ARRAY[
                'status', 'approved_by_id', 'approved_at', 'approval_reason',
                'completed_at', 'safe_result_code', 'updated_at'
            ]
        !=
        to_jsonb(OLD)
            - ARRAY[
                'status', 'approved_by_id', 'approved_at', 'approval_reason',
                'completed_at', 'safe_result_code', 'updated_at'
            ]
    ) THEN
        RAISE EXCEPTION 'financial operation envelope is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'proposed'
       AND NEW.status IN ('approved', 'provider_pending', 'completed')
       AND NEW.approved_by_id IS NOT NULL
       AND NEW.approved_by_id != NEW.requested_by_id
       AND NEW.approved_at IS NOT NULL
       AND NEW.approval_reason != ''
       AND (
           (NEW.status = 'completed' AND NEW.completed_at IS NOT NULL)
           OR (NEW.status != 'completed' AND NEW.completed_at IS NULL)
       )
    THEN
        RETURN NEW;
    END IF;
    IF OLD.status IN ('approved', 'provider_pending')
       AND NEW.status IN ('completed', 'failed')
       AND NEW.completed_at IS NOT NULL
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'invalid financial operation transition'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER registration_financial_operation_guard
BEFORE UPDATE OR DELETE ON registration_financialoperation
FOR EACH ROW EXECUTE FUNCTION maru_guard_financial_operation();

CREATE FUNCTION maru_guard_payment_exception()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'payment exceptions require reasoned resolution'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'open'
       AND NEW.status = 'resolved'
       AND NEW.resolved_at IS NOT NULL
       AND NEW.resolved_by_id IS NOT NULL
       AND NEW.resolution_reason != ''
       AND (
           to_jsonb(NEW)
               - ARRAY[
                   'status', 'resolved_at', 'resolved_by_id',
                   'resolution_reason', 'updated_at'
               ]
           =
           to_jsonb(OLD)
               - ARRAY[
                   'status', 'resolved_at', 'resolved_by_id',
                   'resolution_reason', 'updated_at'
               ]
       )
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'invalid payment exception transition'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER registration_payment_exception_guard
BEFORE UPDATE OR DELETE ON registration_paymentexception
FOR EACH ROW EXECUTE FUNCTION maru_guard_payment_exception();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS registration_payment_exception_guard
    ON registration_paymentexception;
DROP FUNCTION IF EXISTS maru_guard_payment_exception();
DROP TRIGGER IF EXISTS registration_financial_operation_guard
    ON registration_financialoperation;
DROP FUNCTION IF EXISTS maru_guard_financial_operation();
DROP TRIGGER IF EXISTS registration_lifecycle_run_append_only
    ON registration_registrationlifecyclerun;
DROP TRIGGER IF EXISTS registration_media_safety_append_only
    ON registration_mediasafetyreceipt;
DROP TRIGGER IF EXISTS registration_receipt_command_append_only
    ON registration_registrationcommandreceipt;
DROP TRIGGER IF EXISTS registration_webhook_receipt_append_only
    ON registration_paymentwebhookreceipt;
DROP TRIGGER IF EXISTS registration_settlement_batch_append_only
    ON registration_settlementbatch;
DROP TRIGGER IF EXISTS registration_settlement_allocation_append_only
    ON registration_settlementallocation;
DROP TRIGGER IF EXISTS registration_receipt_append_only
    ON registration_receiptrecord;
DROP TRIGGER IF EXISTS registration_financial_ledger_append_only
    ON registration_financialledgerentry;
DROP FUNCTION IF EXISTS maru_prevent_registration_evidence_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("registration", "0022_registrationlifecyclerun_restrictions_applied"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
