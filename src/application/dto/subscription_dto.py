"""
Subscription DTO

订阅数据传输对象，用于在应用层和接口层之间传递订阅数据。
"""

from datetime import datetime

from pydantic import BaseModel, Field


class SubscriptionDTO(BaseModel):
    """
    订阅数据传输对象
    """

    id: int | None = Field(default=None, description="订阅 ID")
    user_id: str = Field(..., description="用户 ID")
    feed_id: int = Field(..., description="Feed ID")
    title: str = Field(default="", description="订阅标题")
    feed_title: str | None = Field(default=None, description="Feed 标题")
    feed_link: str | None = Field(default=None, description="Feed 链接")
    tags: str = Field(default="", description="标签")
    target_session: str | None = Field(default=None, description="推送目标会话")
    platform_name: str | None = Field(default=None, description="平台类型名")
    state: int = Field(default=1, description="状态: 0=停用, 1=启用")
    send_card: bool = Field(default=False, description="是否发送模板卡片")
    template_id: str | None = Field(default=None, description="卡片模板 ID")
    card_send_original_content: bool = Field(
        default=False,
        description="卡片发送成功后是否继续发送原始内容",
    )
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    class Config:
        frozen = True
