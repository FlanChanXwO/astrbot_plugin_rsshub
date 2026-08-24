"""Bundle 管理 LLM tools。

工具只从当前消息事件取得 owner，所有业务校验继续由 Bundle 应用用例执行。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from .common import extract_event, json_dumps, make_tool
from .types import FunctionTool, LLMToolDeps

if TYPE_CHECKING:
    from astrbot.core.agent.run_context import ContextWrapper
    from astrbot.core.astr_agent_context import AstrAgentContext


_BUNDLE_OPTION_KEYS = [
    "name",
    "target_sessions",
    "interval",
    "notify",
    "send_mode",
    "length_limit",
    "display_author",
    "display_via",
    "display_title",
    "display_entry_tags",
    "style",
    "display_media",
    "send_card",
    "template_id",
    "card_send_original_content",
]


def _jsonable(value: Any) -> Any:
    """把应用结果转换为 LLM 可消费的 JSON-safe 数据。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump(mode="json"))
    if hasattr(value, "__dict__"):
        return {
            key: _jsonable(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return str(value)


def _result_payload(result: Any, *, data_key: str = "data") -> str:
    """统一 LLM 工具成功/失败 envelope，避免暴露裸领域对象。"""
    payload: dict[str, Any] = {
        "ok": bool(getattr(result, "success", False)),
        "message": str(getattr(result, "message", "") or ""),
    }
    if payload["ok"]:
        data = getattr(result, "data", None)
        if data is not None:
            payload[data_key] = _jsonable(data)
            if hasattr(data, "id") and getattr(data, "id", None) is not None:
                payload["bundle_id"] = int(data.id)
    else:
        payload["error"] = payload["message"]
        error_code = getattr(result, "error_code", None)
        if error_code:
            payload["error_code"] = str(error_code)
        details = getattr(result, "details", None)
        if details is not None:
            payload["details"] = _jsonable(details)
    return json_dumps(payload)


def _event_user_id(context: Any) -> tuple[Any, str]:
    event = extract_event(context)
    return event, str(event.get_sender_id() or "").strip()


def build_bundle_tools(*, deps: LLMToolDeps, plugin_context) -> list[FunctionTool]:
    """构建 Bundle 安全管理工具。"""

    async def rss_bundle_create(
        context: ContextWrapper[AstrAgentContext],
        name: str,
        feed_ids: list[int],
        target_sessions: list[str],
        interval: int | None = None,
    ) -> str:
        _event, user_id = _event_user_id(context)
        if not user_id:
            return json_dumps({"ok": False, "error": "用户 ID 不能为空"})
        result = await deps["bundle_cmd"].create(
            user_id=user_id,
            name=name,
            feed_ids=feed_ids,
            target_sessions=target_sessions,
            interval=interval,
        )
        return _result_payload(result)

    async def rss_bundle_list(
        context: ContextWrapper[AstrAgentContext],
    ) -> str:
        _event, user_id = _event_user_id(context)
        if not user_id:
            return json_dumps({"ok": False, "error": "用户 ID 不能为空"})
        result = await deps["bundle_cmd"].list(user_id=user_id)
        return _result_payload(result, data_key="items")

    async def rss_bundle_get(
        context: ContextWrapper[AstrAgentContext],
        bundle_id: int,
    ) -> str:
        _event, user_id = _event_user_id(context)
        if not user_id:
            return json_dumps({"ok": False, "error": "用户 ID 不能为空"})
        result = await deps["bundle_cmd"].show(
            bundle_id=bundle_id,
            user_id=user_id,
        )
        return _result_payload(result)

    async def rss_bundle_update_members(
        context: ContextWrapper[AstrAgentContext],
        bundle_id: int,
        feed_ids: list[int],
    ) -> str:
        _event, user_id = _event_user_id(context)
        if not user_id:
            return json_dumps({"ok": False, "error": "用户 ID 不能为空"})
        result = await deps["bundle_cmd"].replace_members(
            bundle_id=bundle_id,
            user_id=user_id,
            feed_ids=feed_ids,
        )
        return _result_payload(result)

    async def rss_bundle_set_option(
        context: ContextWrapper[AstrAgentContext],
        bundle_id: int,
        key: str,
        value: Any,
    ) -> str:
        _event, user_id = _event_user_id(context)
        if not user_id:
            return json_dumps({"ok": False, "error": "用户 ID 不能为空"})
        result = await deps["bundle_cmd"].set_option(
            bundle_id=bundle_id,
            user_id=user_id,
            option=key,
            value=value,
        )
        return _result_payload(result)

    async def rss_bundle_set_handlers(
        context: ContextWrapper[AstrAgentContext],
        bundle_id: int,
        handlers: list[dict[str, Any]],
    ) -> str:
        _event, user_id = _event_user_id(context)
        if not user_id:
            return json_dumps({"ok": False, "error": "用户 ID 不能为空"})
        result = await deps["bundle_cmd"].set_handlers(
            bundle_id=bundle_id,
            user_id=user_id,
            handlers=handlers,
        )
        return _result_payload(result)

    async def rss_bundle_set_state(
        context: ContextWrapper[AstrAgentContext],
        bundle_id: int,
        state: int,
    ) -> str:
        _event, user_id = _event_user_id(context)
        if not user_id:
            return json_dumps({"ok": False, "error": "用户 ID 不能为空"})
        if isinstance(state, bool) or state not in {0, 1}:
            return json_dumps({"ok": False, "error": "state 只能是 0 或 1"})
        result = await deps["bundle_cmd"].state(
            bundle_id=bundle_id,
            user_id=user_id,
            enable=state == 1,
        )
        return _result_payload(result)

    async def rss_bundle_delete(
        context: ContextWrapper[AstrAgentContext],
        bundle_id: int,
    ) -> str:
        _event, user_id = _event_user_id(context)
        if not user_id:
            return json_dumps({"ok": False, "error": "用户 ID 不能为空"})
        result = await deps["bundle_cmd"].delete(
            bundle_id=bundle_id,
            user_id=user_id,
        )
        return _result_payload(result)

    return [
        make_tool(
            name="rss_bundle_create",
            description=(
                "在当前用户下创建停用的多源聚合订阅。feed_ids 至少包含两个不同 Feed，"
                "创建后如需启用请继续使用聊天命令或后续管理接口。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Bundle 名称",
                    },
                    "feed_ids": {
                        "type": "array",
                        "minItems": 2,
                        "items": {"type": "integer", "minimum": 1},
                        "description": "至少两个不同的 Feed ID",
                    },
                    "target_sessions": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                        "description": "推送目标会话列表",
                    },
                    "interval": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "检查周期（分钟），省略则使用插件默认值",
                    },
                },
                "required": ["name", "feed_ids", "target_sessions"],
                "additionalProperties": False,
            },
            handler=rss_bundle_create,
            plugin_context=plugin_context,
        ),
        make_tool(
            name="rss_bundle_list",
            description="列出当前用户拥有的聚合订阅；修改前先用此工具确认 Bundle ID。",
            parameters={"type": "object", "properties": {}},
            handler=rss_bundle_list,
            plugin_context=plugin_context,
        ),
        make_tool(
            name="rss_bundle_get",
            description="查看当前用户拥有的 Bundle 详情、成员顺序和状态。",
            parameters={
                "type": "object",
                "properties": {
                    "bundle_id": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Bundle ID",
                    }
                },
                "required": ["bundle_id"],
                "additionalProperties": False,
            },
            handler=rss_bundle_get,
            plugin_context=plugin_context,
        ),
        make_tool(
            name="rss_bundle_update_members",
            description="按给定顺序原子替换当前用户 Bundle 的 Feed 成员；含无效 Feed 时不会部分写入。",
            parameters={
                "type": "object",
                "properties": {
                    "bundle_id": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Bundle ID",
                    },
                    "feed_ids": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                        "description": "按推送顺序排列的 Feed ID 数组",
                    },
                },
                "required": ["bundle_id", "feed_ids"],
                "additionalProperties": False,
            },
            handler=rss_bundle_update_members,
            plugin_context=plugin_context,
        ),
        make_tool(
            name="rss_bundle_set_option",
            description=(
                "设置当前用户 Bundle 的单个配置项。应用层会校验归属、格式、"
                "卡片模板匹配和未解决投递保护。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "bundle_id": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Bundle ID",
                    },
                    "key": {
                        "type": "string",
                        "enum": _BUNDLE_OPTION_KEYS,
                        "description": "允许的 Bundle 配置项",
                    },
                    "value": {
                        "description": "配置值；类型由应用用例按 key 校验",
                        "oneOf": [
                            {"type": "string"},
                            {"type": "integer"},
                            {"type": "boolean"},
                            {"type": "array"},
                            {"type": "null"},
                        ],
                    },
                },
                "required": ["bundle_id", "key", "value"],
                "additionalProperties": False,
            },
            handler=rss_bundle_set_option,
            plugin_context=plugin_context,
        ),
        make_tool(
            name="rss_bundle_set_handlers",
            description="替换当前用户 Bundle 的文档级 handlers；先用 rss_list_handlers 确认可用 schema。",
            parameters={
                "type": "object",
                "properties": {
                    "bundle_id": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Bundle ID",
                    },
                    "handlers": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "文档级 handler 配置数组",
                    },
                },
                "required": ["bundle_id", "handlers"],
                "additionalProperties": False,
            },
            handler=rss_bundle_set_handlers,
            plugin_context=plugin_context,
        ),
        make_tool(
            name="rss_bundle_set_state",
            description="启用或停用当前用户的 Bundle；启用前应用层会检查成员、目标和模板。",
            parameters={
                "type": "object",
                "properties": {
                    "bundle_id": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Bundle ID",
                    },
                    "state": {
                        "type": "integer",
                        "enum": [0, 1],
                        "description": "0=停用，1=启用",
                    },
                },
                "required": ["bundle_id", "state"],
                "additionalProperties": False,
            },
            handler=rss_bundle_set_state,
            plugin_context=plugin_context,
        ),
        make_tool(
            name="rss_bundle_delete",
            description="删除当前用户的 Bundle；存在未解决 inbox 或批次时应用层会拒绝并返回错误。",
            parameters={
                "type": "object",
                "properties": {
                    "bundle_id": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Bundle ID",
                    }
                },
                "required": ["bundle_id"],
                "additionalProperties": False,
            },
            handler=rss_bundle_delete,
            plugin_context=plugin_context,
        ),
    ]
