"""Request-scoped context for low-coupling user_id propagation.

Use set_user_id/reset_user_id in a web middleware (e.g., FastAPI) to inject
the current user_id into the async context. Callers can read it through
get_user_id() without changing function signatures across the codebase.
"""

from contextvars import ContextVar
from typing import Optional

_user_id_ctx: ContextVar[Optional[str]] = ContextVar("user_id", default=None)

def set_user_id(user_id: Optional[str]):
    """Set the current user_id in context; returns a token for reset."""
    return _user_id_ctx.set(user_id)

def reset_user_id(token) -> None:
    """Reset the context back to a previous token."""
    _user_id_ctx.reset(token)

def get_user_id() -> Optional[str]:
    """Get the current user_id from context, or None if not set."""
    return _user_id_ctx.get()

