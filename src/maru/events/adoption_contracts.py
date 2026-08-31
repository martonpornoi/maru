"""Import-safe contracts for module-owned adoption catalog entries.

The Events adoption manifest consumes these descriptors but this module does
not import Django, model classes, or the manifest itself. Product modules can
therefore declare their complete adapter and conflict-source catalogs without
creating an Events-to-owner import cycle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


_OWNER_MODULE_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
_VERSIONED_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]*(?:[.-][a-z0-9_]+)*@[1-9][0-9]*")


def _validate_descriptor_fields(
    *,
    code: str,
    owner_module: str,
    kind: str,
    result_semantics: str,
    failure_semantics: str,
) -> None:
    """Validate the shared fields of one adoption catalog descriptor.

    Parameters
    ----------
    code : str
        The canonical exact-version catalog code.
    owner_module : str
        The module expected to prefix the code.
    kind : str
        The stable adapter or conflict-source category.
    result_semantics : str
        The declared meaning of one successful result.
    failure_semantics : str
        The declared fail-closed behavior when the contract cannot produce a
        trustworthy result.

    Raises
    ------
    ValueError
        If the owner, versioned code, kind, result contract, or failure
        contract is invalid.
    """
    if _OWNER_MODULE_PATTERN.fullmatch(owner_module) is None:
        raise ValueError("Adoption descriptor owner_module must be a module token.")
    if _VERSIONED_CODE_PATTERN.fullmatch(code) is None:
        raise ValueError(
            "Adoption descriptor code must end in a positive canonical @version."
        )
    if not code.startswith(f"{owner_module}."):
        raise ValueError("Adoption descriptor code must use its owner module prefix.")
    if not kind.strip():
        raise ValueError("Adoption descriptor kind must not be empty.")
    if not result_semantics.strip():
        raise ValueError("Adoption descriptor result_semantics must not be empty.")
    if not failure_semantics.strip():
        raise ValueError("Adoption descriptor failure_semantics must not be empty.")


@dataclass(frozen=True, slots=True)
class AdoptionAdapterDescriptor:
    """Describe one exact-version adapter owned by a product module.

    Attributes
    ----------
    code
        The canonical owner-prefixed adapter code with a positive ``@version``.
    owner_module
        The module that owns and documents the adapter contract.
    kind
        The stable adapter category used to explain its invocation boundary.
    result_semantics
        The non-empty meaning of a successful adapter result.
    failure_semantics
        The non-empty fail-closed behavior for an unavailable, untrusted, or
        otherwise unsuccessful adapter result.
    """

    code: str
    owner_module: str
    kind: str
    result_semantics: str
    failure_semantics: str

    def __post_init__(self) -> None:
        """Reject malformed or semantically empty adapter declarations."""
        _validate_descriptor_fields(
            code=self.code,
            owner_module=self.owner_module,
            kind=self.kind,
            result_semantics=self.result_semantics,
            failure_semantics=self.failure_semantics,
        )

    @property
    def version(self) -> int:
        """Return the positive version encoded by the descriptor code.

        Returns
        -------
        int
            The positive canonical version following the final ``@``.
        """
        return int(self.code.rpartition("@")[2])


@dataclass(frozen=True, slots=True)
class AdoptionConflictSourceDescriptor:
    """Describe one exact-version scheduling conflict source.

    Attributes
    ----------
    code
        The canonical owner-prefixed source code with a positive ``@version``.
    owner_module
        The module that owns and documents the conflict evidence.
    kind
        The stable conflict-source category used by orchestration.
    result_semantics
        The non-empty meaning and completeness boundary of a source result.
    failure_semantics
        The non-empty behavior when the source is unavailable or cannot make
        its completeness claim.
    """

    code: str
    owner_module: str
    kind: str
    result_semantics: str
    failure_semantics: str

    def __post_init__(self) -> None:
        """Reject malformed or semantically empty source declarations."""
        _validate_descriptor_fields(
            code=self.code,
            owner_module=self.owner_module,
            kind=self.kind,
            result_semantics=self.result_semantics,
            failure_semantics=self.failure_semantics,
        )

    @property
    def version(self) -> int:
        """Return the positive version encoded by the descriptor code.

        Returns
        -------
        int
            The positive canonical version following the final ``@``.
        """
        return int(self.code.rpartition("@")[2])


def build_adoption_adapter_registry(
    *,
    owner_module: str,
    descriptors: Iterable[AdoptionAdapterDescriptor],
) -> Mapping[str, AdoptionAdapterDescriptor]:
    """Build an immutable owner-level adoption-adapter registry.

    Parameters
    ----------
    owner_module : str
        The module that must own every descriptor in the registry.
    descriptors : Iterable[AdoptionAdapterDescriptor]
        The complete literal descriptor declarations for that owner.

    Returns
    -------
    Mapping[str, AdoptionAdapterDescriptor]
        A read-only code-keyed registry retaining the descriptor objects.

    Raises
    ------
    ValueError
        If the owner token is malformed, a descriptor has another owner, or a
        code is declared more than once.
    """
    if _OWNER_MODULE_PATTERN.fullmatch(owner_module) is None:
        raise ValueError("Adoption registry owner_module must be a module token.")
    registry: dict[str, AdoptionAdapterDescriptor] = {}
    for descriptor in descriptors:
        if descriptor.owner_module != owner_module:
            raise ValueError("Adoption adapter registry contains another owner.")
        if descriptor.code in registry:
            raise ValueError("Adoption adapter registry codes must be unique.")
        registry[descriptor.code] = descriptor
    return MappingProxyType(registry)


def build_adoption_conflict_source_registry(
    *,
    owner_module: str,
    descriptors: Iterable[AdoptionConflictSourceDescriptor],
) -> Mapping[str, AdoptionConflictSourceDescriptor]:
    """Build an immutable owner-level conflict-source registry.

    Parameters
    ----------
    owner_module : str
        The module that must own every descriptor in the registry.
    descriptors : Iterable[AdoptionConflictSourceDescriptor]
        The complete literal source declarations for that owner.

    Returns
    -------
    Mapping[str, AdoptionConflictSourceDescriptor]
        A read-only code-keyed registry retaining the descriptor objects.

    Raises
    ------
    ValueError
        If the owner token is malformed, a descriptor has another owner, or a
        code is declared more than once.
    """
    if _OWNER_MODULE_PATTERN.fullmatch(owner_module) is None:
        raise ValueError("Adoption registry owner_module must be a module token.")
    registry: dict[str, AdoptionConflictSourceDescriptor] = {}
    for descriptor in descriptors:
        if descriptor.owner_module != owner_module:
            raise ValueError(
                "Adoption conflict-source registry contains another owner."
            )
        if descriptor.code in registry:
            raise ValueError("Adoption conflict-source registry codes must be unique.")
        registry[descriptor.code] = descriptor
    return MappingProxyType(registry)


FOUNDATION_ADOPTION_ADAPTERS = build_adoption_adapter_registry(
    owner_module="foundation",
    descriptors=(),
)
FOUNDATION_ADOPTION_CONFLICT_SOURCES = build_adoption_conflict_source_registry(
    owner_module="foundation",
    descriptors=(),
)


__all__ = [
    "FOUNDATION_ADOPTION_ADAPTERS",
    "FOUNDATION_ADOPTION_CONFLICT_SOURCES",
    "AdoptionAdapterDescriptor",
    "AdoptionConflictSourceDescriptor",
    "build_adoption_adapter_registry",
    "build_adoption_conflict_source_registry",
]
