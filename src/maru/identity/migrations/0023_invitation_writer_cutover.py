"""Retire legacy invitation challenge writers without adopting Registration."""

from typing import ClassVar

from django.db import migrations
from django.db.migrations.operations.base import Operation

FORWARD_SQL = r"""
LOCK TABLE public.identity_identitychallenge IN SHARE ROW EXCLUSIVE MODE;

CREATE FUNCTION public.maru_identity_invitation_writer_guard()
RETURNS trigger
AS $invitation_writer$
BEGIN
    IF TG_OP = 'UPDATE' AND (
        OLD.purpose = 'account_invitation' OR NEW.purpose = 'account_invitation'
    ) AND NEW.purpose IS DISTINCT FROM OLD.purpose THEN
        RAISE EXCEPTION 'invitation challenge purpose is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.purpose <> 'account_invitation' THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'INSERT' AND (
        NEW.delivery_status IS DISTINCT FROM 'suppressed'
        OR NEW.delivery_attempt_count IS DISTINCT FROM 0
        OR NEW.last_delivery_attempt_at IS NOT NULL
        OR NEW.delivered_at IS NOT NULL
        OR NEW.delivery_error_code IS DISTINCT FROM ''
    ) THEN
        RAISE EXCEPTION 'invitation requires canonical durable delivery'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.delivery_status IS DISTINCT FROM OLD.delivery_status
        OR NEW.delivery_attempt_count IS DISTINCT FROM OLD.delivery_attempt_count
        OR NEW.last_delivery_attempt_at IS DISTINCT FROM OLD.last_delivery_attempt_at
        OR NEW.delivered_at IS DISTINCT FROM OLD.delivered_at
        OR NEW.delivery_error_code IS DISTINCT FROM OLD.delivery_error_code
    ) THEN
        RAISE EXCEPTION 'legacy invitation delivery writers are retired'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$invitation_writer$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

REVOKE ALL ON FUNCTION public.maru_identity_invitation_writer_guard() FROM PUBLIC;

CREATE TRIGGER maru_identity_invitation_writer
BEFORE INSERT OR UPDATE ON public.identity_identitychallenge
FOR EACH ROW EXECUTE FUNCTION public.maru_identity_invitation_writer_guard();
"""

REVERSE_SQL = r"""
LOCK TABLE public.identity_identitychallenge,
    public.identity_platformaccountinvitation,
    public.identity_platformaccountinvitationtransition
IN ACCESS EXCLUSIVE MODE;
DO $unused_invitation_writer$
BEGIN
    IF EXISTS (SELECT 1 FROM public.identity_platformaccountinvitation)
       OR EXISTS (SELECT 1 FROM public.identity_identitychallenge
                  WHERE purpose = 'account_invitation')
       OR EXISTS (SELECT 1 FROM public.identity_platformaccountinvitationtransition)
    THEN
        RAISE EXCEPTION
            'used invitation writer generation requires fix-forward recovery'
            USING ERRCODE = '23514';
    END IF;
END;
$unused_invitation_writer$;
DROP TRIGGER maru_identity_invitation_writer ON public.identity_identitychallenge;
DROP FUNCTION public.maru_identity_invitation_writer_guard();
"""


class Migration(migrations.Migration):
    """Install a closed writer generation and retain the post-use downgrade fence."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("identity", "0022_person_obligation_source_identity"),
    ]
    operations: ClassVar[list[Operation]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
