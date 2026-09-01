"""Entry content handler runtime for RSS push pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any

from pydantic import Field
from pydantic.dataclasses import dataclass as pydantic_dataclass

try:
    from astrbot.core.agent.run_context import ContextWrapper
    from astrbot.core.agent.tool import FunctionTool, ToolExecResult, ToolSet
    from astrbot.core.astr_agent_context import AstrAgentContext
    from astrbot.core.message.message_event_result import MessageEventResult
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
except Exception:  # pragma: no cover - lightweight test fallback

    class ContextWrapper:  # type: ignore[no-redef]
        pass

    ToolExecResult = str  # type: ignore[assignment]

    @dataclass
    class FunctionTool:  # type: ignore[no-redef]
        name: str
        description: str
        parameters: dict

        @classmethod
        def __class_getitem__(cls, _item):
            return cls

    class ToolSet:  # type: ignore[no-redef]
        def __init__(self, tools: list[Any] | None = None) -> None:
            self.tools = tools or []

    class AstrAgentContext:  # type: ignore[no-redef]
        pass

    class MessageEventResult:  # type: ignore[no-redef]
        def __init__(self) -> None:
            self.chain: list[Any] = []

        def message(self, text: str) -> MessageEventResult:
            self.chain = [text]
            return self

    class AstrMessageEvent:  # type: ignore[no-redef]
        unified_msg_origin: str = ""


try:
    from astrbot.core.provider.provider import Provider
except Exception:  # pragma: no cover - lightweight test fallback

    class Provider:  # type: ignore[no-redef]
        pass


from ...domain.entities.content_types import LayoutFragment
from ...domain.entities.handlers import (
    HandlerSpec,
    is_handler_enabled,
    normalize_handlers,
)
from ...domain.entities.subscription import (
    HANDLERS_MODE_DISABLED,
    HANDLERS_MODE_INHERIT,
    HANDLERS_MODE_OVERRIDE,
    Subscription,
)
from ...domain.entities.user import User
from ...infrastructure.config import ContentHandlerSettings
from ...infrastructure.utils import get_logger
from ...shared.constants import (
    AiFilterInputScope,
    AiTransformScope,
    HandlerTraceStatus,
    HandlerType,
)
from .html_parser import HTMLParser

logger = get_logger()


class _SyntheticHandlerEvent(AstrMessageEvent):
    """Minimal event adapter for tool_loop_agent in non-chat paths.

    继承 AstrMessageEvent 以通过 AstrAgentContext 的 pydantic ``isinstance``
    校验（修复 Web 测试推送/自动轮询路径下 scope=xml 的 ai_transform 因
    ``Input should be an instance of AstrMessageEvent`` 永远失败、回退原文），
    同时提供所有必要方法的最小实现，使 tool_loop_agent 在无真实事件时可用。
    __init__ 不调用父类构造（框架父类可能要求复杂参数），只注入
    tool_loop_agent 实际使用的最小子集。
    """

    def __init__(
        self,
        *,
        unified_msg_origin: str,
        platform_name: str,
        sender_id: str,
    ) -> None:
        self.unified_msg_origin = str(unified_msg_origin or "").strip()
        self.role = "member"
        self._platform_name = str(platform_name or "").strip()
        self._sender_id = str(sender_id or "").strip()
        self._result: MessageEventResult | None = None
        self._extras: dict[str, Any] = {}

    def get_result(self) -> MessageEventResult | None:
        return self._result

    def set_result(self, result: MessageEventResult | str) -> None:
        if isinstance(result, str):
            self._result = MessageEventResult().message(result)
            return
        self._result = result

    def get_extra(self, key: str | None = None, default=None) -> Any:
        if key is None:
            return self._extras
        return self._extras.get(key, default)

    def set_extra(self, key: str, value: Any) -> None:
        self._extras[key] = value

    def get_sender_id(self) -> str:
        return self._sender_id

    def get_platform_name(self) -> str:
        return self._platform_name

    async def send(self, _message) -> None:
        return None


@pydantic_dataclass
class XmlValidationTool(FunctionTool[AstrAgentContext]):
    name: str = "rss_validate_xml_fragment"
    description: str = (
        "Validate one RSS/Atom item or entry XML fragment. "
        "Returns ok=false with precise parse/safety errors."
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "raw_xml": {
                    "type": "string",
                    "description": "Single item/entry XML fragment to validate.",
                }
            },
            "required": ["raw_xml"],
        }
    )

    async def call(
        self,
        _context: ContextWrapper[AstrAgentContext],
        **kwargs,
    ) -> ToolExecResult:
        raw_xml = str(kwargs.get("raw_xml") or "").strip()
        from .agent_xml_push_service import _parse_xml_root, _validate_xml_input

        try:
            _validate_xml_input(raw_xml)
            _parse_xml_root(raw_xml)
        except Exception as exc:
            return json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "rules": [
                        "只返回单个 item 或 entry 级 XML 片段",
                        "不要包含 DOCTYPE 或 ENTITY",
                        "不要输出 Markdown、解释文本或代码块包裹",
                    ],
                },
                ensure_ascii=False,
            )
        return json.dumps({"ok": True}, ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class EntryContentContext:
    """Raw entry payload before formatting for one subscription."""

    title: str
    summary: str
    content: str
    link: str
    author: str
    feed_title: str
    feed_link: str
    raw_xml: str = ""
    media_urls: tuple[str, ...] = ()
    media_items: tuple[tuple[str, str], ...] = ()
    layout: tuple[LayoutFragment, ...] = ()


@dataclass(frozen=True, slots=True)
class HandlerProcessResult:
    """Content handler result plus runtime trace."""

    entry: EntryContentContext
    allow: bool = True
    reason: str = ""
    trace: tuple[dict[str, Any], ...] = ()


class ContentHandlerRuntime:
    """Resolve and execute builtin entry handlers."""

    def __init__(
        self,
        context: Any | None = None,
        settings: ContentHandlerSettings | None = None,
    ):
        self._context = context
        self._settings = settings or ContentHandlerSettings()

    def resolve_handlers(
        self,
        *,
        subscription: Subscription,
        user: User | None,
    ) -> list[HandlerSpec]:
        mode = str(getattr(subscription, "handlers_mode", "") or "").strip().lower()
        if mode == HANDLERS_MODE_DISABLED:
            active = []
        elif mode == HANDLERS_MODE_OVERRIDE:
            active = subscription.get_handlers()
        else:  # inherit
            # inherit 语义：订阅自带 handlers 优先，未配置才回落用户级。
            # 修复：原实现兜底条件 mode not in {INHERIT,...} 等价于"mode 是
            # 未知值"，对 inherit（已知 mode）永远不成立，导致订阅自带
            # handlers 被完全忽略，所有订阅都套用户级 handlers。
            sub_handlers = subscription.get_handlers()
            active = sub_handlers if sub_handlers else (
                user.get_handlers() if user else []
            )
        return normalize_handlers(active)

    async def process_entry(
        self,
        *,
        subscription: Subscription,
        user: User | None,
        entry: EntryContentContext,
        session_id: str | None = None,
        event: AstrMessageEvent | Any | None = None,
        target_session: str | None = None,
        platform_name: str | None = None,
        user_id: str | None = None,
    ) -> EntryContentContext:
        result = await self.process_entry_with_trace(
            subscription=subscription,
            user=user,
            entry=entry,
            session_id=session_id,
            event=event,
            target_session=target_session,
            platform_name=platform_name,
            user_id=user_id,
        )
        return result.entry

    async def process_entry_with_trace(
        self,
        *,
        subscription: Subscription,
        user: User | None,
        entry: EntryContentContext,
        session_id: str | None = None,
        event: AstrMessageEvent | Any | None = None,
        target_session: str | None = None,
        platform_name: str | None = None,
        user_id: str | None = None,
    ) -> HandlerProcessResult:
        result = entry
        trace: list[dict[str, Any]] = []
        for spec in self.resolve_handlers(subscription=subscription, user=user):
            if not is_handler_enabled(spec):
                trace.append(
                    {
                        "id": spec.id,
                        "name": spec.name,
                        "status": HandlerTraceStatus.DISABLED.value,
                    }
                )
                continue
            if spec.type != HandlerType.BUILTIN.value:
                logger.debug("跳过 external handler: %s", spec.id)
                trace.append(
                    {
                        "id": spec.id,
                        "name": spec.name,
                        "status": HandlerTraceStatus.SKIPPED.value,
                        "reason": "external handler",
                    }
                )
                continue
            try:
                if spec.name == "ai_filter":
                    allowed, reason = await self._run_ai_filter(
                        result,
                        spec.config,
                        session_id=session_id,
                    )
                    trace.append(
                        {
                            "id": spec.id,
                            "name": spec.name,
                            "status": HandlerTraceStatus.OK.value,
                            "allow": allowed,
                            "reason": reason,
                            "scope": str(
                                spec.config.get("input_scope")
                                or AiFilterInputScope.TEXT.value
                            ),
                        }
                    )
                    if not allowed:
                        return HandlerProcessResult(
                            entry=result,
                            allow=False,
                            reason=reason,
                            trace=tuple(trace),
                        )
                elif spec.name == "ai_transform":
                    transform_result = await self._run_ai_transform(
                        result,
                        spec.config,
                        session_id=session_id,
                        event=event,
                        target_session=target_session,
                        platform_name=platform_name,
                        user_id=user_id
                        or getattr(user, "id", "")
                        or subscription.user_id,
                    )
                    result = transform_result["entry"]
                    trace.append(
                        {
                            "id": spec.id,
                            "name": spec.name,
                            "status": HandlerTraceStatus.OK.value,
                            **transform_result["trace"],
                        }
                    )
                else:
                    logger.debug("未知内置 handler，已跳过: %s", spec.name)
                    trace.append(
                        {
                            "id": spec.id,
                            "name": spec.name,
                            "status": HandlerTraceStatus.SKIPPED.value,
                            "reason": "unknown builtin handler",
                        }
                    )
            except Exception as exc:
                logger.warning(
                    "handler 执行失败，已回退上一步结果: %s (%s)",
                    spec.id,
                    exc,
                )
                trace.append(
                    {
                        "id": spec.id,
                        "name": spec.name,
                        "status": HandlerTraceStatus.ERROR.value,
                        "reason": str(exc),
                    }
                )
        return HandlerProcessResult(entry=result, trace=tuple(trace))

    async def _run_ai_transform(
        self,
        entry: EntryContentContext,
        config: dict[str, Any],
        *,
        session_id: str | None = None,
        event: AstrMessageEvent | Any | None = None,
        target_session: str | None = None,
        platform_name: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        prompt = str((config or {}).get("prompt") or "").strip()
        if not prompt or self._context is None:
            return {
                "entry": entry,
                "trace": {
                    "scope": str(
                        (config or {}).get("scope") or AiTransformScope.PLAINTEXT.value
                    ),
                    "steps_used": 0,
                    "fallback": True,
                    "fallback_reason": "missing prompt or context",
                },
            }

        provider = self._resolve_provider(session_id=session_id)
        if provider is None:
            logger.warning("ai_transform 跳过：当前没有可用的对话模型 provider")
            return {
                "entry": entry,
                "trace": {
                    "scope": str(
                        (config or {}).get("scope") or AiTransformScope.PLAINTEXT.value
                    ),
                    "steps_used": 0,
                    "fallback": True,
                    "fallback_reason": "provider unavailable",
                },
            }

        transform_scope = self._normalize_transform_scope((config or {}).get("scope"))
        agent_event = self._resolve_agent_event(
            event=event,
            session_id=session_id,
            target_session=target_session,
            platform_name=platform_name,
            user_id=user_id,
        )
        provider_id = self._resolve_chat_provider_id(
            provider=provider,
            session_id=session_id,
        )
        if not provider_id:
            raise ValueError("ai_transform 无法解析当前对话 provider_id")

        if transform_scope == AiTransformScope.XML.value:
            return await self._run_ai_transform_xml(
                entry=entry,
                prompt=prompt,
                provider_id=provider_id,
                event=agent_event,
            )
        return await self._run_ai_transform_plaintext(
            entry=entry,
            prompt=prompt,
            provider_id=provider_id,
            event=agent_event,
        )

    async def _run_ai_transform_plaintext(
        self,
        *,
        entry: EntryContentContext,
        prompt: str,
        provider_id: str,
        event: AstrMessageEvent | Any,
    ) -> dict[str, Any]:
        source_payload = {
            "title": entry.title,
            "summary": entry.summary,
            "content": entry.content,
            "link": entry.link,
            "author": entry.author,
            "feed_title": entry.feed_title,
            "feed_link": entry.feed_link,
            "media_urls": list(entry.media_urls),
        }
        request_prompt = (
            "你是 RSS 内容改写 agent。请根据用户要求改写 RSS 条目的文本字段。"
            "只返回 JSON 对象，不要输出解释、Markdown 或代码块。"
            '\n只允许返回这些字段中的任意子集：{"title":"...","summary":"...","content":"..."}'
            "\n缺省字段表示不改动；空字符串也视为不改动。"
            f"\n用户要求:\n{prompt}"
            f"\n\n条目数据:\n{json.dumps(source_payload, ensure_ascii=False)}"
        )
        response = await self._context.tool_loop_agent(
            event=event,
            chat_provider_id=provider_id,
            prompt=request_prompt,
            tools=ToolSet(),
            contexts=[],
            system_prompt=self._resolve_system_prompt(),
            max_steps=1,
            tool_call_timeout=60,
            stream=False,
        )
        payload = str(getattr(response, "completion_text", "") or "").strip()
        parsed = self._parse_transform_json(
            payload, required_fields={"title", "summary", "content"}
        )
        title = str(parsed.get("title") or entry.title).strip()
        summary = str(parsed.get("summary") or entry.summary).strip()
        content = str(parsed.get("content") or entry.content).strip()
        return {
            "entry": replace(
                entry,
                title=title or entry.title,
                summary=summary or entry.summary,
                content=content or entry.content,
            ),
            "trace": {
                "scope": AiTransformScope.PLAINTEXT.value,
                "steps_used": 1,
                "fallback": False,
            },
        }

    async def _run_ai_transform_xml(
        self,
        *,
        entry: EntryContentContext,
        prompt: str,
        provider_id: str,
        event: AstrMessageEvent | Any,
    ) -> dict[str, Any]:
        source_payload = {
            "raw_xml": entry.raw_xml,
            "title": entry.title,
            "link": entry.link,
            "author": entry.author,
            "feed_title": entry.feed_title,
            "feed_link": entry.feed_link,
        }
        system_prompt = "\n\n".join(
            part
            for part in [
                self._resolve_system_prompt(),
                (
                    "你是 RSS XML 改写 agent。你必须遵守 RSS/Atom item 或 entry 片段规范。"
                    "只返回 JSON 对象，且必须包含 raw_xml 字段。"
                    "raw_xml 只能是单个 item/entry 级 XML 片段，不允许 DOCTYPE/ENTITY，"
                    "不要输出解释文本、Markdown 或代码块包裹。"
                ),
            ]
            if part
        )
        request_prompt = (
            "请按用户要求改写下面的 RSS item/entry XML。必要时先调用 XML 校验工具自检并修正。"
            '\n最终只返回 JSON，例如 {"raw_xml":"<item>...</item>"}。'
            f"\n用户要求:\n{prompt}"
            f"\n\n条目数据:\n{json.dumps(source_payload, ensure_ascii=False)}"
        )
        response = await self._context.tool_loop_agent(
            event=event,
            chat_provider_id=provider_id,
            prompt=request_prompt,
            tools=ToolSet([XmlValidationTool()]),
            contexts=[],
            system_prompt=system_prompt,
            max_steps=6,
            tool_call_timeout=60,
            stream=False,
        )
        payload = str(getattr(response, "completion_text", "") or "").strip()
        parsed = self._parse_transform_json(payload, required_fields={"raw_xml"})
        transformed_xml = str(parsed.get("raw_xml") or "").strip()
        if not transformed_xml:
            raise ValueError("ai_transform(xml) 输出缺少 raw_xml")

        reparsed_entry = await self._reparse_transformed_xml(
            entry=entry, raw_xml=transformed_xml
        )
        steps_used = max(
            len(getattr(response, "tools_call_name", []) or []) + 1,
            1,
        )
        return {
            "entry": reparsed_entry,
            "trace": {
                "scope": AiTransformScope.XML.value,
                "steps_used": steps_used,
                "fallback": False,
            },
        }

    async def _run_ai_filter(
        self,
        entry: EntryContentContext,
        config: dict[str, Any],
        *,
        session_id: str | None = None,
    ) -> tuple[bool, str]:
        prompt = str((config or {}).get("prompt") or "").strip()
        if not prompt or self._context is None:
            return True, "ai_filter 未配置 prompt 或 provider 上下文"

        provider = self._resolve_provider(session_id=session_id)
        if provider is None:
            logger.warning("ai_filter 放行：当前没有可用的对话模型 provider")
            return True, "provider unavailable"

        input_scope = self._normalize_filter_scope((config or {}).get("input_scope"))
        source_payload = {
            "title": entry.title,
            "summary": entry.summary,
            "content": entry.content,
            "link": entry.link,
            "author": entry.author,
            "feed_title": entry.feed_title,
            "feed_link": entry.feed_link,
        }
        if input_scope in {
            AiFilterInputScope.RAW_XML.value,
            AiFilterInputScope.BOTH.value,
        }:
            source_payload["raw_xml"] = entry.raw_xml
        if input_scope == AiFilterInputScope.RAW_XML.value:
            source_payload = {
                "title": entry.title,
                "link": entry.link,
                "feed_title": entry.feed_title,
                "raw_xml": entry.raw_xml,
            }

        request_prompt = (
            "你是 RSS 内容过滤器。根据用户要求判断条目是否允许推送，只返回 JSON。"
            '\n返回格式: {"allow":true,"reason":"..."}'
            "\nallow=false 表示跳过推送；reason 用一句话说明原因。"
            f"\n用户要求:\n{prompt}"
            f"\n\n条目数据:\n{json.dumps(source_payload, ensure_ascii=False)}"
        )
        response = await provider.text_chat(
            prompt=request_prompt,
            session_id=session_id or "rsshub-handlers",
            contexts=[],
            persist=False,
            system_prompt=self._resolve_system_prompt(),
        )
        payload = str(getattr(response, "completion_text", "") or "").strip()
        if not payload:
            logger.warning("ai_filter 放行：AI 返回为空")
            return True, "empty response"
        try:
            parsed = json.loads(payload)
        except Exception as exc:
            logger.warning("ai_filter 放行：AI 返回非法 JSON: %s", exc)
            return True, "invalid json"
        if not isinstance(parsed, dict) or not isinstance(parsed.get("allow"), bool):
            logger.warning("ai_filter 放行：AI 返回结构无效")
            return True, "invalid schema"
        reason = str(parsed.get("reason") or "").strip()
        try:
            reason_max_length = int((config or {}).get("reason_max_length") or 120)
        except (TypeError, ValueError):
            reason_max_length = 120
        if reason_max_length > 0 and len(reason) > reason_max_length:
            reason = reason[:reason_max_length].rstrip()
        return bool(parsed["allow"]), reason

    def _normalize_filter_scope(self, value: Any) -> str:
        normalized = str(value or "").strip()
        if normalized not in {item.value for item in AiFilterInputScope}:
            return AiFilterInputScope.TEXT.value
        return normalized

    def _normalize_transform_scope(self, value: Any) -> str:
        normalized = str(value or "").strip()
        if normalized not in {item.value for item in AiTransformScope}:
            return AiTransformScope.PLAINTEXT.value
        return normalized

    def _parse_transform_json(
        self,
        payload: str,
        *,
        required_fields: set[str],
    ) -> dict[str, Any]:
        if not payload:
            raise ValueError("ai_transform 输出为空")
        try:
            parsed = json.loads(payload)
        except Exception as exc:
            raise ValueError(f"ai_transform 输出不是合法 JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("ai_transform 输出必须是 JSON 对象")
        allowed_fields = {"title", "summary", "content", "raw_xml"}
        invalid_keys = [key for key in parsed.keys() if key not in allowed_fields]
        if invalid_keys:
            raise ValueError(
                f"ai_transform 输出包含非法字段: {', '.join(invalid_keys)}"
            )
        if required_fields and not any(
            str(parsed.get(field) or "").strip() for field in required_fields
        ):
            raise ValueError("ai_transform 输出缺少有效结果")
        return parsed

    async def _reparse_transformed_xml(
        self,
        *,
        entry: EntryContentContext,
        raw_xml: str,
    ) -> EntryContentContext:
        from .agent_xml_push_service import (
            _collect_xml_media,
            _parse_xml_root,
            _validate_xml_input,
        )

        normalized_xml = _validate_xml_input(raw_xml)
        root, body_xml = _parse_xml_root(normalized_xml)
        parsed = await HTMLParser(
            body_xml, feed_link=entry.feed_link or entry.link or ""
        ).parse()
        from .feed_polling_service import FeedPollingService

        plain_body = FeedPollingService._remove_media_placeholders(
            parsed.html_tree.get_plain().strip()
        )
        content = await FeedPollingService._format_dispatch_content_async(
            title=str(root.findtext("title") or entry.title or "").strip(),
            body=plain_body,
            link=str(root.findtext("link") or entry.link or "").strip(),
            feed_title=entry.feed_title,
            feed_link=entry.feed_link,
            author=str(root.findtext("author") or entry.author or "").strip(),
        )
        media_items = FeedPollingService._media_items_from_parsed(parsed.media)
        media_urls = [url for _media_type, url in media_items]
        media_urls.extend(_collect_xml_media(root))
        deduped_media_urls = tuple(dict.fromkeys(media_urls))
        return replace(
            entry,
            title=str(root.findtext("title") or entry.title or "").strip()
            or entry.title,
            summary=plain_body or entry.summary,
            content=content or entry.content,
            link=str(root.findtext("link") or entry.link or "").strip() or entry.link,
            author=str(root.findtext("author") or entry.author or "").strip()
            or entry.author,
            raw_xml=normalized_xml,
            media_urls=deduped_media_urls,
            media_items=tuple(media_items),
            layout=tuple(parsed.layout),
        )

    def _resolve_agent_event(
        self,
        *,
        event: AstrMessageEvent | Any | None,
        session_id: str | None,
        target_session: str | None,
        platform_name: str | None,
        user_id: str | None,
    ) -> AstrMessageEvent | Any:
        if event is not None:
            return event
        resolved_target = (
            str(target_session or "").strip()
            or str(session_id or "").strip()
            or "rsshub:FriendMessage:rsshub-handlers"
        )
        resolved_platform = (
            str(platform_name or "").strip()
            or self._platform_name_from_session(resolved_target)
            or "rsshub"
        )
        return _SyntheticHandlerEvent(
            unified_msg_origin=resolved_target,
            platform_name=resolved_platform,
            sender_id=str(user_id or "rsshub-handler"),
        )

    def _platform_name_from_session(self, target_session: str) -> str:
        parts = str(target_session or "").split(":", 2)
        return parts[0].strip() if parts else ""

    def _resolve_chat_provider_id(
        self,
        *,
        provider: Provider,
        session_id: str | None,
    ) -> str:
        provider_id = self._settings.ai_provider_id.strip()
        if provider_id:
            return provider_id
        meta = getattr(provider, "meta", None)
        if callable(meta):
            try:
                return str(meta().id or "").strip()
            except Exception:
                return ""
        return ""

    def _resolve_provider(self, *, session_id: str | None = None) -> Provider | None:
        provider = None
        provider_id = self._settings.ai_provider_id.strip()
        if provider_id:
            getter_by_id = getattr(self._context, "get_provider_by_id", None)
            if getter_by_id is not None:
                provider = getter_by_id(provider_id)
        if provider is None:
            getter = getattr(self._context, "get_using_provider", None)
            if getter is None:
                return None
            # 修复：非聊天路径（Web 测试推送/自动轮询）下 session_id 对应的会话
            # 无活跃用户，getter(session_id) 返回 None；需回退到全局默认 provider，
            # 否则 AI filter/transform 在 Web/自动推送路径静默跳过、原文直发。
            provider = getter(session_id) if session_id else None
            if provider is None:
                provider = getter()  # 全局默认 provider
        return provider if callable(getattr(provider, "text_chat", None)) else None

    def _resolve_system_prompt(self) -> str:
        persona_id = self._settings.ai_persona_id.strip()
        if not persona_id:
            return ""
        persona_manager = getattr(self._context, "persona_manager", None)
        getter = getattr(persona_manager, "get_persona_v3_by_id", None)
        if getter is None:
            logger.warning("内容处理器人格未生效：persona_manager 不可用")
            return ""
        persona = getter(persona_id)
        if not persona:
            logger.warning("内容处理器人格未生效：找不到 persona_id=%s", persona_id)
            return ""
        prompt = getattr(persona, "system_prompt", None)
        if prompt is None and isinstance(persona, dict):
            prompt = persona.get("prompt") or persona.get("system_prompt")
        return str(prompt or "").strip()
