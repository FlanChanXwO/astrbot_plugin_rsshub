"""RSS-to-AstrBot Web Module."""

from __future__ import annotations

from .webui import RSSHubWebUI, resolve_webui_config


async def feed_get(*args, **kwargs):
    """Lazy proxy kept for backward compatibility with old import paths."""
    from .feed import feed_get as _feed_get

    return await _feed_get(*args, **kwargs)


__all__ = ["feed_get", "RSSHubWebUI", "resolve_webui_config"]
