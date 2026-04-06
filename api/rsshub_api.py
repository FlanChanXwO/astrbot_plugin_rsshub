"""Helpers for RSSHub route discovery and URL building for LLM tools."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp


def normalize_base_url(base_url: str) -> str:
    """Normalize base URL to scheme + netloc form."""
    raw = (base_url or "").strip()
    if not raw:
        raise ValueError("base_url 不能为空")

    parsed = urlsplit(raw)
    if not parsed.netloc:
        parsed = urlsplit(f"https://{raw}")

    scheme = (parsed.scheme or "https").lower()
    if scheme not in {"http", "https"}:
        raise ValueError("base_url 仅支持 http 或 https")

    netloc = (parsed.netloc or "").strip().lower()
    if not netloc:
        raise ValueError("base_url 非法")

    return urlunsplit((scheme, netloc, "", "", "")).rstrip("/")


def normalize_uri(uri: str) -> str:
    """Normalize route uri while preserving route params pattern."""
    raw = (uri or "").strip()
    if not raw:
        raise ValueError("uri 不能为空")

    parsed = urlsplit(raw)
    path = parsed.path or raw
    if not path.startswith("/"):
        path = "/" + path

    # Route matching should not include query/fragment.
    return urlunsplit(("", "", path.rstrip("/") or "/", "", ""))


class RSSHubRadarAPI:
    """Fetch and index RSSHub radar rules with a small in-memory cache."""

    def __init__(
        self,
        timeout: int = 30,
        proxy: str = "",
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.timeout = max(1, int(timeout or 30))
        self.proxy = (proxy or "").strip()
        self._cache_ttl = 300
        self._rules_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._session = session
        self._owns_session = session is None

    async def close(self) -> None:
        """Close internal aiohttp session when owned by this helper."""
        if (
            self._owns_session
            and self._session is not None
            and not self._session.closed
        ):
            await self._session.close()
        self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    def resolve_base_url(self, explicit_base_url: str, default_base_url: str) -> str:
        """Resolve base URL with explicit override support."""
        chosen = (explicit_base_url or "").strip() or default_base_url
        return normalize_base_url(chosen)

    async def search_routes(
        self,
        *,
        query: str,
        top_k: int,
        explicit_base_url: str,
        default_base_url: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Return a concise route list filtered by query."""
        resolved_base_url = self.resolve_base_url(explicit_base_url, default_base_url)
        rules = await self._get_rules(resolved_base_url)

        tokens = [token for token in query.lower().split() if token]
        scored: list[tuple[int, dict[str, Any]]] = []
        for rule in rules:
            searchable = " ".join(
                [
                    str(rule.get("uri", "")).lower(),
                    str(rule.get("title", "")).lower(),
                    str(rule.get("brief", "")).lower(),
                    " ".join(rule.get("required_params", [])),
                    " ".join(rule.get("optional_params", [])),
                ]
            )
            if not tokens:
                score = 1
            else:
                score = sum(1 for token in tokens if token in searchable)
                if score == 0:
                    continue

            scored.append((score, rule))

        scored.sort(key=lambda item: (-item[0], item[1].get("uri", "")))
        selected = [
            {
                "uri": item[1].get("uri", ""),
                "title": item[1].get("title", ""),
                "required_params": item[1].get("required_params", []),
                "optional_params": item[1].get("optional_params", []),
                "brief": item[1].get("brief", ""),
            }
            for item in scored[:top_k]
        ]
        return resolved_base_url, selected

    async def get_route_schema(
        self,
        *,
        uri: str,
        explicit_base_url: str,
        default_base_url: str,
    ) -> tuple[str, dict[str, Any] | None]:
        """Return one route schema by URI."""
        resolved_base_url = self.resolve_base_url(explicit_base_url, default_base_url)
        normalized_uri = normalize_uri(uri)
        rules = await self._get_rules(resolved_base_url)

        for rule in rules:
            if rule.get("uri") == normalized_uri:
                return (
                    resolved_base_url,
                    {
                        "uri": rule.get("uri", ""),
                        "title": rule.get("title", ""),
                        "required_params": rule.get("required_params", []),
                        "optional_params": rule.get("optional_params", []),
                        "brief": rule.get("brief", ""),
                        "param_details": rule.get("param_details", {}),
                    },
                )

        return resolved_base_url, None

    def build_subscribe_url(
        self,
        *,
        uri: str,
        params: dict[str, str],
        explicit_base_url: str,
        default_base_url: str,
    ) -> tuple[str, str]:
        """Build full subscription URL from base URL + uri + query params."""
        resolved_base_url = self.resolve_base_url(explicit_base_url, default_base_url)
        normalized_uri = normalize_uri(uri)

        parsed_uri = urlsplit(normalized_uri)
        query_pairs = dict(parse_qsl(parsed_uri.query, keep_blank_values=True))
        query_pairs.update({k: str(v) for k, v in params.items() if k})

        query = urlencode(query_pairs, doseq=True)
        full_url = f"{resolved_base_url}{parsed_uri.path}"
        if query:
            full_url = f"{full_url}?{query}"
        return resolved_base_url, full_url

    async def _get_rules(self, resolved_base_url: str) -> list[dict[str, Any]]:
        """Load and normalize rules from /api/radar/rules with cache."""
        now = time.monotonic()
        cached = self._rules_cache.get(resolved_base_url)
        if cached and (now - cached[0] < self._cache_ttl):
            return cached[1]

        rules_url = f"{resolved_base_url}/api/radar/rules"
        session = await self._get_session()
        async with session.get(
            rules_url,
            timeout=self.timeout,
            proxy=self.proxy or None,
            headers={"Accept": "application/json"},
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f"获取 RSSHub 路由失败: HTTP {resp.status} {resp.reason or ''}".strip()
                )
            payload = await resp.json(content_type=None)

        rules = self._normalize_rules(payload)
        self._rules_cache[resolved_base_url] = (now, rules)
        return rules

    def _normalize_rules(self, payload: Any) -> list[dict[str, Any]]:
        """Flatten various radar JSON structures into a normalized route list."""
        route_map: dict[str, dict[str, Any]] = {}

        def walk(node: Any, inherited_title: str = "") -> None:
            if isinstance(node, dict):
                title = str(node.get("title") or node.get("name") or inherited_title)
                route = self._route_from_node(node, title)
                if route is not None:
                    existing = route_map.get(route["uri"])
                    if existing is None:
                        route_map[route["uri"]] = route
                    else:
                        existing["required_params"] = sorted(
                            set(existing["required_params"])
                            | set(route["required_params"])
                        )
                        existing["optional_params"] = sorted(
                            set(existing["optional_params"])
                            | set(route["optional_params"])
                        )
                        if not existing.get("title") and route.get("title"):
                            existing["title"] = route["title"]
                        if not existing.get("brief") and route.get("brief"):
                            existing["brief"] = route["brief"]
                        existing["param_details"].update(route.get("param_details", {}))

                for value in node.values():
                    walk(value, title)
                return

            if isinstance(node, list):
                for item in node:
                    walk(item, inherited_title)

        walk(payload)
        return [route_map[key] for key in sorted(route_map)]

    def _route_from_node(
        self, node: dict[str, Any], inherited_title: str
    ) -> dict[str, Any] | None:
        uri = ""
        for key in ("path", "route", "uri"):
            value = node.get(key)
            if isinstance(value, str) and value.strip().startswith("/"):
                uri = normalize_uri(value)
                break

        if not uri:
            return None

        required_params: set[str] = set()
        optional_params: set[str] = set()
        param_details: dict[str, dict[str, Any]] = {}

        self._collect_params(
            node.get("params") or node.get("parameters"),
            required_params,
            optional_params,
            param_details,
        )

        required = node.get("required")
        if isinstance(required, list):
            for item in required:
                if isinstance(item, str) and item.strip():
                    required_params.add(item.strip())
                    optional_params.discard(item.strip())

        brief_source = node.get("description") or node.get("desc") or ""
        brief = str(brief_source).strip()[:200]
        title = str(
            node.get("title") or node.get("name") or inherited_title or ""
        ).strip()

        # Required params should not also appear in optional params.
        optional_params -= required_params

        return {
            "uri": uri,
            "title": title,
            "required_params": sorted(required_params),
            "optional_params": sorted(optional_params),
            "brief": brief,
            "param_details": param_details,
        }

    def _collect_params(
        self,
        raw_params: Any,
        required_params: set[str],
        optional_params: set[str],
        param_details: dict[str, dict[str, Any]],
    ) -> None:
        if raw_params is None:
            return

        if isinstance(raw_params, dict):
            for key, value in raw_params.items():
                if not isinstance(key, str) or not key.strip():
                    continue
                param_name = key.strip()
                detail: dict[str, Any] = {}
                is_required = False

                if isinstance(value, dict):
                    is_required = bool(value.get("required", False))
                    for field in ("description", "desc", "example", "type"):
                        if field in value and value[field] is not None:
                            detail[field] = value[field]
                elif isinstance(value, str) and value.strip():
                    detail["description"] = value.strip()

                if is_required:
                    required_params.add(param_name)
                else:
                    optional_params.add(param_name)

                if detail:
                    param_details[param_name] = detail
            return

        if isinstance(raw_params, list):
            for item in raw_params:
                if isinstance(item, str) and item.strip():
                    optional_params.add(item.strip())
                    continue

                if not isinstance(item, dict):
                    continue

                name = ""
                for key in ("name", "key", "param"):
                    raw_name = item.get(key)
                    if isinstance(raw_name, str) and raw_name.strip():
                        name = raw_name.strip()
                        break
                if not name:
                    continue

                if bool(item.get("required", False)):
                    required_params.add(name)
                else:
                    optional_params.add(name)

                detail: dict[str, Any] = {}
                for field in ("description", "desc", "example", "type"):
                    if field in item and item[field] is not None:
                        detail[field] = item[field]
                if detail:
                    param_details[name] = detail
