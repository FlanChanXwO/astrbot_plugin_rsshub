"""NapCat stream upload helpers for local media files.

参考 astrbot_plugin_setu 的实现，提供分块流式上传功能。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import math
import uuid
from pathlib import Path
from typing import Any

from ..utils import get_logger

logger = get_logger()

DEFAULT_STREAM_CHUNK_SIZE = 64 * 1024
DEFAULT_FILE_RETENTION_MS = 30 * 1000


def _get_bot_client(event_or_client: Any) -> Any | None:
    """解析出 bot 客户端

    既支持传入 AstrBot 事件对象（从中提取 bot），
    也支持直接传入已经支持 call_action 的 bot 客户端。
    """
    if event_or_client is None:
        return None
    # 直接传入的 bot 客户端
    if _supports_call_action(event_or_client):
        return event_or_client
    # 从事件对象中提取
    return getattr(event_or_client, "bot", None) or getattr(
        event_or_client, "_bot", None
    )


def _supports_call_action(bot_client: Any) -> bool:
    """检查 bot 客户端是否支持 call_action"""
    if bot_client is None:
        return False
    return (
        hasattr(bot_client, "api") and hasattr(bot_client.api, "call_action")
    ) or hasattr(bot_client, "call_action")


async def _call_action(bot_client: Any, action: str, params: dict[str, Any]) -> Any:
    """调用 bot 客户端的 action"""
    if hasattr(bot_client, "api") and hasattr(bot_client.api, "call_action"):
        return await bot_client.api.call_action(action, **params)
    if hasattr(bot_client, "call_action"):
        return await bot_client.call_action(action, **params)
    return None


def _extract_response_data(response: Any) -> dict[str, Any]:
    """提取响应数据并检查错误"""
    if response is None:
        raise RuntimeError("NapCat Stream API 未返回响应")
    if not isinstance(response, dict):
        raise RuntimeError(f"NapCat Stream API 返回格式异常: {type(response).__name__}")

    status = response.get("status")
    if status == "failed":
        message = response.get("message") or response.get("wording") or response
        raise RuntimeError(f"NapCat Stream API 返回失败: {message}")
    retcode = response.get("retcode")
    if retcode not in (None, 0):
        message = response.get("message") or response.get("wording") or response
        raise RuntimeError(f"NapCat Stream API 返回错误: retcode={retcode}, {message}")

    data = response.get("data")
    if isinstance(data, dict):
        return data
    return response


def _extract_uploaded_path(response: Any) -> str | None:
    """从响应中提取上传后的文件路径"""
    data = _extract_response_data(response)
    for key in ("file_path", "file", "path"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _calculate_sha256(file_path: Path) -> str:
    """计算文件的 SHA256 哈希值"""
    hasher = hashlib.sha256()
    with file_path.open("rb") as file:
        while True:
            chunk = file.read(DEFAULT_STREAM_CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


async def upload_file_stream(
    event_or_client: Any,
    file_path: str | Path,
    *,
    chunk_size: int = DEFAULT_STREAM_CHUNK_SIZE,
    file_retention_ms: int = DEFAULT_FILE_RETENTION_MS,
) -> str | None:
    """通过 NapCat 的流式 API 上传本地文件

    Args:
        event_or_client: AstrBot 事件对象或直接的 bot 客户端
        file_path: 本地文件路径
        chunk_size: 分块大小（字节）
        file_retention_ms: 文件保留时间（毫秒）

    Returns:
        上传后的远程文件路径，失败返回 None
    """
    bot_client = _get_bot_client(event_or_client)
    if not bot_client or not _supports_call_action(bot_client):
        logger.debug("[napcat_stream] 不可用: 缺少 bot call_action 支持")
        return None

    path = Path(file_path)
    if not path.exists() or not path.is_file():
        logger.warning("[napcat_stream] 跳过: 无效的文件路径=%s", path)
        return None

    file_size = path.stat().st_size
    if file_size <= 0:
        logger.warning("[napcat_stream] 跳过: 空文件 path=%s", path)
        return None

    chunk_size = max(1, int(chunk_size or DEFAULT_STREAM_CHUNK_SIZE))
    total_chunks = max(1, math.ceil(file_size / chunk_size))
    stream_id = str(uuid.uuid4())

    try:
        expected_sha256 = await asyncio.to_thread(_calculate_sha256, path)
        current_size = path.stat().st_size
        if current_size != file_size:
            raise RuntimeError("文件在上传前大小发生变化")

        logger.info(
            "[napcat_stream] 开始上传: file=%s, size=%d, chunks=%d",
            path.name,
            file_size,
            total_chunks,
        )

        with path.open("rb") as file:
            for chunk_index in range(total_chunks):
                chunk = file.read(chunk_size)
                if not chunk:
                    raise RuntimeError("文件在上传过程中提前结束")
                response = await _call_action(
                    bot_client,
                    "upload_file_stream",
                    {
                        "stream_id": stream_id,
                        "chunk_data": base64.b64encode(chunk).decode("utf-8"),
                        "chunk_index": chunk_index,
                        "total_chunks": total_chunks,
                        "file_size": file_size,
                        "expected_sha256": expected_sha256,
                        "filename": path.name,
                        "file_retention": file_retention_ms,
                    },
                )
                _extract_response_data(response)

        complete_response = await _call_action(
            bot_client,
            "upload_file_stream",
            {"stream_id": stream_id, "is_complete": True},
        )
        uploaded = _extract_uploaded_path(complete_response)
        logger.info(
            "[napcat_stream] 上传完成: file=%s, remote=%s",
            path.name,
            uploaded,
        )
        return uploaded
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception(
            "[napcat_stream] 上传失败: file=%s, error=%s",
            path.name,
            exc,
        )
        return None
