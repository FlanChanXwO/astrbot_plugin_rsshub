"""Compatibility re-export for RSSHub API helpers.

Keep old import paths stable while the canonical implementation lives in ``api``.
"""

from ..api.rsshub_api import RSSHubRadarAPI, normalize_base_url, normalize_uri

__all__ = ["RSSHubRadarAPI", "normalize_base_url", "normalize_uri"]
