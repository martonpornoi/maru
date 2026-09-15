"""Real encoders and transports retain complete final disclosure proof."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest

from maru.events.personal_timetable_queries import PersonalTimetableEditionLabel
from maru.events.queries import EditionAdoptionProfileReference
from maru.scheduling import continuity_queries as queries
from maru.scheduling import operator_output_views, output_views, personal_output_views
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.continuity_protocol import ContinuityScope
from maru.scheduling.output_navigation import ProgrammeOutputLink
from maru.scheduling.output_observation import (
    align_timetable_observation,
    verify_timetable_observation,
)
from tests.unit.test_personal_timetable_rendering import (
    personal as personal,  # noqa: PLC0414
)
from tests.unit.test_personal_timetable_views import request_view as personal_view
from tests.unit.test_programme_operator_rendering import (
    full_sheet as full_sheet,  # noqa: PLC0414
)
from tests.unit.test_programme_operator_rendering import sheet as sheet  # noqa: PLC0414
from tests.unit.test_programme_operator_views import request_view as operator_view
from tests.unit.test_scheduling_output_rendering import (
    snapshot as snapshot,  # noqa: PLC0414
)
from tests.unit.test_scheduling_output_views import request_view as public_view


@pytest.fixture(params=["public", "exact_person", "private_operator"])
def source(request, snapshot, personal, full_sheet):
    if request.param == "public":
        return (
            snapshot,
            ContinuityScope(UUID(int=21), UUID(int=22), "public"),
            "load_public_programme_timetable",
        )
    if request.param == "exact_person":
        return (
            personal,
            ContinuityScope(
                personal.organization_id,
                personal.edition_id,
                "exact_person",
                personal.actor_id,
                "personal",
            ),
            "load_personal_timetable",
        )
    return (
        full_sheet,
        ContinuityScope(
            full_sheet.organization_id,
            full_sheet.edition_id,
            "private_operator",
            UUID(int=19),
            full_sheet.kind.value,
            full_sheet.target_id,
            tuple(sorted(full_sheet.layers)),
        ),
        "load_operator_run_sheet",
    )


@pytest.fixture
def boundary(source, monkeypatch):
    current, scope, name = source
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    monkeypatch.setattr(
        queries,
        "_admitted",
        Mock(return_value=EditionAdoptionProfileReference("synthetic", 1)),
    )
    owners = {}
    for owner in (
        "load_public_programme_timetable",
        "load_personal_timetable",
        "load_operator_run_sheet",
    ):
        owners[owner] = (
            Mock(return_value=current)
            if owner == name
            else Mock(side_effect=AssertionError("Audience fallback forbidden"))
        )
        monkeypatch.setattr(queries, owner, owners[owner])
    initial = queries.load_continuity_projection(scope, correlation_id=uuid4())
    owners[name].reset_mock()
    return scope, initial, owners[name]


def test_final_continuity_check_keeps_original_clock_and_complete_digest(
    source, boundary
):
    current, _scope, _name = source
    scope, initial, owner = boundary
    owner.return_value = replace(
        current, checked_at=current.checked_at + timedelta(seconds=1)
    )
    result = queries.load_continuity_projection(
        scope, correlation_id=uuid4(), expected=initial
    )
    assert result == initial
    assert result.source_sha256 == initial.source_sha256
    owner.assert_called_once()


@pytest.mark.parametrize("change", ["scope", "digest"])
def test_expected_projection_is_not_authority_and_digest_is_never_ignored(
    boundary, change
):
    scope, initial, owner = boundary
    expected = (
        replace(initial, scope=replace(scope, edition_id=uuid4()))
        if change == "scope"
        else replace(initial, source_sha256="0" * 64)
    )
    with pytest.raises(SchedulingUnavailableError):
        queries.load_continuity_projection(
            scope, correlation_id=uuid4(), expected=expected
        )
    if change == "scope":
        owner.assert_not_called()
    else:
        owner.assert_called_once()


@pytest.mark.parametrize(
    "failure", [SchedulingAuthorizationDeniedError, SchedulingUnavailableError]
)
def test_final_owner_failure_cannot_become_a_cached_projection(boundary, failure):
    scope, initial, owner = boundary
    owner.side_effect = failure
    with pytest.raises(failure):
        queries.load_continuity_projection(
            scope, correlation_id=uuid4(), expected=initial
        )


def test_backward_or_naive_observations_never_renew_rendered_content(source, boundary):
    current, _scope, _name = source
    scope, initial, owner = boundary
    for at in (
        current.checked_at - timedelta(microseconds=1),
        current.checked_at.replace(tzinfo=None),
    ):
        owner.return_value = replace(current, checked_at=at)
        with pytest.raises(SchedulingUnavailableError):
            queries.load_continuity_projection(
                scope, correlation_id=uuid4(), expected=initial
            )
    assert (
        align_timetable_observation(current, observed_at=current.checked_at) == current
    )


def test_source_facts_not_displayed_in_cards_still_invalidate_the_digest(
    source, boundary
):
    current, scope, _name = source
    if scope.audience == "public":
        row = current.entries[0]
        changed = replace(
            current,
            entries=(
                replace(
                    row, copy=replace(row.copy, summary="Changed reviewed summary")
                ),
            ),
        )
    elif scope.audience == "exact_person":
        changed = replace(
            current,
            edition_label=PersonalTimetableEditionLabel("Changed edition context", 2),
        )
    else:
        placement = replace(current.entries[0].placement, placement_id=uuid4())
        changed = replace(
            current,
            reference=replace(current.reference, occurrences=(placement,)),
            entries=(replace(current.entries[0], placement=placement),),
        )
    _scope, initial, owner = boundary
    owner.return_value = changed
    later = queries.load_continuity_projection(scope, correlation_id=uuid4())
    assert (later.entries == initial.entries) == (scope.audience != "public")
    assert later.source_sha256 != initial.source_sha256
    with pytest.raises(SchedulingUnavailableError):
        queries.load_continuity_projection(
            scope, correlation_id=uuid4(), expected=initial
        )


def test_complete_source_comparison_keeps_changed_owner_fields(source):
    current, scope, _name = source
    if scope.audience == "exact_person":
        row = current.shifts[0]
        changed = replace(
            current,
            shifts=(
                replace(
                    row,
                    instructions=replace(
                        row.instructions, briefing="Changed private instructions"
                    ),
                ),
            ),
        )
    else:
        row = current.entries[0]
        changed = replace(
            current,
            entries=(
                replace(
                    row, copy=replace(row.copy, summary="Changed reviewed summary")
                ),
            ),
        )
    with pytest.raises(SchedulingUnavailableError):
        verify_timetable_observation(current, changed)


@pytest.fixture
def transport_shell():
    with (
        patch.object(operator_output_views.admin.site, "each_context", return_value={}),
        patch(
            "maru.events.templatetags.admin_edition_context.admin_shell_access",
            return_value={"workspace_available": False},
        ),
        patch(
            "maru.events.templatetags.admin_edition_context.project_shell_navigation",
            return_value={},
        ),
    ):
        yield


@pytest.mark.parametrize("output_format", ["html", "print", "json", "calendar"])
@pytest.mark.parametrize(
    ("failure", "status"),
    [(SchedulingAuthorizationDeniedError, 404), (SchedulingUnavailableError, 503)],
)
def test_all_output_transports_withhold_bytes_on_final_owner_failure(
    source, transport_shell, output_format, failure, status
):
    current, scope, name = source
    parameters = "".join(f"&{layer}=1" for layer in scope.layers)
    query = f"?format={output_format}{parameters}"
    if scope.audience == "public":
        module = output_views
        serve, arguments = public_view, (query,)
    elif scope.audience == "exact_person":
        module = personal_output_views
        serve, arguments = personal_view, (current, query)
    else:
        module = operator_output_views
        serve, arguments = operator_view, (current, query)
    with (
        patch.object(module, name, side_effect=[current, failure]) as owner,
        patch.object(operator_output_views, "authorize_operator_scope"),
        patch.object(module, "programme_output_links", return_value=()),
    ):
        response = serve(*arguments)
    assert owner.call_count == 2
    assert response.status_code == status
    assert "Content-Disposition" not in response
    assert b"Private host instructions" not in response.content
    assert b"Technical secret" not in response.content
    assert b"Current work briefing" not in response.content
    assert b"Opening" not in response.content


def _transport_route(source, output_format):
    current, scope, _name = source
    query = f"?format={output_format}" + "".join(
        f"&{layer}=1" for layer in scope.layers
    )
    if scope.audience == "public":
        return output_views, public_view, (query,)
    if scope.audience == "exact_person":
        return personal_output_views, personal_view, (current, query)
    return operator_output_views, operator_view, (current, query)


def test_changed_optional_links_are_omitted_before_final_source_proof(
    source, transport_shell
):
    current, _scope, name = source
    module, serve, arguments = _transport_route(source, "html")
    render_name = "_render_snapshot" if module is output_views else "_render"
    link = ProgrammeOutputLink("now", "Synthetic next task", "/synthetic-now/")
    events = []
    original = getattr(module, render_name)

    def render(*args, **kwargs):
        events.append("render")
        return original(*args, **kwargs)

    def owner(*args, **kwargs):
        events.append("owner")
        return current

    with (
        patch.object(module, name, side_effect=owner),
        patch.object(module, render_name, side_effect=render),
        patch.object(module, "programme_output_links", side_effect=[(link,), ()]),
        patch.object(operator_output_views, "authorize_operator_scope"),
    ):
        response = serve(*arguments)
    assert response.status_code == 200
    assert events == ["owner", "render", "render", "owner"]
    assert b"Synthetic next task" not in response.content
    assert b"/synthetic-now/" not in response.content


@pytest.mark.parametrize("output_format", ["html", "print", "json", "calendar"])
def test_navigation_only_appears_in_interactive_output(
    source, transport_shell, output_format
):
    current, scope, name = source
    module, serve, arguments = _transport_route(source, output_format)
    link = ProgrammeOutputLink("now", "Synthetic next task", "/synthetic-now/")
    with (
        patch.object(module, name, return_value=current) as owner,
        patch.object(
            module, "programme_output_links", return_value=(link,)
        ) as navigation,
        patch.object(operator_output_views, "authorize_operator_scope"),
    ):
        response = serve(*arguments)
    assert response.status_code == 200
    assert (b"Synthetic next task" in response.content) == (output_format == "html")
    assert navigation.call_count == (2 if output_format == "html" else 0)
    if output_format == "html":
        actual = navigation.call_args.args[0]
        assert actual.organization_id == (
            owner.call_args.args[0].organization_id
            if scope.audience == "private_operator"
            else owner.call_args.kwargs["organization_id"]
        )
        if scope.audience == "private_operator":
            assert actual.actor_id == owner.call_args.args[0].actor_id
            assert actual.target_id == scope.target_id
        elif scope.audience == "exact_person":
            assert actual.actor_id == current.actor_id
        assert actual.layers == scope.layers


@pytest.mark.parametrize("output_format", ["html", "print", "json", "calendar"])
def test_owner_content_moving_during_render_never_escapes(
    source, transport_shell, output_format
):
    current, scope, name = source
    module, serve, arguments = _transport_route(source, output_format)
    if scope.audience == "exact_person":
        row = current.shifts[0]
        changed = replace(
            current,
            shifts=(
                replace(
                    row,
                    instructions=replace(
                        row.instructions, briefing="Changed during rendering"
                    ),
                ),
            ),
        )
    else:
        row = current.entries[0]
        changed = replace(
            current,
            entries=(
                replace(
                    row, copy=replace(row.copy, summary="Changed during rendering")
                ),
            ),
        )
    owner = Mock(return_value=current)
    render_name = "_render_snapshot" if module is output_views else "_render"
    original = getattr(module, render_name)

    def render(*args, **kwargs):
        response = original(*args, **kwargs)
        owner.return_value = changed
        return response

    with (
        patch.object(module, name, owner),
        patch.object(module, render_name, side_effect=render),
        patch.object(module, "programme_output_links", return_value=()),
        patch.object(operator_output_views, "authorize_operator_scope"),
    ):
        response = serve(*arguments)
    assert response.status_code == 503
    assert "Content-Disposition" not in response
    assert b"Changed during rendering" not in response.content
    assert b"Opening" not in response.content
    assert b"Private handover instructions" not in response.content
