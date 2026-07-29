from django.db import migrations


FORWARD_SQL = r"""
CREATE FUNCTION maru_guard_workforce_department()
RETURNS trigger AS $$
DECLARE
    edition_organization uuid;
    parent_organization uuid;
    parent_edition uuid;
BEGIN
    SELECT organization_id INTO edition_organization
      FROM events_eventedition WHERE id = NEW.edition_id;
    IF edition_organization IS NULL OR edition_organization <> NEW.organization_id THEN
        RAISE EXCEPTION 'workforce department edition scope mismatch';
    END IF;
    IF NEW.parent_id IS NOT NULL THEN
        SELECT organization_id, edition_id
          INTO parent_organization, parent_edition
          FROM workforce_department WHERE id = NEW.parent_id;
        IF parent_organization <> NEW.organization_id
           OR parent_edition <> NEW.edition_id
           OR NEW.parent_id = NEW.id THEN
            RAISE EXCEPTION 'workforce department parent scope mismatch';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER workforce_department_scope_guard
BEFORE INSERT OR UPDATE ON workforce_department
FOR EACH ROW EXECUTE FUNCTION maru_guard_workforce_department();

CREATE FUNCTION maru_guard_workforce_document_type()
RETURNS trigger AS $$
DECLARE
    edition_organization uuid;
BEGIN
    SELECT organization_id INTO edition_organization
      FROM events_eventedition WHERE id = NEW.edition_id;
    IF edition_organization IS NULL OR edition_organization <> NEW.organization_id THEN
        RAISE EXCEPTION 'workforce document type edition scope mismatch';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status IN ('active', 'retired') THEN
        IF NOT (
            OLD.status = 'active'
            AND NEW.status = 'retired'
            AND NEW.organization_id = OLD.organization_id
            AND NEW.edition_id = OLD.edition_id
            AND NEW.code = OLD.code
            AND NEW.name = OLD.name
            AND NEW.version = OLD.version
            AND NEW.description = OLD.description
            AND NEW.max_bytes = OLD.max_bytes
            AND NEW.retention_notice = OLD.retention_notice
            AND NEW.created_by_id = OLD.created_by_id
        ) THEN
            RAISE EXCEPTION 'active workforce document versions are immutable';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER workforce_document_type_guard
BEFORE INSERT OR UPDATE ON workforce_onboardingdocumenttype
FOR EACH ROW EXECUTE FUNCTION maru_guard_workforce_document_type();

CREATE FUNCTION maru_guard_workforce_position_template()
RETURNS trigger AS $$
DECLARE
    role_organization uuid;
BEGIN
    SELECT organization_id INTO role_organization
      FROM authorization_rolebundle WHERE id = NEW.role_bundle_id;
    IF role_organization IS NULL OR role_organization <> NEW.organization_id THEN
        RAISE EXCEPTION 'workforce position template role scope mismatch';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status IN ('published', 'retired') THEN
        IF NOT (
            OLD.status = 'published'
            AND NEW.status = 'retired'
            AND NEW.organization_id = OLD.organization_id
            AND NEW.code = OLD.code
            AND NEW.name = OLD.name
            AND NEW.version = OLD.version
            AND NEW.description = OLD.description
            AND NEW.default_headcount = OLD.default_headcount
            AND NEW.default_capacity_codes = OLD.default_capacity_codes
            AND NEW.role_bundle_id = OLD.role_bundle_id
            AND NEW.created_by_id = OLD.created_by_id
        ) THEN
            RAISE EXCEPTION 'published workforce position templates are immutable';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER workforce_position_template_guard
BEFORE INSERT OR UPDATE ON workforce_positiontemplate
FOR EACH ROW EXECUTE FUNCTION maru_guard_workforce_position_template();

CREATE FUNCTION maru_guard_workforce_position()
RETURNS trigger AS $$
DECLARE
    scoped_organization uuid;
    scoped_edition uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'workforce positions cannot be deleted';
    END IF;
    SELECT organization_id INTO scoped_organization
      FROM events_eventedition WHERE id = NEW.edition_id;
    IF scoped_organization IS NULL OR scoped_organization <> NEW.organization_id THEN
        RAISE EXCEPTION 'workforce position edition scope mismatch';
    END IF;
    SELECT organization_id, edition_id INTO scoped_organization, scoped_edition
      FROM workforce_department WHERE id = NEW.department_id;
    IF scoped_organization <> NEW.organization_id
       OR scoped_edition <> NEW.edition_id THEN
        RAISE EXCEPTION 'workforce position department scope mismatch';
    END IF;
    SELECT organization_id INTO scoped_organization
      FROM workforce_positiontemplate WHERE id = NEW.template_id;
    IF scoped_organization <> NEW.organization_id THEN
        RAISE EXCEPTION 'workforce position template scope mismatch';
    END IF;
    SELECT organization_id INTO scoped_organization
      FROM authorization_rolebundle WHERE id = NEW.role_bundle_id;
    IF scoped_organization <> NEW.organization_id THEN
        RAISE EXCEPTION 'workforce position role scope mismatch';
    END IF;
    IF NEW.reports_to_id IS NOT NULL THEN
        SELECT organization_id, edition_id
          INTO scoped_organization, scoped_edition
          FROM workforce_position WHERE id = NEW.reports_to_id;
        IF scoped_organization <> NEW.organization_id
           OR scoped_edition <> NEW.edition_id
           OR NEW.reports_to_id = NEW.id THEN
            RAISE EXCEPTION 'workforce reporting line scope mismatch';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER workforce_position_guard
BEFORE INSERT OR UPDATE OR DELETE ON workforce_position
FOR EACH ROW EXECUTE FUNCTION maru_guard_workforce_position();

CREATE FUNCTION maru_guard_workforce_position_document()
RETURNS trigger AS $$
DECLARE
    position_organization uuid;
    position_edition uuid;
    document_organization uuid;
    document_edition uuid;
BEGIN
    SELECT organization_id, edition_id
      INTO position_organization, position_edition
      FROM workforce_position WHERE id = NEW.position_id;
    SELECT organization_id, edition_id
      INTO document_organization, document_edition
      FROM workforce_onboardingdocumenttype WHERE id = NEW.document_type_id;
    IF position_organization <> document_organization
       OR position_edition <> document_edition THEN
        RAISE EXCEPTION 'workforce position document scope mismatch';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER workforce_position_document_guard
BEFORE INSERT OR UPDATE ON workforce_positiondocumentrequirement
FOR EACH ROW EXECUTE FUNCTION maru_guard_workforce_position_document();

CREATE FUNCTION maru_guard_workforce_document_request()
RETURNS trigger AS $$
DECLARE
    scoped_organization uuid;
    scoped_edition uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'workforce onboarding document evidence cannot be deleted';
    END IF;
    SELECT organization_id INTO scoped_organization
      FROM events_eventedition WHERE id = NEW.edition_id;
    IF scoped_organization IS NULL OR scoped_organization <> NEW.organization_id THEN
        RAISE EXCEPTION 'workforce document request edition scope mismatch';
    END IF;
    SELECT organization_id, edition_id
      INTO scoped_organization, scoped_edition
      FROM workforce_onboardingdocumenttype WHERE id = NEW.document_type_id;
    IF scoped_organization <> NEW.organization_id
       OR scoped_edition <> NEW.edition_id THEN
        RAISE EXCEPTION 'workforce document request type scope mismatch';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.status = 'approved' THEN
            RAISE EXCEPTION 'approved workforce document evidence is immutable';
        END IF;
        IF OLD.status = 'submitted' AND NEW.status = 'submitted'
           AND (
               NEW.document <> OLD.document
               OR NEW.original_filename <> OLD.original_filename
               OR NEW.content_type <> OLD.content_type
               OR NEW.byte_count IS DISTINCT FROM OLD.byte_count
               OR NEW.sha256 <> OLD.sha256
               OR NEW.scanner_code <> OLD.scanner_code
               OR NEW.submitted_at IS DISTINCT FROM OLD.submitted_at
           ) THEN
            RAISE EXCEPTION 'submitted workforce document evidence is immutable';
        END IF;
        IF OLD.status <> NEW.status AND NOT (
            (OLD.status = 'requested' AND NEW.status = 'submitted')
            OR (OLD.status = 'rejected' AND NEW.status = 'submitted')
            OR (
                OLD.status = 'submitted'
                AND NEW.status IN ('approved', 'rejected')
            )
        ) THEN
            RAISE EXCEPTION 'invalid workforce document status transition';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER workforce_document_request_guard
BEFORE INSERT OR UPDATE OR DELETE ON workforce_onboardingdocumentrequest
FOR EACH ROW EXECUTE FUNCTION maru_guard_workforce_document_request();

CREATE FUNCTION maru_guard_workforce_assignment()
RETURNS trigger AS $$
DECLARE
    scoped_organization uuid;
    scoped_edition uuid;
    scoped_account uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'workforce assignments cannot be deleted';
    END IF;
    SELECT organization_id, edition_id
      INTO scoped_organization, scoped_edition
      FROM workforce_position WHERE id = NEW.position_id;
    IF scoped_organization <> NEW.organization_id
       OR scoped_edition <> NEW.edition_id THEN
        RAISE EXCEPTION 'workforce assignment position scope mismatch';
    END IF;
    IF NEW.approved_by_id IS NOT NULL
       AND NEW.approved_by_id = NEW.proposed_by_id THEN
        RAISE EXCEPTION 'workforce assignment requires independent approval';
    END IF;
    IF NEW.role_assignment_id IS NOT NULL THEN
        SELECT organization_id, edition_id, principal_id
          INTO scoped_organization, scoped_edition, scoped_account
          FROM authorization_roleassignment WHERE id = NEW.role_assignment_id;
        IF scoped_organization <> NEW.organization_id
           OR scoped_edition IS DISTINCT FROM NEW.edition_id
           OR scoped_account <> NEW.account_id THEN
            RAISE EXCEPTION 'workforce assignment role evidence scope mismatch';
        END IF;
    END IF;
    IF NEW.participation_capacity_id IS NOT NULL THEN
        SELECT p.organization_id, p.edition_id, p.account_id
          INTO scoped_organization, scoped_edition, scoped_account
          FROM participation_participationcapacity c
          JOIN participation_participation p ON p.id = c.participation_id
         WHERE c.id = NEW.participation_capacity_id;
        IF scoped_organization <> NEW.organization_id
           OR scoped_edition <> NEW.edition_id
           OR scoped_account <> NEW.account_id THEN
            RAISE EXCEPTION 'workforce assignment capacity evidence scope mismatch';
        END IF;
    END IF;
    IF NEW.status = 'active' AND (
        NEW.approved_by_id IS NULL
        OR NEW.role_assignment_id IS NULL
        OR NEW.participation_capacity_id IS NULL
    ) THEN
        RAISE EXCEPTION 'active workforce assignment lacks approval evidence';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.status = 'active' AND NEW.status = 'active'
           AND NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'active workforce assignments are immutable';
        END IF;
        IF OLD.status <> NEW.status AND NOT (
            (OLD.status = 'proposed' AND NEW.status = 'active')
            OR (OLD.status = 'active' AND NEW.status = 'ended')
        ) THEN
            RAISE EXCEPTION 'invalid workforce assignment status transition';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER workforce_assignment_guard
BEFORE INSERT OR UPDATE OR DELETE ON workforce_positionassignment
FOR EACH ROW EXECUTE FUNCTION maru_guard_workforce_assignment();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS workforce_assignment_guard
ON workforce_positionassignment;
DROP FUNCTION IF EXISTS maru_guard_workforce_assignment();
DROP TRIGGER IF EXISTS workforce_document_request_guard
ON workforce_onboardingdocumentrequest;
DROP FUNCTION IF EXISTS maru_guard_workforce_document_request();
DROP TRIGGER IF EXISTS workforce_position_document_guard
ON workforce_positiondocumentrequirement;
DROP FUNCTION IF EXISTS maru_guard_workforce_position_document();
DROP TRIGGER IF EXISTS workforce_position_guard ON workforce_position;
DROP FUNCTION IF EXISTS maru_guard_workforce_position();
DROP TRIGGER IF EXISTS workforce_position_template_guard
ON workforce_positiontemplate;
DROP FUNCTION IF EXISTS maru_guard_workforce_position_template();
DROP TRIGGER IF EXISTS workforce_document_type_guard
ON workforce_onboardingdocumenttype;
DROP FUNCTION IF EXISTS maru_guard_workforce_document_type();
DROP TRIGGER IF EXISTS workforce_department_scope_guard
ON workforce_department;
DROP FUNCTION IF EXISTS maru_guard_workforce_department();
"""


class Migration(migrations.Migration):
    dependencies = [("workforce", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
