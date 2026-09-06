"""
更新订阅选项命令

处理更新订阅配置选项的业务用例。
"""

from ...domain.entities.handlers import parse_handlers_input
from ...domain.entities.subscription import SUPPORTED_HANDLERS_MODES
from ...domain.repositories.delivery_repository import DeliveryDeletionBlockedError
from ...domain.repositories.subscription_repository import SubscriptionRepository
from ...infrastructure.config import validate_interval_value
from ..dto.result_dto import CommandResult
from ..dto.subscription_dto import SubscriptionDTO

REMOVED_OPTIONS = {
    "translate",
    "translate_target_lang",
    "use_sub_config",
    "ai_prompt",
}
STRING_OPTIONS = {
    "title",
    "tags",
    "target_session",
    "platform_name",
    "handlers_mode",
}
JSON_OPTIONS = {"handlers"}
BOOLEAN_OPTIONS = {"send_card", "card_send_original_content"}
_BOOLEAN_TRUE_VALUES = {"1", "true", "yes", "on"}
_BOOLEAN_FALSE_VALUES = {"0", "false", "no", "off"}


def _parse_boolean_option(key: str, value: object) -> bool:
    """解析公开配置入口的布尔值，拒绝含糊文本。"""
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in _BOOLEAN_TRUE_VALUES:
        return True
    if normalized in _BOOLEAN_FALSE_VALUES:
        return False
    raise ValueError(f"{key} 只支持 true / false")


class UpdateSubscriptionCommand:
    """
    更新订阅选项命令

    处理更新订阅配置选项的业务用例。
    """

    def __init__(
        self,
        subscription_repo: SubscriptionRepository,
        card_management_service=None,
    ):
        self._subscription_repo = subscription_repo
        self._card_management_service = card_management_service

    async def execute(
        self,
        sub_id: int,
        user_id: str,
        allow_template_selection: bool = False,
        **options,
    ) -> CommandResult:
        """
        执行更新命令

        Args:
            sub_id: 订阅 ID
            user_id: 用户 ID
            **options: 要更新的选项

        Returns:
            CommandResult: 命令执行结果
        """
        removed = sorted(REMOVED_OPTIONS.intersection(options))
        if removed:
            return CommandResult(
                success=False,
                message=("订阅翻译选项已移除: " + ", ".join(removed)),
            )
        if "template_id" in options and not allow_template_selection:
            return CommandResult(
                success=False,
                message="template_id 不能通过自由文本命令设置，请从模板候选中选择",
            )
        normalized_options = {}
        for key, value in options.items():
            if key in STRING_OPTIONS:
                normalized_value = str(value or "").strip()
                if key == "handlers_mode":
                    normalized_value = normalized_value.lower()
                    if normalized_value not in SUPPORTED_HANDLERS_MODES:
                        return CommandResult(
                            success=False,
                            message="handlers_mode 只支持 inherit / override / disabled",
                        )
                normalized_options[key] = normalized_value
                continue
            if key == "template_id":
                normalized_options[key] = (
                    str(value).strip() if value is not None else None
                )
                continue
            if key in JSON_OPTIONS:
                try:
                    normalized_options[key] = parse_handlers_input(value)
                except ValueError as exc:
                    return CommandResult(success=False, message=str(exc))
                continue
            if key in BOOLEAN_OPTIONS:
                try:
                    normalized_options[key] = _parse_boolean_option(key, value)
                except ValueError as exc:
                    return CommandResult(success=False, message=str(exc))
                continue
            if key == "interval":
                try:
                    normalized_options[key] = validate_interval_value(
                        value,
                        allow_inherit=True,
                        field_name="interval",
                    )
                except ValueError as exc:
                    return CommandResult(success=False, message=str(exc))
                continue
            normalized_options[key] = value

        card_options = {
            key: normalized_options[key]
            for key in (*BOOLEAN_OPTIONS, "template_id")
            if key in normalized_options
        }
        if card_options:
            if self._card_management_service is None:
                return CommandResult(
                    success=False,
                    message="卡片配置服务未初始化",
                )
            try:
                await self._card_management_service.validate_configuration(
                    subscription_id=sub_id,
                    user_id=user_id,
                    **card_options,
                )
            except (ValueError, PermissionError, DeliveryDeletionBlockedError) as exc:
                return CommandResult(success=False, message=str(exc))

        subscription = await self._subscription_repo.update_options(
            sub_id, user_id, **normalized_options
        )
        if not subscription:
            return CommandResult(
                success=False,
                message=f"订阅不存在或无权修改 (ID: {sub_id})",
            )

        return CommandResult(
            success=True,
            message=f"已更新订阅选项 (ID: {sub_id})",
            data=SubscriptionDTO(
                id=subscription.id,
                user_id=subscription.user_id,
                feed_id=subscription.feed_id,
                title=subscription.title,
                tags=subscription.tags,
                target_session=subscription.target_session,
                platform_name=subscription.platform_name,
                state=subscription.state,
                send_card=subscription.send_card,
                template_id=subscription.template_id,
                card_send_original_content=subscription.card_send_original_content,
                created_at=subscription.created_at,
                updated_at=subscription.updated_at,
            ),
        )
