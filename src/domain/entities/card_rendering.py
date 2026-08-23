"""卡片模板公开的稳定 JSON 上下文契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _CardContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CardSourceContext(_CardContextModel):
    """卡片批次来源。"""

    type: Literal["feed", "bundle"]
    owner_id: int = Field(gt=0)


class CardFeedContext(_CardContextModel):
    """模板可见的 Feed 摘要。"""

    id: int = Field(gt=0)
    title: str = ""
    link: str = ""


class CardBundleContext(_CardContextModel):
    """模板可见的 Bundle 摘要。"""

    id: int = Field(gt=0)
    name: str = ""


class CardBundleFeedContext(CardFeedContext):
    """Bundle 中按 position 排序的 Feed 摘要。"""

    position: int = Field(ge=0)


class CardEntryContext(_CardContextModel):
    """一条 post-handler 条目。"""

    item_key: str = Field(min_length=1)
    feed_id: int = Field(gt=0)
    title: str = ""
    link: str = ""
    author: str = ""
    published: str | None = None
    updated: str | None = None
    summary: str = ""
    content_html: str = ""
    tags: list[str] = Field(default_factory=list)
    media_items: list[dict[str, Any]] = Field(default_factory=list)


class CardDocumentContext(_CardContextModel):
    """handler 后的标准文本与聚合 RSS XML。"""

    text: str = ""
    rss_xml: str = ""


class CardRenderMeta(_CardContextModel):
    """一次渲染的不可变批次元信息。"""

    batch_id: int = Field(gt=0)
    rendered_at: str = Field(min_length=1)


class CardRenderContext(_CardContextModel):
    """CardTemplateService 接受的最小稳定上下文。"""

    source: CardSourceContext
    feed: CardFeedContext | None = None
    bundle: CardBundleContext | None = None
    feeds: list[CardBundleFeedContext] = Field(default_factory=list)
    entries: list[CardEntryContext] = Field(default_factory=list)
    document: CardDocumentContext
    meta: CardRenderMeta

    @model_validator(mode="after")
    def _validate_source_shape(self) -> CardRenderContext:
        if self.source.type == "feed":
            if self.feed is None or self.bundle is not None or self.feeds:
                raise ValueError("Feed 上下文必须包含 feed，且不能包含 bundle/feeds")
        elif self.bundle is None or self.feed is not None:
            raise ValueError("Bundle 上下文必须包含 bundle，且不能包含 feed")
        return self
