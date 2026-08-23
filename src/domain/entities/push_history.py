"""
推送历史领域实体

记录每次推送的完整信息和状态，用于重试机制和推送统计。
不包含任何 ORM 或持久化逻辑。
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

MAX_FAIL_REASON_LENGTH = 512


def normalize_fail_reason(
    reason: str | None, *, max_length: int = MAX_FAIL_REASON_LENGTH
) -> str | None:
    """Trim failure reasons to the persisted model limit."""
    if reason is None:
        return None
    normalized = str(reason).strip()
    if not normalized:
        return None
    if len(normalized) <= max_length:
        return normalized
    if max_length <= 3:
        return normalized[:max_length]
    return normalized[: max_length - 3] + "..."


def normalize_display_fail_reason(
    reason: str | None, *, max_length: int = MAX_FAIL_REASON_LENGTH
) -> str | None:
    """Normalize a failure reason for UI display and storage."""
    return normalize_fail_reason(reason, max_length=max_length)


def normalize_fail_reason_for_status(
    status: str | None,
    reason: str | None,
    *,
    max_length: int = MAX_FAIL_REASON_LENGTH,
) -> str | None:
    """Normalize stored/displayed fail reason according to push status."""
    if status in {"failed", "stopped", "retrying", "skipped", "discarded"}:
        return normalize_display_fail_reason(reason, max_length=max_length)
    return None


class PushHistory(BaseModel):
    """
    推送历史领域实体

    记录每次推送的完整信息和状态，用于重试机制和推送统计。
    """

    id: int | None = Field(default=None, description="数据库ID")
    sub_id: int | None = Field(default=None, description="订阅ID")
    batch_id: int | None = Field(default=None, description="投递批次 ID")
    bundle_id: int | None = Field(default=None, description="Bundle ID")
    user_id: str = Field(..., description="用户ID")
    feed_id: int | None = Field(default=None, description="FeedID")
    source_type: str = Field(
        default="feed", max_length=16, description="来源类型: feed/agent"
    )
    source_key: str | None = Field(
        default=None, max_length=255, description="来源跟踪键"
    )

    content: str = Field(default="", description="格式化后的消息内容")
    raw_xml: str | None = Field(default=None, description="XML 推送原始内容")
    media_urls: list[str] | None = Field(default=None, description="媒体URL列表")
    handler_trace: list[dict[str, Any]] | None = Field(
        default=None,
        description="内容 handler 执行摘要",
    )
    output_kind: str = Field(
        default="standard",
        max_length=16,
        description="批次输出类型: card/standard",
    )
    output_order: int = Field(default=0, ge=0, description="批次内输出顺序")
    source_context: dict[str, Any] | None = Field(
        default=None,
        description="来源不可变快照",
    )

    entry_title: str = Field(default="", max_length=1024, description="条目标题")
    entry_link: str = Field(default="", max_length=4096, description="条目链接")
    entry_guid: str | None = Field(default=None, max_length=512, description="条目GUID")

    feed_title: str = Field(default="", max_length=1024, description="Feed标题")
    feed_link: str = Field(default="", max_length=4096, description="Feed链接")

    platform_name: str | None = Field(
        default=None, max_length=64, description="平台名称"
    )
    target_session: str | None = Field(
        default=None, max_length=255, description="目标会话"
    )

    status: str | None = Field(
        default=None,
        max_length=16,
        description=(
            "状态: waiting/pending/retrying/success/failed/stopped/skipped/discarded"
        ),
    )
    retry_count: int = Field(default=0, description="重试次数")
    max_retries: int = Field(default=3, description="最大重试次数")
    fail_reason: str | None = Field(
        default=None, max_length=512, description="失败原因"
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="创建时间"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="更新时间"
    )
    completed_at: datetime | None = Field(default=None, description="完成时间")

    def can_retry(self) -> bool:
        """检查是否可以重试"""
        return self.status == "failed" and self.retry_count < self.max_retries

    def is_agent_source(self) -> bool:
        """检查是否为 Agent 来源推送。"""
        return self.source_type == "agent"

    def is_feed_source(self) -> bool:
        """检查是否为 Feed 来源推送。"""
        return not self.is_agent_source()

    def mark_success(self) -> "PushHistory":
        """标记推送成功"""
        self.status = "success"
        self.fail_reason = None
        self.completed_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
        return self

    def record_first_failure(self, reason: str | None = None) -> "PushHistory":
        """记录首次失败（不增加重试计数）"""
        self.status = "failed"
        self.fail_reason = normalize_display_fail_reason(reason)
        self.updated_at = datetime.now(timezone.utc)
        return self

    def record_retry_failure(self, reason: str | None = None) -> "PushHistory":
        """记录重试失败（增加重试计数）"""
        self.status = "failed"
        self.retry_count += 1
        self.fail_reason = normalize_display_fail_reason(reason)
        self.updated_at = datetime.now(timezone.utc)
        return self

    def mark_retrying(self) -> "PushHistory":
        """标记为正在重试（原子更新用）"""
        self.status = "retrying"
        self.updated_at = datetime.now(timezone.utc)
        return self

    def mark_failed(self, reason: str | None = None) -> "PushHistory":
        """标记推送失败（保持向后兼容，调用 record_first_failure）"""
        return self.record_first_failure(reason)

    def mark_stopped(self, reason: str | None = None) -> "PushHistory":
        """标记推送被人工停止（不参与重试）。"""
        self.status = "stopped"
        self.completed_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
        self.fail_reason = normalize_display_fail_reason(reason)
        return self

    def mark_skipped(self, reason: str | None = None) -> "PushHistory":
        """标记被内容 handler 跳过（不参与重试）。"""
        self.status = "skipped"
        self.completed_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
        self.max_retries = 0
        self.fail_reason = normalize_display_fail_reason(reason)
        return self

    def is_pending(self) -> bool:
        """检查是否处于待推送状态"""
        return self.status == "pending"

    def is_success(self) -> bool:
        """检查是否推送成功"""
        return self.status == "success"

    def is_failed(self) -> bool:
        """检查是否推送失败"""
        return self.status == "failed"
