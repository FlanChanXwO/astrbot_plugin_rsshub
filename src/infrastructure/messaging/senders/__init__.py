"""消息发送器包

提供跨平台消息发送的实现。
"""

__all__ = [
    # 基础类型
    "BaseMessageSender",
    "SendResult",
    "PreparedMedia",
    "ChannelInfo",
    "MessageContext",
    # 发送器类
    "DefaultMessageSender",
    "TelegramMessageSender",
    "OneBotMessageSender",
    "QQOfficialMessageSender",
    "WeixinOCMessageSender",
    "InfrastructureMessageSenderAdapter",
    "InfrastructureMessageSenderProvider",
    # 工厂方法
    "get_sender_for_platform",
    "register_sender",
    # 工具函数
    "set_bot_self_id_provider",
    "get_bot_self_id",
    "set_bot_client_provider",
    "get_bot_client",
]

_EXPORTS: dict[str, tuple[str, str]] = {
    "BaseMessageSender": ("types", "BaseMessageSender"),
    "SendResult": ("types", "SendResult"),
    "PreparedMedia": ("types", "PreparedMedia"),
    "ChannelInfo": ("types", "ChannelInfo"),
    "MessageContext": ("types", "MessageContext"),
    "DefaultMessageSender": ("base_sender", "DefaultMessageSender"),
    "TelegramMessageSender": ("telegram_sender", "TelegramMessageSender"),
    "OneBotMessageSender": ("onebot_sender", "OneBotMessageSender"),
    "QQOfficialMessageSender": ("qq_official_sender", "QQOfficialMessageSender"),
    "WeixinOCMessageSender": ("weixin_oc_sender", "WeixinOCMessageSender"),
    "InfrastructureMessageSenderAdapter": (
        "provider",
        "InfrastructureMessageSenderAdapter",
    ),
    "InfrastructureMessageSenderProvider": (
        "provider",
        "InfrastructureMessageSenderProvider",
    ),
    "get_sender_for_platform": ("factory", "get_sender_for_platform"),
    "register_sender": ("factory", "register_sender"),
    "set_bot_self_id_provider": ("types", "set_bot_self_id_provider"),
    "get_bot_self_id": ("types", "get_bot_self_id"),
    "set_bot_client_provider": ("types", "set_bot_client_provider"),
    "get_bot_client": ("types", "get_bot_client"),
}


def __getattr__(name: str):
    """按需加载 sender 实现，避免类型导入触发 AstrBot 运行时依赖。"""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    from importlib import import_module

    value = getattr(import_module(f"{__name__}.{module_name}"), attr_name)
    globals()[name] = value
    return value
