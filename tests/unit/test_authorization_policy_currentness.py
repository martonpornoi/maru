"""Point-in-time policy checks must not cache or replace exact authority."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError
from django.utils import timezone

from maru.authorization import policy, provenance


def _arguments():
    return {
        "authority": SimpleNamespace(authority_issuance=SimpleNamespace(ordinal=17)),
        "principal": SimpleNamespace(id=uuid4()),
        "capability_code": "events.view_basic",
        "resource": object(),
        "evaluation_time": timezone.now(),
    }


def test_policy_submits_one_pinned_point_in_time_check_without_caching(monkeypatch):
    calls = []
    answers = iter((True, False))

    def current(**kwargs):
        calls.append(kwargs)
        return (next(answers),)

    monkeypatch.setattr(policy, "authority_issuances_are_current", current)
    arguments = _arguments()
    assert policy._exact_issuance_allows(**arguments)
    assert not policy._exact_issuance_allows(**arguments)
    expected = provenance.AuthorityIssuanceCurrentCheck(
        issuance_ordinal=17,
        principal_id=arguments["principal"].id,
        capability_code=arguments["capability_code"],
        target=arguments["resource"],
        requested_effective_from=arguments["evaluation_time"],
        requested_expires_at=None,
        horizon_mode=provenance.ControlHorizonMode.POINT_IN_TIME,
    )
    assert (
        calls
        == [
            {"checks": (expected,), "evaluated_at": arguments["evaluation_time"]},
        ]
        * 2
    )


def test_policy_missing_exact_issuance_never_searches_for_another_source(monkeypatch):
    class MissingIssuance:
        @property
        def authority_issuance(self):
            raise ObjectDoesNotExist

    def unexpected(**_kwargs):
        pytest.fail("Missing lineage must not reach the native validator.")

    monkeypatch.setattr(policy, "authority_issuances_are_current", unexpected)
    assert not policy._exact_issuance_allows(
        **(_arguments() | {"authority": MissingIssuance()})
    )


def test_native_policy_failure_cannot_fall_back_to_python_or_cached_success(
    monkeypatch,
):
    def unavailable(**_kwargs):
        raise DatabaseError("Synthetic validator unavailable.")

    def unexpected(**_kwargs):
        pytest.fail("Native unavailability must not switch the decision contract.")

    monkeypatch.setattr(policy, "authority_issuances_are_current", unavailable)
    monkeypatch.setattr(
        provenance, "_authority_issuances_are_current_python", unexpected
    )
    with pytest.raises(DatabaseError, match="Synthetic validator unavailable"):
        policy._exact_issuance_allows(**_arguments())


def test_single_issuance_writer_validator_keeps_independent_python_path(monkeypatch):
    observed = []

    def python_current(**kwargs):
        observed.append(kwargs)
        return (False,)

    def unexpected(**_kwargs):
        pytest.fail("The single-source writer boundary must remain independent.")

    monkeypatch.setattr(
        provenance, "_authority_issuances_are_current_python", python_current
    )
    monkeypatch.setattr(
        provenance, "_authority_issuances_are_current_database", unexpected
    )
    now = timezone.now()
    assert not provenance.authority_issuance_is_current(
        issuance_ordinal=17,
        principal_id=uuid4(),
        capability_code="events.edit",
        target=object(),
        requested_effective_from=now,
        requested_expires_at=None,
        evaluated_at=now,
    )
    assert len(observed) == 1
    assert (
        observed[0]["checks"][0].horizon_mode
        is provenance.ControlHorizonMode.PERSISTENT
    )
    assert observed[0]["lock"] is False
