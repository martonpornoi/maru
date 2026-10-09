"""Native adapters accept only their actual authenticated Identity principal."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.utils.functional import SimpleLazyObject

from maru.identity.models import Account
from maru.identity.request_actor import authenticated_request_actor


def test_returns_the_same_active_request_account_without_database_access():
    actor = Account(id=UUID(int=1), email="reader@example.invalid", is_active=True)
    request = RequestFactory().get("/")
    request.user = actor
    assert authenticated_request_actor(request) is actor


def test_preserves_django_lazy_authentication_principal():
    actor = Account(id=UUID(int=1), email="reader@example.invalid", is_active=True)
    request = RequestFactory().get("/")
    request.user = SimpleLazyObject(lambda: actor)
    assert authenticated_request_actor(request) is request.user
    assert authenticated_request_actor(request).pk == actor.pk


@pytest.mark.parametrize(
    "actor",
    [
        None,
        AnonymousUser(),
        Account(id=UUID(int=1), email="inactive@example.invalid", is_active=False),
        SimpleNamespace(pk=UUID(int=1), is_authenticated=True, is_active=True),
    ],
)
def test_rejects_missing_inactive_anonymous_or_lookalike_principals(actor):
    request = RequestFactory().get("/")
    request.user = actor
    with pytest.raises(PermissionDenied):
        authenticated_request_actor(request)


def test_rejects_a_request_without_authentication_middleware():
    with pytest.raises(PermissionDenied):
        authenticated_request_actor(RequestFactory().get("/"))
