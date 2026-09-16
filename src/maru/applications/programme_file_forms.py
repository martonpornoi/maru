"""Bounded original-intent proofs and explicit supporting-answer clearing."""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from django import forms
from django.core import signing

from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_reference_sources import (
    ProgrammeAnswerReferenceIntent,
    ProgrammeAnswerReferenceRequest,
    _binding,
    _intent,
    _values,
)

MAX_FILE_INTENT_BYTES = 2048
_PURPOSES = frozenset({"upload", "clear"})


class ProgrammeFileClearForm(forms.Form):
    """Keep original signed scope and require deliberate current-answer clearing."""

    token = forms.CharField(max_length=MAX_FILE_INTENT_BYTES, widget=forms.HiddenInput)
    confirm = forms.BooleanField(
        label="Clear this current answer; retained files and sealed history remain."
    )


def _salt(purpose: str) -> str:
    if purpose not in _PURPOSES:
        raise Denied
    return f"applications.programme-file-intent.{purpose}.v1"


def _encode(
    request: ProgrammeAnswerReferenceRequest,
    intent: ProgrammeAnswerReferenceIntent,
    *,
    purpose: str,
) -> str:
    _values(request)
    _intent(intent)
    token = signing.dumps(
        {
            "scope": _binding(request),
            "intent": {
                key: str(value) if isinstance(value, UUID) else value
                for key, value in asdict(intent).items()
            },
        },
        salt=_salt(purpose),
    )
    if len(token.encode("ascii")) > MAX_FILE_INTENT_BYTES:
        raise Denied
    return token


def _decode(
    request: ProgrammeAnswerReferenceRequest, token: str, *, purpose: str
) -> ProgrammeAnswerReferenceIntent:
    _values(request)
    try:
        if (
            not isinstance(token, str)
            or not token
            or token.startswith(".")
            or len(token.encode("ascii")) > MAX_FILE_INTENT_BYTES
        ):
            raise Denied
        value = signing.loads(token, salt=_salt(purpose))
        if (
            type(value) is not dict
            or set(value) != {"scope", "intent"}
            or value["scope"] != _binding(request)
            or type(value["intent"]) is not dict
            or set(value["intent"])
            != set(ProgrammeAnswerReferenceIntent.__dataclass_fields__)
        ):
            raise Denied
        values = value["intent"]
        retry = values["retry_key"]
        if not isinstance(retry, str):
            raise Denied
        retry_key = UUID(retry)
        if str(retry_key) != retry:
            raise Denied
        intent = ProgrammeAnswerReferenceIntent(**(values | {"retry_key": retry_key}))
        _intent(intent)
    except (signing.BadSignature, ValueError, TypeError) as error:
        raise Denied from error
    return intent
