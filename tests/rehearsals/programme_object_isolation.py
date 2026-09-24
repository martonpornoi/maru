"""Actual cross-scope POST refusals with existing objects and successful owners."""

import re
from html.parser import HTMLParser
from uuid import UUID, uuid4

import psycopg
from psycopg import sql

from tests.rehearsals.programme_http_session import ProgrammeHttpSession
from tests.rehearsals.programme_https import ProgrammeHttpsError
from tests.rehearsals.programme_journey_isolation import _check
from tests.rehearsals.programme_object_preparation import prepare_isolated_objects
from tests.rehearsals.programme_onsite_scenario import _read, _require
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

_TABLES = (
    "programme_programmeeditioncontrol",
    "programme_programmeitem",
    "programme_programmeworkingrevision",
    "programme_programmecommandreceipt",
    "programme_programmereadinessrequirement",
    "programme_programmereadinessrequirementrevision",
)


class _WorkingForm(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.active = False
        self.forms = 0
        self.values = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "form":
            self.active = (
                values.get("method", "").lower() == "post"
                and values.get("action") == self.path
                and "data-programme-command" in values
            )
            self.forms += self.active
        if (
            self.active
            and tag == "input"
            and values.get("name")
            in {"csrfmiddlewaretoken", "expected_version", "idempotency_key"}
        ):
            self.values.setdefault(values["name"], []).append(values.get("value", ""))

    def handle_endtag(self, tag):
        if tag == "form":
            self.active = False


def _form(text, path):
    parser = _WorkingForm(path)
    parser.feed(text)
    _require(
        parser.forms == 1
        and set(parser.values)
        == {"csrfmiddlewaretoken", "expected_version", "idempotency_key"}
        and all(len(values) == 1 for values in parser.values.values()),
        "fixture_object_form_invalid",
    )
    result = {key: values[0] for key, values in parser.values.items()}
    _require(
        re.fullmatch(r"[A-Za-z0-9]{64}", result["csrfmiddlewaretoken"]) is not None
        and re.fullmatch(r"[1-9][0-9]*", result["expected_version"]) is not None,
        "fixture_object_form_invalid",
    )
    try:
        identifier = UUID(result["idempotency_key"])
    except ValueError:
        raise ProgrammeHttpsError("fixture_object_form_invalid") from None
    _require(
        identifier.int and str(identifier) == result["idempotency_key"],
        "fixture_object_form_invalid",
    )
    return result


def _snapshot(fixture, organizations):
    """Retain complete affected owner rows and Programme events, never log them."""
    with psycopg.connect(fixture.runtime.database_url, connect_timeout=5) as connection:
        result = tuple(
            connection.execute(
                sql.SQL(
                    "SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY t.id), "
                    "'[]'::jsonb) "
                    "FROM public.{} t WHERE organization_id = ANY(%s)"
                ).format(sql.Identifier(table)),
                (list(organizations),),
            ).fetchone()[0]
            for table in _TABLES
        )
        events = connection.execute(
            "SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY t.id), '[]'::jsonb) "
            "FROM public.effects_domainevent t WHERE organization_id = ANY(%s) "
            "AND event_name LIKE 'programme.%%'",
            (list(organizations),),
        ).fetchone()[0]
    return (*result, events)


def _values(*, csrf, title):
    return {
        "csrfmiddlewaretoken": csrf,
        "expected_version": "1",
        "idempotency_key": str(uuid4()),
        "internal_title": title,
        "working_summary": "Synthetic object mutation control only.",
        "reason": "Synthetic P12 object-level mutation verification.",
    }


def _path(organization, edition, item):
    return f"/admin/programme/items/{organization}/{edition}/{item}/working/"


def _owner_control(session, record, *, forbidden):
    path = _path(record.organization_id, record.edition_id, record.item_id)
    session.login(record.owner, destination=path)
    try:
        page = _read(session, path, forbidden=forbidden)
        original = _form(page, path)
        values = (
            _values(
                csrf=original["csrfmiddlewaretoken"],
                title="Private successful scope-owner edit",
            )
            | original
        )
        response = session.submit_working_item(
            organization_id=record.organization_id,
            edition_id=record.edition_id,
            item_id=record.item_id,
            form=values,
        )
        _require(
            response.status == 302 and response.headers.get("Location") == path,
            "fixture_object_positive_mutation_failed",
        )
        after = _read(session, path, forbidden=forbidden)
        _require(
            values["internal_title"] in after,
            "fixture_object_positive_mutation_missing",
        )
        current = _form(after, path)
        _require(
            int(current["expected_version"]) == int(original["expected_version"]) + 1,
            "fixture_object_positive_version_changed",
        )
        return int(current["expected_version"])
    finally:
        session.logout()


def verify_object_mutation_isolation(fixture, scopes, review, items):
    """Prove actual owner success plus foreign tenant, edition and object refusal."""
    require_programme_rehearsal_request()
    setup = fixture.scenario
    _require(
        (review.organization_id, review.edition_id)
        == (setup.organization_id, setup.edition_id)
        and (items.organization_id, items.edition_id)
        == (setup.organization_id, setup.edition_id),
        "fixture_object_source_scope",
    )
    objects = prepare_isolated_objects(fixture, scopes)
    session = ProgrammeHttpSession(fixture)
    private = (
        "Private foreign-scope mutation control",
        "Private successful scope-owner edit",
        *(row.owner.email for row in objects),
        *(row.owner.password for row in objects),
    )
    original_path = _path(
        setup.organization_id, setup.edition_id, items.accepted.item_id
    )
    # Each denied target is a real editable object, proved through a different
    # authenticated owner. No missing-ID or CSRF refusal substitutes for policy.
    versions = {
        record.item_id: _owner_control(
            session, record, forbidden=tuple(row.owner.password for row in objects)
        )
        for record in objects
    }
    session.login(review.people[5], destination=original_path)
    try:
        own = _form(_read(session, original_path, forbidden=private), original_path)
        organizations = (setup.organization_id, scopes.organization_id)
        baseline = _snapshot(fixture, organizations)
        for record in objects:
            for organization, edition, expected in (
                (record.organization_id, record.edition_id, 404),
                # The genuine current editor has this scope, but the object is
                # not in it. The existing owner API uses non-disclosing 503 for
                # unavailable item/source, identical to an absent object.
                (setup.organization_id, setup.edition_id, 503),
            ):
                response = session.submit_working_item(
                    organization_id=organization,
                    edition_id=edition,
                    item_id=record.item_id,
                    form=_values(
                        csrf=own["csrfmiddlewaretoken"],
                        title="Forbidden cross-scope overwrite",
                    )
                    | {"expected_version": str(versions[record.item_id])},
                )
                _check(
                    response,
                    expected=expected,
                    code="object_mutation",
                    forbidden=private,
                )
                _require(
                    _snapshot(fixture, organizations) == baseline,
                    "fixture_object_denial_wrote_owner_state",
                )
                fixture.verify_excluded_state()
    finally:
        session.logout()
    # Re-prove both owners can still read and mutate after all denied attempts.
    for record in objects:
        _owner_control(
            session, record, forbidden=tuple(row.owner.password for row in objects)
        )
    fixture.verify_excluded_state()
