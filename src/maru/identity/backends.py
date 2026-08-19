"""Authentication backends for human login aliases and email addresses."""

from typing import Any

from django.contrib.auth.backends import ModelBackend
from django.db.models import Q
from django.http import HttpRequest

from maru.identity.models import Account


class EmailOrHandleBackend(ModelBackend):
    """Authenticate an account by either its email or optional public handle."""

    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> Account | None:
        """Authenticate.

        Parameters
        ----------
        request : HttpRequest | None
            The incoming HTTP request and authenticated principal context.
        username : str | None, default=None
            The username evaluated while authenticate.
        password : str | None, default=None
            The plaintext secret to verify without logging or retaining it.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Returns
        -------
        Account | None
            The resolved Account | None for authenticate.
        """
        del request
        identifier = username or kwargs.get(Account.USERNAME_FIELD)
        if not isinstance(identifier, str) or password is None:
            return None
        normalized = identifier.strip()
        matches = list(
            Account.objects.filter(
                Q(email__iexact=normalized) | Q(login_handle__iexact=normalized)
            )[:2]
        )
        if len(matches) != 1:
            # Retain the password hasher's cost for missing and ambiguous identifiers.
            Account().set_password(password)
            return None
        account = matches[0]
        if account.check_password(password) and self.user_can_authenticate(account):
            return account
        return None
