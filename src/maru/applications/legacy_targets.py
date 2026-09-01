"""Closed target catalog exposed through the legacy Applications workflow.

Programme proposals deliberately reuse the Applications-owned form engine, but
they have a separate collaboration, sealing, and acknowledgement lifecycle.
Keeping this allowlist explicit prevents a newly added target kind from becoming
visible or mutable through the generic applicant and reviewer surfaces by
accident.
"""

LEGACY_APPLICATION_TARGET_KINDS: tuple[str, ...] = (
    "merch_submission",
    "dj_set",
    "fursuit_dance_competition",
    "maid_cafe",
    "adult_fursuit_striptease",
    "volunteer",
    "feedback",
    "idea",
    "damage_report",
    "helper",
)
"""Target kinds admitted by the pre-Programme Applications workflow."""


def is_legacy_application_target(target_kind: str) -> bool:
    """Return whether a target belongs to the closed legacy catalog.

    Parameters
    ----------
    target_kind : str
        Target-adapter kind to compare with the legacy allowlist.

    Returns
    -------
    bool
        ``True`` when the target remains available to generic Applications.
    """
    return target_kind in LEGACY_APPLICATION_TARGET_KINDS
