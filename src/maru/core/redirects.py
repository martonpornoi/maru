"""Local-only HTTP continuations for server-owned application destinations."""

from django.core.exceptions import SuspiciousOperation
from django.http import HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme

_FIRST_PRINTABLE_ASCII = 32
_ASCII_DELETE = 127


def local_redirect(destination: str) -> HttpResponseRedirect:
    """Redirect only to an absolute path on the current origin.

    Parameters
    ----------
    destination : str
        Server-constructed path, optionally including a query or fragment. Callers
        must choose the owning route and authorize its scope independently.

    Returns
    -------
    HttpResponseRedirect
        Temporary redirect retaining the local path and its encoded parameters.

    Raises
    ------
    SuspiciousOperation
        If the target is not an absolute local path, contains a browser-ambiguous
        backslash or control character, or names a scheme or remote authority.

    Notes
    -----
    An empty host allowlist intentionally rejects even absolute same-host URLs.
    Request Host headers and caller-supplied return URLs grant no redirect trust.
    """
    if (
        not destination.startswith("/")
        or "\\" in destination
        or any(
            ord(character) < _FIRST_PRINTABLE_ASCII or ord(character) == _ASCII_DELETE
            for character in destination
        )
        or not url_has_allowed_host_and_scheme(destination, allowed_hosts=set())
    ):
        raise SuspiciousOperation(
            "Redirect destination must be an absolute local path."
        )
    return HttpResponseRedirect(destination)
