"""卡片模板 metadata 领域契约。"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..value_objects.feed_url import FeedUrl

TemplateTarget = Literal["feed", "bundle"]
TemplateOwnerType = Literal["subscription", "bundle"]

_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_TEMPLATE_ID_PATTERN = re.compile(r"^astrbot_plugin_rsshub_card_[a-z0-9][a-z0-9_-]*$")


def is_valid_card_template_id(value: str) -> bool:
    """判断字符串是否符合卡片模板 ID 契约。"""
    return _TEMPLATE_ID_PATTERN.fullmatch(value) is not None


class CardTemplateMetadata(BaseModel):
    """描述一个可安装卡片模板包的公开元数据。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ...,
        pattern=_TEMPLATE_ID_PATTERN.pattern,
        description="模板 ID",
    )
    name: str = Field(..., description="模板名称")
    version: str = Field(..., description="SemVer 版本")
    author: str = Field(..., description="模板作者")
    description: str = Field(..., description="模板说明")
    repository: str = Field(..., description="模板仓库")
    targets: list[TemplateTarget] = Field(
        ...,
        min_length=1,
        description="支持的 owner 类型",
    )
    feed_patterns: list[str] = Field(
        default_factory=list,
        description="适配 Feed URL 的正则表达式",
    )

    @field_validator("name", "author", "description", "repository")
    @classmethod
    def _normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("required metadata text must not be blank")
        return normalized

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if _SEMVER_PATTERN.fullmatch(value) is None:
            raise ValueError("version must be valid SemVer")
        return value

    @field_validator("feed_patterns")
    @classmethod
    def _validate_feed_patterns(cls, value: list[str]) -> list[str]:
        for pattern in value:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(
                    f"feed_patterns contains invalid regex {pattern!r}: {exc}"
                ) from exc
        return value

    def matches_owner(
        self,
        *,
        owner_type: TemplateOwnerType,
        feed_urls: Sequence[str],
    ) -> bool:
        """判断模板是否适配 owner 类型及其全部 Feed。"""
        if owner_type not in {"subscription", "bundle"}:
            raise ValueError(f"unsupported owner_type: {owner_type}")
        target: TemplateTarget = "feed" if owner_type == "subscription" else "bundle"
        if target not in self.targets:
            return False

        normalized_urls = [FeedUrl(url=url).normalized() for url in feed_urls]
        if not normalized_urls or (
            owner_type == "subscription" and len(normalized_urls) != 1
        ):
            return False
        if not self.feed_patterns:
            return True

        patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.feed_patterns
        ]
        return all(
            any(pattern.search(url) is not None for pattern in patterns)
            for url in normalized_urls
        )
