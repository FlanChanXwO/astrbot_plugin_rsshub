"""媒体发送分发解析器

统一将 PreparedMedia / LayoutFragment 映射为发送阶段的媒体类型、组件类型和文件路径，
使各平台 sender 和 pipeline 无需各自实现 GIF 转换后的类型修正逻辑。

规则：
- video + local_path.suffix == ".gif" → media_type="image"，component_kind="media"，file=local_path
- audio/file → component_kind="tail"
- image/video → component_kind="media"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...domain.entities.content_types import LayoutFragment
    from ..messaging.senders.types import PreparedMedia


@dataclass(frozen=True)
class MediaDispatchInfo:
    """媒体分发信息：描述一个媒体项在发送阶段应该使用的类型和路径。"""

    media_type: str
    """实际发送类型：image / video / audio / file"""
    component_kind: str
    """组件类别：media（图/视频）或 tail（音频/文件）"""
    file: str
    """实际发送时使用的文件路径或 URL"""
    original_url: str
    """原始媒体 URL"""
    name: str = ""
    """文件名（仅 file 类型需要）"""


class MediaDispatchResolver:
    """媒体发送分发解析器。

    统一决定 PreparedMedia / LayoutFragment 在发送时应该使用什么 media_type、
    component_kind 和文件路径。所有 sender 和 pipeline 代码都通过此类消费分发结果，
    不再直接读取 PreparedMedia.media_type 做分支判断。
    """

    # ------------------------------------------------------------------
    # PreparedMedia → MediaDispatchInfo
    # ------------------------------------------------------------------

    @staticmethod
    def resolve_prepared(
        item: PreparedMedia,
    ) -> MediaDispatchInfo:
        """将 PreparedMedia 解析为 MediaDispatchInfo。

        Args:
            item: 预处理后的媒体项
        """
        media_type = str(item.media_type or "").strip()
        original_url = str(item.original_url or "")

        # 无声视频转 GIF 后按图片发送
        if (
            media_type == "video"
            and item.local_path is not None
            and str(item.local_path).lower().endswith(".gif")
        ):
            return MediaDispatchInfo(
                media_type="image",
                component_kind="media",
                file=str(item.local_path),
                original_url=original_url,
            )

        if media_type in ("image", "video"):
            file = MediaDispatchResolver._resolve_video_path(item)
            return MediaDispatchInfo(
                media_type=media_type,
                component_kind="media",
                file=file,
                original_url=original_url,
            )

        # audio / file → tail
        file = str(item.local_path) if item.local_path else original_url
        return MediaDispatchInfo(
            media_type=media_type,
            component_kind="tail",
            file=file,
            original_url=original_url,
            name=MediaDispatchResolver._filename_from_url(original_url)
            if media_type == "file"
            else "",
        )

    @staticmethod
    def _resolve_video_path(
        item: PreparedMedia,
    ) -> str:
        """决定视频/图片使用的文件路径或 URL。"""
        return str(item.local_path) if item.local_path else item.original_url

    # ------------------------------------------------------------------
    # LayoutFragment → MediaDispatchInfo
    # ------------------------------------------------------------------

    @staticmethod
    def resolve_layout_fragment(
        fragment: LayoutFragment,
        prepared_media_by_url: dict[str, PreparedMedia] | None = None,
    ) -> MediaDispatchInfo:
        """将 LayoutFragment 解析为 MediaDispatchInfo。

        如果 fragment 的 URL 命中了预下载结果，复用 resolve_prepared() 的分发逻辑；
        否则保留 fragment 的原始类型和 URL。

        Args:
            fragment: 布局片段
            prepared_media_by_url: original_url → PreparedMedia 的映射（可选）
        """
        kind = str(fragment.kind or "").strip()
        url = str(fragment.url or "").strip()
        name = str(fragment.name or "").strip()

        # 已预下载 → 走 resolve_prepared
        if url and prepared_media_by_url:
            prepared = prepared_media_by_url.get(url)
            if prepared is not None:
                if prepared.download_failed:
                    from ...domain.entities.content_types import is_generated_media_url

                    if prepared.generated or is_generated_media_url(url):
                        return MediaDispatchInfo(
                            media_type="",
                            component_kind="",
                            file="",
                            original_url=url,
                        )
                return MediaDispatchResolver.resolve_prepared(prepared)

        # 未预下载 → 保留原始类型
        if kind in ("image", "video") and fragment.local_path:
            return MediaDispatchInfo(
                media_type=kind,
                component_kind="media",
                file=fragment.local_path,
                original_url=url,
            )
        if kind in ("audio", "file") and fragment.local_path:
            return MediaDispatchInfo(
                media_type=kind,
                component_kind="tail",
                file=fragment.local_path,
                original_url=url,
                name=name,
            )
        if kind in ("image", "video") and url:
            return MediaDispatchInfo(
                media_type=kind,
                component_kind="media",
                file=url,
                original_url=url,
            )
        if kind in ("audio", "file") and url:
            return MediaDispatchInfo(
                media_type=kind,
                component_kind="tail",
                file=url,
                original_url=url,
                name=name,
            )
        # text 不应走此方法，返回空
        return MediaDispatchInfo(
            media_type="",
            component_kind="",
            file="",
            original_url=url,
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filename_from_url(url: str) -> str:
        from urllib.parse import unquote, urlparse

        return unquote(urlparse(url).path.rsplit("/", 1)[-1]) or "attachment"
