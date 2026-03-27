"""Named exception hierarchy for give-back.

All custom exceptions inherit from GiveBackError. No catch-all `except Exception`
anywhere — each handler names the specific exception it catches.
"""


class GiveBackError(Exception):
    """Base exception for all give-back errors."""


class AuthenticationError(GiveBackError):
    """GitHub API returned 401 — token is invalid or expired."""


class RateLimitError(GiveBackError):
    """GitHub API returned 403 with rate-limit headers, or X-RateLimit-Remaining is 0."""

    def __init__(self, message: str, reset_at: int | None = None):
        super().__init__(message)
        self.reset_at = reset_at
        """Unix timestamp when the rate limit resets (from X-RateLimit-Reset header)."""


class RepoNotFoundError(GiveBackError):
    """Repository does not exist or is private (404 from GitHub, or GraphQL repository: null)."""


class GraphQLError(GiveBackError):
    """GraphQL response contained errors (HTTP 200 but errors key present)."""

    def __init__(self, message: str, errors: list[dict] | None = None):
        super().__init__(message)
        self.errors = errors or []
        """Raw error objects from the GraphQL response."""


class StateCorruptError(GiveBackError):
    """State file exists but contains invalid JSON or unexpected schema."""


class ForkError(GiveBackError):
    """Fork operation failed — gh CLI missing, not authenticated, or fork API error."""


class WorkspaceError(GiveBackError):
    """Workspace setup failed — clone error, wrong remote, or dirty branch."""
