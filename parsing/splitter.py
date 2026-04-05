"""
RSS-to-AstrBot Message Splitter
消息分割模块，处理超长消息
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# 分隔符优先级（从高到低）
SEPARATORS: Final[tuple[str, ...]] = (
    "\n\n",  # 段落
    "\n",  # 换行
    "。",  # 中文句号
    ". ",  # 英文句号
    "？",  # 中文问号
    "? ",  # 英文问号
    "！",  # 中文感叹号
    "! ",  # 英文感叹号
    "：",  # 中文冒号
    ": ",  # 英文冒号
    "；",  # 中文分号
    "; ",  # 英文分号
    "，",  # 中文逗号
    ", ",  # 英文逗号
    " ",  # 空格
)


@dataclass
class MessageChunk:
    """消息块"""

    text: str
    has_media: bool = False
    media_urls: list[str] = None

    def __post_init__(self):
        if self.media_urls is None:
            self.media_urls = []


def split_text(
    text: str, max_length: int = 4096, min_chunk_size: int | None = None
) -> list[str]:
    """
    将长文本分割为多个块

    Args:
        text: 要分割的文本
        max_length: 每块最大长度
        min_chunk_size: 每块最小长度（默认为 max_length 的一半）

    Returns:
        分割后的文本列表
    """
    if min_chunk_size is None:
        min_chunk_size = max_length // 2

    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # 尝试找到合适的分割点
        chunk = None
        for sep in SEPARATORS:
            # 在允许范围内查找分隔符
            search_start = min_chunk_size
            search_end = max_length

            # 查找最后一个分隔符位置
            pos = remaining.rfind(sep, search_start, search_end)

            if pos != -1:
                # 找到分隔符，在此处分割
                chunk = remaining[: pos + len(sep)]
                remaining = remaining[pos + len(sep) :]
                break

        if chunk is None:
            # 未找到合适的分隔符，强制在最大长度处分割
            chunk = remaining[:max_length]
            remaining = remaining[max_length:]

        chunks.append(chunk)

    return chunks


def split_message_with_entities(
    text: str, max_length: int = 4096
) -> list[tuple[str, int, int]]:
    """
    分割带有实体格式的消息

    Args:
        text: 消息文本
        max_length: 最大长度

    Returns:
        List of (chunk_text, start_offset, end_offset)
    """
    chunks = split_text(text, max_length)
    result = []
    offset = 0

    for chunk in chunks:
        end_offset = offset + len(chunk)
        result.append((chunk, offset, end_offset))
        offset = end_offset

    return result


def estimate_message_size(text: str) -> int:
    """
    估算消息大小（以字节为单位）

    Args:
        text: 消息文本

    Returns:
        估算的字节大小
    """
    # UTF-8 编码下，ASCII 字符占 1 字节，中文等占 3 字节
    return len(text.encode("utf-8"))


def needs_split(text: str, max_length: int = 4096) -> bool:
    """
    检查消息是否需要分割

    Args:
        text: 消息文本
        max_length: 最大长度

    Returns:
        是否需要分割
    """
    return len(text) > max_length


def smart_split(
    text: str, max_length: int = 4096, preserve_formatting: bool = True
) -> list[MessageChunk]:
    """
    智能分割消息

    尝试保持段落完整性，避免在句子中间分割

    Args:
        text: 消息文本
        max_length: 最大长度
        preserve_formatting: 是否保留格式

    Returns:
        MessageChunk 列表
    """
    if not needs_split(text, max_length):
        return [MessageChunk(text=text)]

    chunks = []

    # 首先尝试按段落分割
    paragraphs = text.split("\n\n")

    current_chunk = ""
    for para in paragraphs:
        # 如果当前段落本身超长
        if len(para) > max_length:
            # 先保存当前块
            if current_chunk:
                chunks.append(MessageChunk(text=current_chunk.strip()))
                current_chunk = ""

            # 分割超长段落
            para_chunks = split_text(para, max_length)
            for pc in para_chunks:
                chunks.append(MessageChunk(text=pc.strip()))
            continue

        # 检查是否可以添加到当前块
        test_chunk = current_chunk + "\n\n" + para if current_chunk else para
        if len(test_chunk) <= max_length:
            current_chunk = test_chunk
        else:
            # 保存当前块，开始新块
            if current_chunk:
                chunks.append(MessageChunk(text=current_chunk.strip()))
            current_chunk = para

    # 保存最后一块
    if current_chunk:
        chunks.append(MessageChunk(text=current_chunk.strip()))

    return chunks
