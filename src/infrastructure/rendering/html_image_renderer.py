"""AstrBot HTML→PNG 适配器。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class AstrBotT2I(Protocol):
    """AstrBot html_renderer 的最小运行时契约。"""

    async def render_custom_template(
        self,
        html: str,
        data: dict[str, Any],
        **kwargs: Any,
    ) -> object:
        """渲染自定义 HTML。"""
        ...


class CardImageRenderError(RuntimeError):
    """AstrBot T2I 未返回可持久化 PNG。"""


class AstrBotHtmlImageRenderer:
    """复用 AstrBot 内置 html_renderer，不引入额外浏览器运行时。"""

    def __init__(self, *, t2i: AstrBotT2I | None = None) -> None:
        self._t2i = t2i

    async def render(self, html: str) -> bytes:
        """把已完成 Jinja 渲染的 HTML 转换为 PNG 字节。"""
        t2i = self._t2i
        if t2i is None:
            from astrbot.core import html_renderer

            t2i = html_renderer
        try:
            result = await t2i.render_custom_template(
                html,
                {},
                return_url=False,
                options={"full_page": True, "type": "png", "scale": "css"},
            )
        except Exception as exc:
            raise CardImageRenderError(f"AstrBot T2I 渲染失败: {exc}") from exc
        if isinstance(result, bytes):
            return result
        if isinstance(result, (str, Path)):
            result_path = Path(result)
            if result_path.is_file():
                try:
                    return result_path.read_bytes()
                except OSError as exc:
                    raise CardImageRenderError(
                        f"无法读取 AstrBot T2I 产物 {result_path}: {exc}"
                    ) from exc
        raise CardImageRenderError(
            f"AstrBot T2I 返回了不支持的结果类型: {type(result).__name__}"
        )
