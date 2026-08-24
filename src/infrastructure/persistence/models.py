"""ORM 模型定义模块

定义数据库表结构对应的 SQLModel 模型。
所有模型继承自 RSSHubBaseModel，共享同一个 metadata。

注意:
    此模块仅包含 ORM 模型定义和数据结构，不包含业务逻辑方法。
    业务逻辑应放在领域层 (domain/entities/) 或仓库实现中。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, Index, UniqueConstraint, text
from sqlmodel import Field

from ...shared.constants import INHERIT_VALUE
from .database import RSSHubBaseModel

EFFECTIVE_OPTION_KEYS = (
    "send_mode",
    "length_limit",
    "display_author",
    "display_via",
    "display_title",
    "display_entry_tags",
    "style",
    "display_media",
)


# ============================================================================
# ORM 模型
# ============================================================================


class UserORM(RSSHubBaseModel, table=True):
    """用户 ORM 模型，映射 rsshub_user 表。"""

    __tablename__ = "rsshub_user"

    id: str = Field(default=None, primary_key=True, description="用户ID")
    state: int = Field(default=1, description="用户状态: -1=已封禁, 1=用户")

    interval: int = Field(default=INHERIT_VALUE, description="监控间隔(分钟)")
    notify: int = Field(default=INHERIT_VALUE, description="是否通知: 0=禁用, 1=启用")
    send_mode: int = Field(
        default=INHERIT_VALUE,
        description="发送模式: -1=仅链接, 0=自动, 1=直接发送",
    )
    handlers: str = Field(default="[]", description="内容处理 handlers JSON")
    length_limit: int = Field(default=INHERIT_VALUE, description="长度限制")
    display_author: int = Field(
        default=INHERIT_VALUE, description="显示作者: -1=禁用, 0=自动, 1=强制"
    )
    display_via: int = Field(
        default=INHERIT_VALUE,
        description="显示来源: -2=完全禁用, -1=仅链接, 0=自动, 1=强制",
    )
    display_title: int = Field(
        default=INHERIT_VALUE, description="显示标题: -1=禁用, 0=自动, 1=强制"
    )
    display_entry_tags: int = Field(default=INHERIT_VALUE, description="显示标签")
    style: int = Field(
        default=INHERIT_VALUE,
        description="推送排版策略: 0=自动, 1=RSSRT, 2=原始顺序",
    )
    display_media: int = Field(
        default=INHERIT_VALUE, description="显示媒体: -1=禁用, 0=启用"
    )
    default_target_session: str | None = Field(
        default=None,
        max_length=255,
        description="默认推送目标会话(unified_msg_origin)",
    )
    needs_binding_notice: int = Field(default=0, description="是否需要提示绑定推送目标")

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="创建时间",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)},
        description="更新时间",
    )


class FeedORM(RSSHubBaseModel, table=True):
    """Feed ORM 模型，映射 rsshub_feed 表。"""

    __tablename__ = "rsshub_feed"

    id: int | None = Field(default=None, primary_key=True)
    state: int = Field(default=1, description="Feed状态: 0=停用, 1=启用")
    link: str = Field(max_length=4096, unique=True, description="Feed链接")
    title: str = Field(max_length=1024, description="Feed标题")
    entry_hashes: list[Any] | None = Field(
        default=None, sa_column=Column(JSON), description="条目哈希历史"
    )
    etag: str | None = Field(default=None, max_length=128, description="ETag")
    last_modified: datetime | None = Field(default=None, description="最后修改时间")

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="创建时间",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)},
        description="更新时间",
    )


class SubORM(RSSHubBaseModel, table=True):
    """订阅 ORM 模型，映射 rsshub_sub 表。"""

    __tablename__ = "rsshub_sub"

    id: int | None = Field(default=None, primary_key=True)
    state: int = Field(default=1, description="订阅状态: 0=停用, 1=启用")

    user_id: str = Field(foreign_key="rsshub_user.id", description="用户ID")
    feed_id: int = Field(foreign_key="rsshub_feed.id", description="FeedID")

    title: str = Field(default="", max_length=1024, description="订阅标题")
    tags: str = Field(default="", max_length=255, description="标签")
    target_session: str | None = Field(
        default=None,
        max_length=255,
        description="订阅推送目标会话",
    )
    platform_name: str | None = Field(
        default=None,
        max_length=64,
        description="平台类型名",
    )

    interval: int = Field(default=INHERIT_VALUE, description="监控间隔(分钟)")
    next_check_time: datetime | None = Field(default=None, description="下次检查时间")
    notify: int = Field(default=INHERIT_VALUE, description="是否通知")
    send_mode: int = Field(
        default=INHERIT_VALUE,
        description="发送模式: -100=继承, -1=仅链接, 0=自动, 1=直接发送",
    )
    length_limit: int = Field(default=INHERIT_VALUE, description="长度限制")
    display_author: int = Field(default=INHERIT_VALUE, description="显示作者")
    display_via: int = Field(default=INHERIT_VALUE, description="显示来源")
    display_title: int = Field(default=INHERIT_VALUE, description="显示标题")
    display_entry_tags: int = Field(default=INHERIT_VALUE, description="显示标签")
    style: int = Field(default=INHERIT_VALUE, description="推送排版策略")
    display_media: int = Field(default=INHERIT_VALUE, description="显示媒体")
    send_card: bool = Field(default=False, description="是否发送模板卡片")
    template_id: str | None = Field(
        default=None,
        max_length=255,
        description="卡片模板 ID",
    )
    card_send_original_content: bool = Field(
        default=False,
        description="卡片成功后是否继续发送原始内容",
    )
    handlers_mode: str = Field(
        default="inherit",
        max_length=16,
        description="handlers 继承模式",
    )
    handlers: str = Field(default="[]", description="内容处理 handlers JSON")

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="创建时间",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)},
        description="更新时间",
    )


class BundleORM(RSSHubBaseModel, table=True):
    """多源聚合订阅 ORM 模型，映射 rsshub_bundle 表。"""

    __tablename__ = "rsshub_bundle"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "name",
            name="uq_rsshub_bundle_user_name",
        ),
        CheckConstraint(
            "state IN (0, 1)",
            name="ck_rsshub_bundle_state",
        ),
        CheckConstraint(
            "interval > 0",
            name="ck_rsshub_bundle_interval",
        ),
        CheckConstraint(
            "json_valid(target_sessions) AND json_array_length(target_sessions) > 0",
            name="ck_rsshub_bundle_target_sessions",
        ),
        Index(
            "idx_rsshub_bundle_due",
            "state",
            "next_check_time",
            "id",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(foreign_key="rsshub_user.id", description="用户 ID")
    name: str = Field(max_length=255, description="聚合订阅名称")
    target_sessions: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="有序推送目标会话",
    )
    state: int = Field(default=0, description="状态: 0=停用, 1=启用")
    interval: int = Field(description="固定滚动周期（分钟）")
    next_check_time: datetime | None = Field(default=None, description="下次检查时间")
    notify: int = Field(default=INHERIT_VALUE, description="是否通知")
    send_mode: int = Field(default=INHERIT_VALUE, description="发送模式")
    length_limit: int = Field(default=INHERIT_VALUE, description="长度限制")
    display_author: int = Field(default=INHERIT_VALUE, description="显示作者")
    display_via: int = Field(default=INHERIT_VALUE, description="显示来源")
    display_title: int = Field(default=INHERIT_VALUE, description="显示标题")
    display_entry_tags: int = Field(default=INHERIT_VALUE, description="显示标签")
    style: int = Field(default=INHERIT_VALUE, description="推送排版策略")
    display_media: int = Field(default=INHERIT_VALUE, description="显示媒体")
    handlers: str = Field(default="[]", description="文档级 handlers JSON")
    send_card: bool = Field(default=False, description="是否发送模板卡片")
    template_id: str | None = Field(
        default=None,
        max_length=255,
        description="卡片模板 ID",
    )
    card_send_original_content: bool = Field(
        default=False,
        description="卡片成功后是否继续发送聚合内容",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="创建时间",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)},
        description="更新时间",
    )


class BundleFeedORM(RSSHubBaseModel, table=True):
    """Bundle 成员及其私有采集水位。"""

    __tablename__ = "rsshub_bundle_feed"
    __table_args__ = (
        UniqueConstraint(
            "bundle_id",
            "feed_id",
            name="uq_rsshub_bundle_feed_member",
        ),
        UniqueConstraint(
            "bundle_id",
            "position",
            name="uq_rsshub_bundle_feed_position",
        ),
        CheckConstraint(
            "position >= 0",
            name="ck_rsshub_bundle_feed_position",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    bundle_id: int = Field(
        foreign_key="rsshub_bundle.id",
        ondelete="CASCADE",
        description="Bundle ID",
    )
    feed_id: int = Field(
        foreign_key="rsshub_feed.id",
        ondelete="RESTRICT",
        description="Feed ID",
    )
    position: int = Field(description="成员顺序，从 0 开始")
    entry_hashes: list[Any] | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="成员私有条目哈希水位",
    )
    etag: str | None = Field(default=None, max_length=128, description="私有 ETag")
    last_modified: datetime | None = Field(
        default=None,
        description="私有 Last-Modified",
    )
    last_check_status: str | None = Field(
        default=None,
        max_length=32,
        description="最近检查状态",
    )
    last_checked_at: datetime | None = Field(
        default=None,
        description="最近检查时间",
    )


class DeliveryBatchORM(RSSHubBaseModel, table=True):
    """可靠投递批次及其不可变快照。"""

    __tablename__ = "rsshub_delivery_batch"
    __table_args__ = (
        CheckConstraint(
            "owner_type IN ('subscription', 'bundle')",
            name="ck_rsshub_delivery_batch_owner_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'discarded')",
            name="ck_rsshub_delivery_batch_status",
        ),
        CheckConstraint(
            "json_valid(target_sessions) AND json_array_length(target_sessions) > 0",
            name="ck_rsshub_delivery_batch_target_sessions",
        ),
        Index(
            "uq_rsshub_delivery_batch_pending_owner",
            "owner_type",
            "owner_id",
            unique=True,
            sqlite_where=text("status = 'pending'"),
        ),
        Index(
            "idx_rsshub_delivery_batch_owner_status",
            "owner_type",
            "owner_id",
            "status",
            "id",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_type: str = Field(max_length=16, description="owner 类型")
    owner_id: int = Field(description="owner ID")
    status: str = Field(default="pending", max_length=16, description="批次状态")
    target_sessions: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="目标会话快照",
    )
    config_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
        description="投递配置快照",
    )
    template_snapshot: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="模板包不可变快照",
    )
    document_snapshot: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON),
        description="handler 前后文档快照",
    )
    output_manifest: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="批次配置输出的不可变身份清单",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="创建时间",
    )
    confirmed_at: datetime | None = Field(default=None, description="确认时间")


class DeliveryInboxItemORM(RSSHubBaseModel, table=True):
    """owner 私有可靠投递 inbox 条目。"""

    __tablename__ = "rsshub_delivery_inbox"
    __table_args__ = (
        UniqueConstraint(
            "owner_type",
            "owner_id",
            "feed_id",
            "item_key",
            name="uq_rsshub_delivery_inbox_owner_source_item",
        ),
        CheckConstraint(
            "owner_type IN ('subscription', 'bundle')",
            name="ck_rsshub_delivery_inbox_owner_type",
        ),
        CheckConstraint(
            "(owner_type = 'subscription' AND bundle_feed_id IS NULL "
            "AND member_position IS NULL) OR "
            "(owner_type = 'bundle' AND bundle_feed_id IS NOT NULL "
            "AND member_position IS NOT NULL AND member_position >= 0)",
            name="ck_rsshub_delivery_inbox_owner_source",
        ),
        CheckConstraint(
            "length(trim(item_key)) > 0",
            name="ck_rsshub_delivery_inbox_item_key",
        ),
        CheckConstraint(
            "length(trim(discovery_key)) > 0",
            name="ck_rsshub_delivery_inbox_discovery_key",
        ),
        Index(
            "idx_rsshub_delivery_inbox_unclaimed",
            "owner_type",
            "owner_id",
            "batch_id",
            "discovered_at",
            "id",
        ),
        Index(
            "idx_rsshub_delivery_inbox_discovery",
            "owner_type",
            "owner_id",
            "discovery_key",
            "id",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_type: str = Field(max_length=16, description="owner 类型")
    owner_id: int = Field(description="owner ID")
    feed_id: int = Field(
        foreign_key="rsshub_feed.id",
        ondelete="RESTRICT",
        description="来源 Feed ID",
    )
    bundle_feed_id: int | None = Field(
        default=None,
        foreign_key="rsshub_bundle_feed.id",
        ondelete="RESTRICT",
        description="来源 BundleFeed ID",
    )
    member_position: int | None = Field(default=None, description="成员顺序快照")
    item_key: str = Field(max_length=512, description="owner 内稳定条目标识")
    hash_group: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="稳定身份哈希集合",
    )
    discovery_key: str = Field(max_length=512, description="发现事务分组键")
    entry_payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
        description="JSON-safe entry 快照",
    )
    raw_xml: str | None = Field(default=None, description="条目原始 XML")
    media_items: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="媒体快照",
    )
    published_at: datetime | None = Field(default=None, description="发布时间")
    entry_updated_at: datetime | None = Field(default=None, description="条目更新时间")
    discovered_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="发现时间",
    )
    batch_id: int | None = Field(
        default=None,
        foreign_key="rsshub_delivery_batch.id",
        ondelete="RESTRICT",
        description="认领批次 ID",
    )


class PushHistoryORM(RSSHubBaseModel, table=True):
    """推送历史 ORM 模型，映射 rsshub_push_history 表。"""

    __tablename__ = "rsshub_push_history"
    __table_args__ = (
        CheckConstraint(
            "output_kind IN ('card', 'standard')",
            name="ck_rsshub_push_history_output_kind",
        ),
        CheckConstraint(
            "output_order >= 0",
            name="ck_rsshub_push_history_output_order",
        ),
        CheckConstraint(
            "status IS NULL OR status IN "
            "('waiting', 'pending', 'retrying', 'success', 'failed', "
            "'stopped', 'skipped', 'discarded')",
            name="ck_rsshub_push_history_status",
        ),
        Index(
            "idx_rsshub_push_history_batch_output",
            "batch_id",
            "target_session",
            "output_order",
            "id",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    sub_id: int | None = Field(
        default=None, foreign_key="rsshub_sub.id", description="订阅ID"
    )
    batch_id: int | None = Field(
        default=None,
        foreign_key="rsshub_delivery_batch.id",
        ondelete="RESTRICT",
        description="投递批次 ID",
    )
    bundle_id: int | None = Field(
        default=None,
        foreign_key="rsshub_bundle.id",
        ondelete="RESTRICT",
        description="Bundle ID",
    )
    user_id: str = Field(foreign_key="rsshub_user.id", description="用户ID")
    feed_id: int | None = Field(
        default=None, foreign_key="rsshub_feed.id", description="FeedID"
    )
    source_type: str = Field(default="feed", max_length=16, description="来源类型")
    source_key: str | None = Field(
        default=None, max_length=255, description="来源跟踪键"
    )

    content: str = Field(default="", description="格式化后的消息内容")
    raw_xml: str | None = Field(default=None, description="XML 推送原始内容")
    media_urls: list[str] | None = Field(
        default=None, sa_column=Column(JSON), description="媒体URL列表"
    )
    handler_trace: list[dict[str, Any]] | None = Field(
        default=None, sa_column=Column(JSON), description="handler 执行摘要"
    )
    output_kind: str = Field(
        default="standard",
        max_length=16,
        description="批次输出类型",
    )
    output_order: int = Field(default=0, ge=0, description="批次内输出顺序")
    source_context: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON),
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
        description="状态: pending/success/failed/stopped/skipped",
    )
    retry_count: int = Field(default=0, description="重试次数")
    max_retries: int = Field(default=3, description="最大重试次数")
    fail_reason: str | None = Field(
        default=None, max_length=512, description="失败原因"
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="创建时间",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)},
        description="更新时间",
    )
    completed_at: datetime | None = Field(default=None, description="完成时间")


class MigrationRecordORM(RSSHubBaseModel, table=True):
    """迁移记录 ORM 模型，映射 rsshub_migration_record 表。"""

    __tablename__ = "rsshub_migration_record"

    version: str = Field(primary_key=True, max_length=32, description="迁移版本号")
    applied_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="应用时间",
    )
    description: str = Field(default="", max_length=256, description="迁移描述")
