"""执行 Bundle 批次中已经固化的 card/standard 输出。"""

from __future__ import annotations

from typing import Any

from ...domain.entities.content_types import LayoutFragment
from ...domain.entities.push_history import PushHistory
from ...infrastructure.templates.rendering import CardTemplateSnapshot
from ..ports.message_sender import SendResult
from .card_renderer import CardRenderer
from .notification_dispatcher import NotificationDispatcher, SendTarget


class BundleOutputExecutor:
    """只复放批次快照，不重新读取 Bundle 配置或运行 handler。"""

    def __init__(
        self,
        *,
        notification_dispatcher: NotificationDispatcher,
        card_renderer: CardRenderer,
    ) -> None:
        self._notification_dispatcher = notification_dispatcher
        self._card_renderer = card_renderer

    async def execute(self, history: PushHistory) -> SendResult:
        if history.output_kind == "card":
            return await self._execute_card(history)
        if history.output_kind != "standard":
            raise ValueError(f"不支持的 Bundle 输出类型: {history.output_kind}")
        return await self._execute_standard(history)

    async def _execute_standard(self, history: PushHistory) -> SendResult:
        source_context = history.source_context or {}
        send = source_context.get("send")
        if not isinstance(send, dict):
            raise TypeError("standard 输出缺少固化发送参数")
        result = await self._notification_dispatcher.send_to_session(
            target=self._target(history),
            content=str(send.get("content") or ""),
            media_urls=self._string_list(send.get("media_urls")),
            media_items=self._media_items(send.get("media_items")),
            layout=self._layout(send.get("layout")),
            job_description=f"batch={history.batch_id}, history={history.id}",
            channel_title=history.feed_title,
            channel_link=history.feed_link,
            feed_id=None,
            sub_id=None,
            send_mode=send.get("send_mode"),
            style=int(send.get("style") or 0),
        )
        return self._send_result(result)

    async def _execute_card(self, history: PushHistory) -> SendResult:
        source_context = history.source_context or {}
        raw_template = source_context.get("template_snapshot")
        raw_document = source_context.get("document_snapshot")
        raw_bundle = source_context.get("bundle")
        raw_feeds = source_context.get("feeds")
        if not isinstance(raw_template, dict) or not isinstance(raw_document, dict):
            raise TypeError("card 输出缺少固化模板或文档快照")
        if not isinstance(raw_bundle, dict) or not isinstance(raw_feeds, list):
            raise TypeError("Bundle card 输出缺少 Bundle 或 Feed 上下文")
        rendered_at = raw_document.get("rendered_at")
        if not isinstance(rendered_at, str) or not rendered_at.strip():
            raise ValueError("card 输出缺少固化 rendered_at")
        if history.batch_id is None or history.bundle_id is None:
            raise ValueError("card 输出缺少批次或 Bundle 身份")

        snapshot = CardTemplateSnapshot.model_validate(raw_template)
        context = {
            "source": {"type": "bundle", "owner_id": history.bundle_id},
            "bundle": {
                "id": raw_bundle.get("id"),
                "name": raw_bundle.get("name") or history.feed_title,
            },
            "feeds": raw_feeds,
            "entries": raw_document.get("entries") or [],
            "document": raw_document.get("document") or {"text": "", "rss_xml": ""},
            "meta": {
                "batch_id": history.batch_id,
                "rendered_at": rendered_at,
            },
        }
        rendered = await self._card_renderer.render(history, snapshot, context)
        result = await self._notification_dispatcher.send_to_session(
            target=self._target(history),
            content="",
            media_urls=None,
            media_items=[("image", rendered.png_path.as_uri())],
            job_description=f"batch={history.batch_id}, history={history.id}, card",
            channel_title=history.feed_title,
            channel_link=history.feed_link,
            feed_id=None,
            sub_id=None,
        )
        return self._send_result(result)

    @staticmethod
    def _target(history: PushHistory) -> SendTarget:
        return SendTarget(
            user_id=history.user_id,
            platform_name=history.platform_name,
            target_session=history.target_session,
            sub_id=None,
        )

    @staticmethod
    def _send_result(result: dict[str, Any]) -> SendResult:
        return SendResult(
            ok=bool(result.get("ok")),
            cancelled=bool(result.get("cancelled")),
            detail=str(result.get("error") or ""),
        )

    @staticmethod
    def _string_list(value: Any) -> list[str] | None:
        if not isinstance(value, list):
            return None
        return [str(item) for item in value]

    @staticmethod
    def _media_items(value: Any) -> list[tuple[str, str]] | None:
        if not isinstance(value, list):
            return None
        items: list[tuple[str, str]] = []
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                items.append((str(item[0]), str(item[1])))
        return items or None

    @staticmethod
    def _layout(value: Any) -> list[LayoutFragment] | None:
        if not isinstance(value, list):
            return None
        return [LayoutFragment.model_validate(item) for item in value] or None
