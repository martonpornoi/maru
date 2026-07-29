"""Request correlation state with no personal payload."""

from contextvars import ContextVar

correlation_id: ContextVar[str | None] = ContextVar(
    "maru_correlation_id",
    default=None,
)
