"""Pin invitation token digests to a bounded, independently rotated keyring."""

from __future__ import annotations

import django.core.validators
from django.db import migrations, models


def refuse_active_legacy_invitation_challenges(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Do not strand a bearer token whose digest has no recoverable key id."""

    del apps
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "LOCK TABLE identity_identitychallenge IN SHARE ROW EXCLUSIVE MODE"
        )
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM identity_identitychallenge
                 WHERE purpose = 'account_invitation'
                   AND consumed_at IS NULL
                   AND invalidated_at IS NULL
            )
            """
        )
        if bool(cursor.fetchone()[0]):
            raise RuntimeError(
                "Identity 0013 cannot pin digest-key lineage while an active "
                "legacy account invitation exists. Revoke or expire every "
                "outstanding invitation under the old release, then retry."
            )


def refuse_keyed_digest_downgrade(apps, schema_editor):  # type: ignore[no-untyped-def]
    """A keyed digest cannot be interpreted safely by the previous release."""

    del apps
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "LOCK TABLE identity_identitychallenge IN SHARE ROW EXCLUSIVE MODE"
        )
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM identity_identitychallenge
                 WHERE purpose = 'account_invitation'
                   AND token_digest_key_id <> ''
            )
            """
        )
        if bool(cursor.fetchone()[0]):
            raise RuntimeError(
                "Identity 0013 cannot be reversed after a keyed account "
                "invitation challenge exists. Restore compatible code and "
                "recover forward."
            )

INSTALL_DIGEST_KEY_GUARD = r"""
CREATE FUNCTION identity_page10_token_digest_key_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF NEW.purpose <> 'account_invitation' THEN
        IF NEW.token_digest_key_id <> '' THEN
            RAISE EXCEPTION 'non-invitation challenge has an invitation digest key'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE'
       AND NEW.token_digest_key_id IS DISTINCT FROM OLD.token_digest_key_id THEN
        RAISE EXCEPTION 'invitation challenge digest-key lineage is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.token_digest_key_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$' THEN
        RETURN NEW;
    END IF;

    -- Rows created before this migration remain honest legacy evidence. They
    -- may only be terminalized; they cannot become usable keyed challenges.
    IF TG_OP = 'INSERT'
       OR (NEW.consumed_at IS NULL AND NEW.invalidated_at IS NULL) THEN
        RAISE EXCEPTION 'active invitation challenge lacks a versioned digest key'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION identity_page10_token_digest_key_guard() FROM PUBLIC;

CREATE TRIGGER identity_page10_token_digest_key
BEFORE INSERT OR UPDATE ON identity_identitychallenge
FOR EACH ROW EXECUTE FUNCTION identity_page10_token_digest_key_guard();
"""


REMOVE_DIGEST_KEY_GUARD = r"""
DROP TRIGGER IF EXISTS identity_page10_token_digest_key
    ON identity_identitychallenge;
DROP FUNCTION IF EXISTS identity_page10_token_digest_key_guard();
"""


class Migration(migrations.Migration):
    dependencies = [  # noqa: RUF012
        ("identity", "0012_invitation_delivery_reconciliation"),
    ]

    operations = [  # noqa: RUF012
        migrations.RunPython(
            refuse_active_legacy_invitation_challenges,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddField(
            model_name="identitychallenge",
            name="token_digest_key_id",
            field=models.CharField(
                blank=True,
                editable=False,
                help_text=(
                    "Versioned HMAC key used for invitation-token lookup. Blank "
                    "values are retained only on terminal challenges created "
                    "before key rotation."
                ),
                max_length=64,
                validators=(
                    django.core.validators.RegexValidator(
                        code="invalid_invitation_encryption_key_id",
                        message="Use a stable invitation encryption key identifier.",
                        regex=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$",
                    ),
                ),
            ),
        ),
        migrations.RunSQL(
            sql=INSTALL_DIGEST_KEY_GUARD,
            reverse_sql=REMOVE_DIGEST_KEY_GUARD,
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_keyed_digest_downgrade,
        ),
    ]
