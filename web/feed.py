"""Compatibility wrapper for feed fetching.

The implementation moved to ``api.feed`` to centralize outbound request code.
"""

from ..api.feed import feed_get

__all__ = ["feed_get"]
