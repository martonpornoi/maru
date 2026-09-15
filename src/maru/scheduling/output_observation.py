"""Compare complete timetable sources without renewing a rendered observation."""

from dataclasses import replace
from datetime import datetime

from .command_support import SchedulingUnavailableError
from .operator_output_queries import OperatorRunSheet
from .output_queries import PublicProgrammeTimetable
from .personal_output_queries import PersonalTimetable


def align_timetable_observation[
    SourceT: (PublicProgrammeTimetable, PersonalTimetable, OperatorRunSheet)
](source: SourceT, *, observed_at: datetime) -> SourceT:
    """Align only the clock on freshly reauthorized data for a complete comparison.

    Parameters
    ----------
    source : SourceT
        Complete new result of the same trusted owner query, never cached input.
    observed_at : datetime
        Original server-owned observation whose already rendered bytes are retained.

    Returns
    -------
    SourceT
        New immutable DTO with only checked_at aligned; every owner fact is unchanged.

    Raises
    ------
    SchedulingUnavailableError
        If either observation is invalid or the fresh owner clock moved backwards.

    Notes
    -----
    This pure operation grants no authority. Callers must compare the complete result
    or its canonical source digest, not only the fields displayed as timetable cards.
    It never renews source age, signed expiry or an already rendered response.
    """
    if (
        type(source)
        not in {PublicProgrammeTimetable, PersonalTimetable, OperatorRunSheet}
        or not isinstance(observed_at, datetime)
        or observed_at.utcoffset() is None
        or not isinstance(source.checked_at, datetime)
        or source.checked_at.utcoffset() is None
        or source.checked_at < observed_at
    ):
        raise SchedulingUnavailableError
    return replace(source, checked_at=observed_at)


def verify_timetable_observation[
    SourceT: (PublicProgrammeTimetable, PersonalTimetable, OperatorRunSheet)
](original: SourceT, current: SourceT) -> None:
    """Withhold rendered bytes if any complete current owner fact has changed.

    Parameters
    ----------
    original : SourceT
        Validated original in-request source whose response has already been rendered.
    current : SourceT
        Freshly reauthorized complete source from the same trusted owner arguments.

    Raises
    ------
    SchedulingUnavailableError
        If any source fact differs or its observation clock moved backwards.

    Notes
    -----
    Only the current read's observation timestamp is aligned for comparison. Original
    response bytes, source age and source-specific versions are never substituted.
    """
    if (
        align_timetable_observation(current, observed_at=original.checked_at)
        != original
    ):
        raise SchedulingUnavailableError
