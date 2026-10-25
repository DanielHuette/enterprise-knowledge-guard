"""Exception hierarchy of the service.

Context: Expected failures are raised as GuardError subclasses so the HTTP layer can map
them to precise status codes. | Input: none. | Output: exception classes.
"""


class GuardError(Exception):
    """Base class for all errors raised deliberately by this package."""


class AuthError(GuardError):
    """A token is missing, malformed, forged or expired."""


class ToolDenied(GuardError):  # noqa: N818 - reads as a domain event, not a generic error
    """The caller's role does not allow the requested tool."""

    def __init__(self, tool: str, needed: str, have: str) -> None:
        self.tool = tool
        self.needed = needed
        self.have = have
        super().__init__(f"Tool '{tool}' requires at least role '{needed}', caller has '{have}'.")


class ActionRejected(GuardError):  # noqa: N818 - domain event, mirrors ToolDenied
    """An allowed tool was called with a request the data does not permit."""

    def __init__(self, message: str, status_code: int = 409) -> None:
        self.status_code = status_code
        super().__init__(message)


class UpstreamError(GuardError):
    """A model or embedding provider failed after all retries."""
