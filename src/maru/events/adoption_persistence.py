"""Independent database support catalog for exact adoption-profile keys."""

from __future__ import annotations

import re

_PROFILE_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]*\Z")

_PERSISTED_ADOPTION_PROFILE_KEY_DECLARATIONS = (
    ("full_convention", 1),
    ("workforce_only", 1),
)

if len(frozenset(_PERSISTED_ADOPTION_PROFILE_KEY_DECLARATIONS)) != len(
    _PERSISTED_ADOPTION_PROFILE_KEY_DECLARATIONS
):
    raise RuntimeError("Persisted adoption-profile keys must be unique.")
if any(
    _PROFILE_CODE_PATTERN.fullmatch(code) is None
    or isinstance(version, bool)
    or not isinstance(version, int)
    or version < 1
    for code, version in _PERSISTED_ADOPTION_PROFILE_KEY_DECLARATIONS
):
    raise RuntimeError(
        "Persisted adoption-profile keys must be canonical and positive."
    )

PERSISTED_ADOPTION_PROFILE_KEYS = _PERSISTED_ADOPTION_PROFILE_KEY_DECLARATIONS
"""Exact profile pairs admitted by the current database check constraint."""

__all__ = ["PERSISTED_ADOPTION_PROFILE_KEYS"]
