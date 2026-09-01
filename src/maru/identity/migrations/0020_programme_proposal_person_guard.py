"""Guard Applications-owned Programme subject references as person accounts."""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_identity_validate_programme_proposal_lead()
RETURNS trigger AS $$
DECLARE
    subject_kind varchar;
BEGIN
    SELECT account.account_kind INTO subject_kind
      FROM public.applications_applicationsubmission AS submission
     JOIN public.identity_account AS account
        ON account.id = submission.account_id
     WHERE submission.id = NEW.submission_id
     FOR UPDATE OF account;

    IF subject_kind IS DISTINCT FROM 'person' THEN
        RAISE EXCEPTION
            'Programme proposal lead must be a person account'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION
    public.maru_identity_validate_programme_proposal_lead()
FROM PUBLIC;

CREATE CONSTRAINT TRIGGER identity_programme_proposal_lead_person_guard
AFTER INSERT OR UPDATE
ON public.applications_programmeproposal
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION public.maru_identity_validate_programme_proposal_lead();

CREATE FUNCTION public.maru_identity_validate_programme_collaborator_person()
RETURNS trigger AS $$
DECLARE
    subject_kind varchar;
BEGIN
    SELECT account.account_kind INTO subject_kind
      FROM public.identity_account AS account
     WHERE account.id = NEW.account_id
     FOR UPDATE OF account;

    IF subject_kind IS DISTINCT FROM 'person' THEN
        RAISE EXCEPTION
            'Programme proposal collaborator must be a person account'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION
    public.maru_identity_validate_programme_collaborator_person()
FROM PUBLIC;

CREATE CONSTRAINT TRIGGER identity_programme_collaborator_person_guard
AFTER INSERT OR UPDATE
ON public.applications_programmeproposalcollaborator
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION public.maru_identity_validate_programme_collaborator_person();

CREATE FUNCTION public.maru_identity_validate_programme_profile_persons()
RETURNS trigger AS $$
DECLARE
    subject_kind varchar;
    actor_kind varchar;
BEGIN
    PERFORM 1
      FROM public.identity_account AS account
     WHERE account.id IN (NEW.account_id, NEW.actor_id)
     ORDER BY account.id
     FOR UPDATE OF account;
    SELECT account_kind INTO subject_kind
      FROM public.identity_account
     WHERE id = NEW.account_id;
    SELECT account_kind INTO actor_kind
      FROM public.identity_account
     WHERE id = NEW.actor_id;

    IF subject_kind IS DISTINCT FROM 'person'
       OR actor_kind IS DISTINCT FROM 'person'
    THEN
        RAISE EXCEPTION
            'Programme proposal profile references must be person accounts'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION
    public.maru_identity_validate_programme_profile_persons()
FROM PUBLIC;

CREATE CONSTRAINT TRIGGER identity_programme_profile_person_guard
AFTER INSERT OR UPDATE
ON public.applications_programmeproposalcontributorprofilerevision
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION public.maru_identity_validate_programme_profile_persons();

CREATE FUNCTION public.maru_identity_validate_programme_response_persons()
RETURNS trigger AS $$
DECLARE
    subject_kind varchar;
    actor_kind varchar;
BEGIN
    PERFORM 1
      FROM public.identity_account AS account
     WHERE account.id IN (NEW.account_id, NEW.actor_id)
     ORDER BY account.id
     FOR UPDATE OF account;
    SELECT account_kind INTO subject_kind
      FROM public.identity_account
     WHERE id = NEW.account_id;
    SELECT account_kind INTO actor_kind
      FROM public.identity_account
     WHERE id = NEW.actor_id;

    IF subject_kind IS DISTINCT FROM 'person'
       OR actor_kind IS DISTINCT FROM 'person'
    THEN
        RAISE EXCEPTION
            'Programme proposal response references must be person accounts'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION
    public.maru_identity_validate_programme_response_persons()
FROM PUBLIC;

CREATE CONSTRAINT TRIGGER identity_programme_response_person_guard
AFTER INSERT OR UPDATE
ON public.applications_programmeproposalrevisionresponse
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION public.maru_identity_validate_programme_response_persons();

CREATE FUNCTION public.maru_identity_validate_programme_account_kind()
RETURNS trigger AS $$
BEGIN
    IF NEW.account_kind IS DISTINCT FROM 'person'
       AND (
           EXISTS (
               SELECT 1
                 FROM public.applications_programmeproposal AS proposal
                 JOIN public.applications_applicationsubmission AS submission
                   ON submission.id = proposal.submission_id
                WHERE submission.account_id = NEW.id
           )
           OR EXISTS (
               SELECT 1
                 FROM public.applications_programmeproposalcollaborator
                WHERE account_id = NEW.id
           )
           OR EXISTS (
               SELECT 1
                 FROM public.applications_programmeproposalcontributorprofilerevision
                WHERE account_id = NEW.id OR actor_id = NEW.id
           )
           OR EXISTS (
               SELECT 1
                 FROM public.applications_programmeproposalrevisionresponse
                WHERE account_id = NEW.id OR actor_id = NEW.id
           )
       )
    THEN
        RAISE EXCEPTION
            'Programme proposal references cannot retain a non-person account'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION
    public.maru_identity_validate_programme_account_kind()
FROM PUBLIC;

CREATE CONSTRAINT TRIGGER identity_programme_account_kind_guard
AFTER UPDATE OF account_kind
ON public.identity_account
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION public.maru_identity_validate_programme_account_kind();

DO $$
DECLARE
    invalid_reference_count bigint;
BEGIN
    SELECT COUNT(*) INTO invalid_reference_count
      FROM (
          SELECT submission.account_id
            FROM public.applications_programmeproposal AS proposal
            JOIN public.applications_applicationsubmission AS submission
              ON submission.id = proposal.submission_id
          UNION ALL
          SELECT account_id
            FROM public.applications_programmeproposalcollaborator
          UNION ALL
          SELECT account_id
            FROM public.applications_programmeproposalcontributorprofilerevision
          UNION ALL
          SELECT actor_id
            FROM public.applications_programmeproposalcontributorprofilerevision
          UNION ALL
          SELECT account_id
            FROM public.applications_programmeproposalrevisionresponse
          UNION ALL
          SELECT actor_id
            FROM public.applications_programmeproposalrevisionresponse
      ) AS reference
      LEFT JOIN public.identity_account AS account
        ON account.id = reference.account_id
     WHERE account.account_kind IS DISTINCT FROM 'person';

    IF invalid_reference_count > 0 THEN
        RAISE EXCEPTION
            'cannot install Programme person guards: invalid references %',
            invalid_reference_count
            USING ERRCODE = '23514';
    END IF;
END;
$$;
"""


REVERSE_SQL = r"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.applications_programmeproposal)
       OR EXISTS (
           SELECT 1 FROM public.applications_programmeproposalcollaborator
       )
       OR EXISTS (
           SELECT 1
             FROM public.applications_programmeproposalcontributorprofilerevision
       )
       OR EXISTS (
           SELECT 1
             FROM public.applications_programmeproposalrevisionresponse
       )
    THEN
        RAISE EXCEPTION
            'cannot remove Programme person guards while protected rows exist'
            USING ERRCODE = '23514';
    END IF;
END;
$$;

DROP TRIGGER IF EXISTS identity_programme_account_kind_guard
    ON public.identity_account;
DROP FUNCTION IF EXISTS public.maru_identity_validate_programme_account_kind();
DROP TRIGGER IF EXISTS identity_programme_response_person_guard
    ON public.applications_programmeproposalrevisionresponse;
DROP FUNCTION IF EXISTS public.maru_identity_validate_programme_response_persons();
DROP TRIGGER IF EXISTS identity_programme_profile_person_guard
    ON public.applications_programmeproposalcontributorprofilerevision;
DROP FUNCTION IF EXISTS public.maru_identity_validate_programme_profile_persons();
DROP TRIGGER IF EXISTS identity_programme_collaborator_person_guard
    ON public.applications_programmeproposalcollaborator;
DROP FUNCTION IF EXISTS public.maru_identity_validate_programme_collaborator_person();
DROP TRIGGER IF EXISTS identity_programme_proposal_lead_person_guard
    ON public.applications_programmeproposal;
DROP FUNCTION IF EXISTS public.maru_identity_validate_programme_proposal_lead();
"""


class Migration(migrations.Migration):
    """Install deferred person-kind guards for Programme proposal subjects."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("identity", "0019_navigation_pins"),
        ("applications", "0004_programme_calls_and_proposals"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
