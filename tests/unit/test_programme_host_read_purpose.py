"""Closed hosting attribution preserves the existing personal timetable policy."""

from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.programme import timetable_queries as queries


@pytest.mark.parametrize(
    ("options", "operation", "channel"),
    [
        ({}, "programme.query.personal_host_timetable", "programme-timetable"),
        (
            {"purpose": "hosting"},
            "programme.query.personal_host_workspace",
            "programme-hosts",
        ),
    ],
)
def test_read_attribution_cannot_widen_the_exact_self_scope(
    monkeypatch, options, operation, channel
):
    authorization = Mock()
    purposes = Mock(return_value=())
    boundary = Mock(side_effect=lambda **kwargs: kwargs["loader"]())
    monkeypatch.setattr(queries, "authorize_programme_scope", authorization)
    monkeypatch.setattr(queries, "_purposes", purposes)
    monkeypatch.setattr(queries, "_authorized_query", boundary)
    scope = dict(
        zip(
            ("actor_id", "organization_id", "edition_id", "correlation_id"),
            (UUID(int=i) for i in range(1, 5)),
            strict=True,
        )
    )
    assert queries.load_personal_host_purposes(**scope, **options) == ()
    kwargs = boundary.call_args.kwargs
    assert kwargs["operation"] == operation
    assert kwargs["source_channel"] == channel
    assert kwargs["requested_fields"] == frozenset(
        {"own_host_relationship", "own_host_invitation"}
    )
    assert kwargs["capability_code"] == "programme.view_host_self"
    assert kwargs["target_id"] == scope["edition_id"]
    assert kwargs["target_count"](()) == 0
    authorization.assert_called_once_with(
        actor_id=scope["actor_id"],
        organization_id=scope["organization_id"],
        edition_id=scope["edition_id"],
        capability_code=kwargs["capability_code"],
        requested_fields=kwargs["requested_fields"],
        lock=True,
    )
    purposes.assert_called_once_with(
        scope["actor_id"], scope["organization_id"], scope["edition_id"]
    )


def test_unknown_attribution_stops_before_authorization_or_owner_reads(monkeypatch):
    boundary = Mock()
    monkeypatch.setattr(queries, "_authorized_query", boundary)
    with pytest.raises(ValueError, match="registered"):
        queries.load_personal_host_purposes(
            actor_id=UUID(int=1),
            organization_id=UUID(int=2),
            edition_id=UUID(int=3),
            correlation_id=UUID(int=4),
            purpose="organizer-roster",
        )
    boundary.assert_not_called()
