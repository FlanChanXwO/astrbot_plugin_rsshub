"""执行 Subscription 批次中已经固化的输出。"""

from __future__ import annotations

from typing import Any

from ...domain.entities.content_types import LayoutFragment
from ...domain.entities.push_history import PushHistory
from ...infrastructure.templates.rendering import CardTemplateSnapshot
from ..ports.message_sender import SendResult
from .card_renderer import CardRenderer
from .notification_dispatcher import NotificationDispatcher, SendTarget


class SubscriptionOutputExecutor:
    """复放不可变发送参数，不重新解析配置或运行 handler。"""

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
            raise ValueError(f"不支持的 Subscription 输出类型: {history.output_kind}")
        source_context = history.source_context or {}
        send = source_context.get("send")
        if not isinstance(send, dict):
            raise TypeError("standard 输出缺少固化发送参数")
        media_items = self._media_items(send.get("media_items"))
        result = await self._notification_dispatcher.send_to_session(
            target=SendTarget(
                user_id=history.user_id,
                platform_name=history.platform_name,
                target_session=history.target_session,
                sub_id=history.sub_id,
            ),
            content=str(send.get("content") or ""),
            media_urls=self._string_list(send.get("media_urls")),
            media_items=media_items,
            layout=self._layout(send.get("layout")),
            job_description=f"batch={history.batch_id}, history={history.id}",
            channel_title=history.feed_title,
            channel_link=history.feed_link,
            entry_title=history.entry_title,
            entry_link=history.entry_link,
            feed_id=history.feed_id,
            sub_id=history.sub_id,
            send_mode=send.get("send_mode"),
            style=int(send.get("style") or 0),
        )
        return SendResult(
            ok=bool(result.get("ok")),
            cancelled=bool(result.get("cancelled")),
            detail=str(result.get("error") or ""),
        )

    async def _execute_card(self, history: PushHistory) -> SendResult:
        source_context = history.source_context or {}
        raw_template = source_context.get("template_snapshot")
        raw_document = source_context.get("document_snapshot")
        if not isinstance(raw_template, dict) or not isinstance(raw_document, dict):
            raise TypeError("card 输出缺少固化模板或文档快照")
        rendered_at = raw_document.get("rendered_at")
        if not isinstance(rendered_at, str) or not rendered_at.strip():
            raise ValueError("card 输出缺少固化 rendered_at")
        if (
            history.batch_id is None
            or history.sub_id is None
            or history.feed_id is None
        ):
            raise ValueError("card 输出缺少批次、Subscription 或 Feed 身份")
        snapshot = CardTemplateSnapshot.model_validate(raw_template)
        context = {
            "source": {"type": "feed", "owner_id": history.sub_id},
            "feed": {
                "id": history.feed_id,
                "title": history.feed_title,
                "link": history.feed_link,
            },
            "entries": raw_document.get("entries") or [],
            "document": raw_document.get("document") or {"text": "", "rss_xml": ""},
            "meta": {
                "batch_id": history.batch_id,
                "rendered_at": rendered_at,
            },
        }
        rendered = await self._card_renderer.render(history, snapshot, context)
        result = await self._notification_dispatcher.send_to_session(
            target=SendTarget(
                user_id=history.user_id,
                platform_name=history.platform_name,
                target_session=history.target_session,
                sub_id=history.sub_id,
            ),
            content="",
            media_urls=None,
            media_items=[("image", rendered.png_path.as_uri())],
            job_description=f"batch={history.batch_id}, history={history.id}, card",
            channel_title=history.feed_title,
            channel_link=history.feed_link,
            feed_id=history.feed_id,
            sub_id=history.sub_id,
        )
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
