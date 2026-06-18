#!/usr/bin/env python3
"""QQ 官方媒体发送诊断脚本。

用途：从推送历史失败记录中抽取媒体 URL，按 QQ 官方 C2C/group 富媒体接口
分别测试 `/files` 上传和 `/messages` 发送，定位 `invalid content` 发生阶段。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import mimetypes
import os
import random
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import aiohttp


QQ_API_BASE = "https://api.sgroup.qq.com"
QQ_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"

FILE_TYPE_IMAGE = 1
FILE_TYPE_VIDEO = 2
FILE_TYPE_VOICE = 3
FILE_TYPE_FILE = 4

_URL_RE = re.compile(r"https?://[^\s\"'<>]+")

# 探针会处理生产历史里的任意媒体 URL，必须给网络 IO 明确边界，避免慢源
# 或异常大文件让诊断进程挂死。默认下载上限高于已知 39MiB 失败样本，
# 同时避免把任意大文件读入内存后再 base64 放大。
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
DEFAULT_READ_TIMEOUT_SECONDS = 60.0
DEFAULT_TOTAL_TIMEOUT_SECONDS = 120.0
DEFAULT_DOWNLOAD_MAX_BYTES = 64 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 256 * 1024


@dataclass(frozen=True)
class MediaProbeCase:
    """一条失败推送历史对应的媒体诊断样本。"""

    history_id: int
    entry_title: str
    entry_guid: str | None
    fail_reason: str | None
    platform_name: str | None
    target_session: str | None
    openid: str | None
    group_openid: str | None
    media_urls: tuple[str, ...]
    updated_at: str | None


def _iter_json_urls(value: Any) -> list[str]:
    if isinstance(value, str):
        return _URL_RE.findall(value)
    if isinstance(value, (list, tuple)):
        urls: list[str] = []
        for item in value:
            urls.extend(_iter_json_urls(item))
        return urls
    if isinstance(value, dict):
        urls: list[str] = []
        for item in value.values():
            urls.extend(_iter_json_urls(item))
        return urls
    return []


def _extract_xml_urls(raw_xml: str | None) -> list[str]:
    if not raw_xml:
        return []

    urls: list[str] = []
    try:
        root = ElementTree.fromstring(raw_xml)
    except ElementTree.ParseError:
        try:
            root = ElementTree.fromstring(f"<root>{raw_xml}</root>")
        except ElementTree.ParseError:
            return _URL_RE.findall(raw_xml)

    for node in root.iter():
        for key, value in node.attrib.items():
            normalized = key.rsplit("}", 1)[-1].lower()
            if normalized in {"url", "href", "src"}:
                urls.extend(_URL_RE.findall(value))
        if node.text:
            urls.extend(_URL_RE.findall(node.text))
        if node.tail:
            urls.extend(_URL_RE.findall(node.tail))
    return urls


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip().rstrip("),.;]")
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return tuple(result)


def extract_media_urls(
    media_urls_json: str | None, raw_xml: str | None
) -> tuple[str, ...]:
    """从历史 JSON 字段和 XML 标签中提取媒体链接。"""

    urls: list[str] = []
    if media_urls_json:
        try:
            urls.extend(_iter_json_urls(json.loads(media_urls_json)))
        except json.JSONDecodeError:
            urls.extend(_URL_RE.findall(media_urls_json))
    urls.extend(_extract_xml_urls(raw_xml))
    return _dedupe(urls)


def parse_target_session(session: str | None) -> tuple[str | None, str | None]:
    """解析 AstrBot session 字符串，返回 `(openid, group_openid)`。"""

    if not session:
        return None, None

    parts = [part.strip() for part in session.split(":") if part.strip()]
    session_id = parts[-1] if parts else session.strip()
    kind = parts[-2].lower() if len(parts) >= 2 else ""

    if "group" in kind or "群" in kind:
        return None, session_id
    return session_id, None


def load_failed_media_cases(
    db_path: str | Path,
    *,
    limit: int,
    fail_reason_like: str,
    target_session_override: str | None = None,
) -> list[MediaProbeCase]:
    """读取失败历史，抽取带媒体 URL 的 QQ 官方样本。"""

    sql = """
        SELECT id, entry_title, entry_guid, fail_reason, platform_name,
               target_session, raw_xml, media_urls, updated_at
        FROM rsshub_push_history
        WHERE status = 'failed'
          AND COALESCE(fail_reason, '') LIKE ?
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
    """
    cases: list[MediaProbeCase] = []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(sql, (f"%{fail_reason_like}%", limit)):
            session = target_session_override or row["target_session"]
            openid, group_openid = parse_target_session(session)
            media_urls = extract_media_urls(row["media_urls"], row["raw_xml"])
            if not media_urls:
                continue
            cases.append(
                MediaProbeCase(
                    history_id=int(row["id"]),
                    entry_title=str(row["entry_title"]),
                    entry_guid=row["entry_guid"],
                    fail_reason=row["fail_reason"],
                    platform_name=row["platform_name"],
                    target_session=session,
                    openid=openid,
                    group_openid=group_openid,
                    media_urls=media_urls,
                    updated_at=row["updated_at"],
                )
            )
    return cases


def infer_file_type(url: str, *, force_file: bool = False) -> int:
    """按 URL 后缀推断 QQ 官方 file_type。"""

    if force_file:
        return FILE_TYPE_FILE
    parsed = urlparse(url)
    nested_url = parse_qs(parsed.query).get("url", [None])[0]
    media_url = nested_url or url
    mime, _ = mimetypes.guess_type(media_url)
    if mime:
        if mime.startswith("image/"):
            return FILE_TYPE_IMAGE
        if mime.startswith("video/"):
            return FILE_TYPE_VIDEO
        if mime.startswith("audio/"):
            return FILE_TYPE_VOICE
    lowered = media_url.lower().split("?", 1)[0]
    if lowered.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return FILE_TYPE_IMAGE
    if lowered.endswith((".mp4", ".mov", ".m4v", ".webm")):
        return FILE_TYPE_VIDEO
    return FILE_TYPE_FILE


def build_upload_payload(
    *,
    url: str,
    file_type: int,
    openid: str | None,
    group_openid: str | None,
    file_bytes: bytes | None,
) -> dict[str, Any]:
    """构造 QQ `/files` 上传 payload。

    `file_bytes` 对应 AstrBot 本地缓存文件路径分支：先由插件下载媒体，
    再把文件内容 base64 后交给 QQ 官方，而不是让 QQ 服务器自行拉远程 URL。
    """

    payload: dict[str, Any] = {
        "file_type": file_type,
        "srv_send_msg": False,
    }
    if file_bytes is None:
        payload["url"] = url
    else:
        payload["file_data"] = base64.b64encode(file_bytes).decode("utf-8")

    if openid:
        payload["openid"] = openid
    elif group_openid:
        payload["group_openid"] = group_openid
    else:
        raise ValueError("openid or group_openid is required")
    return payload


def _redact_string(value: str, secrets: tuple[str, ...]) -> str:
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "***")
    return redacted


def redact_for_output(value: Any, *, secrets: tuple[str, ...]) -> Any:
    """递归隐藏报告中的敏感值。"""

    if isinstance(value, str):
        return _redact_string(value, secrets)
    if isinstance(value, list):
        return [redact_for_output(item, secrets=secrets) for item in value]
    if isinstance(value, tuple):
        return [redact_for_output(item, secrets=secrets) for item in value]
    if isinstance(value, dict):
        return {
            key: redact_for_output(item, secrets=secrets) for key, item in value.items()
        }
    return value


class QQOfficialMediaProbeClient:
    """最小 QQ 官方媒体接口客户端。"""

    def __init__(self, app_id: str, client_secret: str):
        self._app_id = app_id
        self._client_secret = client_secret
        self._access_token: str | None = None

    async def _ensure_token(self, session: aiohttp.ClientSession) -> str:
        if self._access_token:
            return self._access_token

        async with session.post(
            QQ_TOKEN_URL,
            json={"appId": self._app_id, "clientSecret": self._client_secret},
        ) as response:
            data = await _read_response(response)
        if "access_token" not in data:
            raise RuntimeError(f"getAppAccessToken failed: {data}")
        self._access_token = str(data["access_token"])
        return self._access_token

    async def _request(
        self,
        session: aiohttp.ClientSession,
        method: str,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        token = await self._ensure_token(session)
        headers = {
            "Authorization": f"QQBot {token}",
            "X-Union-Appid": self._app_id,
        }
        async with session.request(
            method,
            f"{QQ_API_BASE}{path}",
            headers=headers,
            json=payload,
        ) as response:
            return await _read_response(response)

    async def upload_media(
        self,
        session: aiohttp.ClientSession,
        *,
        url: str,
        file_type: int,
        openid: str | None,
        group_openid: str | None,
        srv_send_msg: bool,
        file_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        payload = build_upload_payload(
            url=url,
            file_type=file_type,
            openid=openid,
            group_openid=group_openid,
            file_bytes=file_bytes,
        )
        payload["srv_send_msg"] = srv_send_msg
        if openid:
            path = f"/v2/users/{openid}/files"
        elif group_openid:
            path = f"/v2/groups/{group_openid}/files"
        else:
            raise ValueError("openid or group_openid is required")
        return await self._request(session, "POST", path, payload)

    async def send_media_message(
        self,
        session: aiohttp.ClientSession,
        *,
        media: dict[str, Any],
        openid: str | None,
        group_openid: str | None,
        content: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "content": content,
            "msg_type": 7,
            "media": media,
            "msg_seq": random.randint(1, 10000),
        }
        if openid:
            payload["openid"] = openid
            path = f"/v2/users/{openid}/messages"
        elif group_openid:
            payload["group_openid"] = group_openid
            path = f"/v2/groups/{group_openid}/messages"
        else:
            raise ValueError("openid or group_openid is required")
        return await self._request(session, "POST", path, payload)


async def _read_response(response: aiohttp.ClientResponse) -> dict[str, Any]:
    try:
        data: Any = await response.json()
    except aiohttp.ContentTypeError:
        data = await response.text()

    if response.status in {200, 202, 204}:
        return data if isinstance(data, dict) else {"data": data}
    message = data.get("message") if isinstance(data, dict) else str(data)
    raise RuntimeError(f"HTTP {response.status}: {message}")


async def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_failed_media_cases(
        args.db,
        limit=args.limit,
        fail_reason_like=args.fail_reason_like,
        target_session_override=args.target_session,
    )
    report: dict[str, Any] = {
        "mode": args.mode,
        "cases": [asdict(case) for case in cases],
        "results": [],
    }
    if args.mode == "dry-run":
        return report

    secret = _read_secret(args)
    client = QQOfficialMediaProbeClient(args.app_id, secret)
    timeout = aiohttp.ClientTimeout(
        total=args.total_timeout,
        connect=args.connect_timeout,
        sock_read=args.read_timeout,
    )
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for case in cases:
            for url in case.media_urls[: args.media_per_case]:
                result = await _probe_one_url(
                    client,
                    session,
                    case=case,
                    url=url,
                    mode=args.mode,
                    force_file=args.force_file,
                    upload_source=args.upload_source,
                    message_prefix=args.message_prefix,
                    download_max_bytes=args.download_max_bytes,
                )
                report["results"].append(result)
    return report


async def _probe_one_url(
    client: QQOfficialMediaProbeClient,
    session: aiohttp.ClientSession,
    *,
    case: MediaProbeCase,
    url: str,
    mode: str,
    force_file: bool,
    upload_source: str,
    message_prefix: str,
    download_max_bytes: int,
) -> dict[str, Any]:
    file_type = infer_file_type(url, force_file=force_file)
    file_bytes = (
        await _download_bytes(session, url, max_bytes=download_max_bytes)
        if upload_source == "download"
        else None
    )
    result: dict[str, Any] = {
        "history_id": case.history_id,
        "entry_guid": case.entry_guid,
        "url": url,
        "file_type": file_type,
        "upload_source": upload_source,
        "download_size": len(file_bytes) if file_bytes is not None else None,
        "upload": None,
        "send": None,
    }
    media = await client.upload_media(
        session,
        url=url,
        file_type=file_type,
        openid=case.openid,
        group_openid=case.group_openid,
        srv_send_msg=False,
        file_bytes=file_bytes,
    )
    result["upload"] = media
    if mode == "send":
        content = f"{message_prefix} history_id={case.history_id} file_type={file_type}"
        result["send"] = await client.send_media_message(
            session,
            media=media,
            openid=case.openid,
            group_openid=case.group_openid,
            content=content,
        )
    return result


async def _download_bytes(
    session: aiohttp.ClientSession,
    url: str,
    *,
    max_bytes: int = DEFAULT_DOWNLOAD_MAX_BYTES,
) -> bytes:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    async with session.get(url) as response:
        if response.status != 200:
            raise RuntimeError(f"download failed HTTP {response.status}: {url}")
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                expected_size = int(content_length)
            except ValueError:
                expected_size = 0
            if expected_size > max_bytes:
                raise RuntimeError(f"download exceeds limit {max_bytes} bytes: {url}")

        data = bytearray()
        async for chunk in response.content.iter_chunked(DOWNLOAD_CHUNK_BYTES):
            if not chunk:
                continue
            data.extend(chunk)
            if len(data) > max_bytes:
                raise RuntimeError(f"download exceeds limit {max_bytes} bytes: {url}")
        return bytes(data)


def _read_secret(args: argparse.Namespace) -> str:
    if args.secret_stdin:
        secret = sys.stdin.readline().strip()
    else:
        secret = os.environ.get(args.secret_env, "")
    if not secret:
        raise RuntimeError(
            f"missing client secret; set {args.secret_env} or pass --secret-stdin"
        )
    return secret


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return parsed


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="rsshub.db 路径")
    parser.add_argument(
        "--mode",
        choices=("dry-run", "upload-only", "send"),
        default="dry-run",
        help="dry-run 只抽样；upload-only 只调用 /files；send 还调用 /messages",
    )
    parser.add_argument("--limit", type=int, default=5, help="最多抽样失败历史条数")
    parser.add_argument(
        "--media-per-case",
        type=int,
        default=1,
        help="每条历史最多测试几个媒体 URL",
    )
    parser.add_argument(
        "--fail-reason-like",
        default="invalid content",
        help="失败原因 LIKE 过滤条件",
    )
    parser.add_argument(
        "--target-session",
        help="覆盖历史 target_session，例如 名称:私聊:openid",
    )
    parser.add_argument("--app-id", default=os.environ.get("QQ_OFFICIAL_APP_ID"))
    parser.add_argument(
        "--secret-env",
        default="QQ_OFFICIAL_CLIENT_SECRET",
        help="读取 QQ 官方 client secret 的环境变量名",
    )
    parser.add_argument(
        "--secret-stdin",
        action="store_true",
        help="从 stdin 第一行读取 client secret，避免出现在命令行",
    )
    parser.add_argument(
        "--force-file",
        action="store_true",
        help="全部媒体按 file_type=4 普通文件上传，用于验证文件降级路径",
    )
    parser.add_argument(
        "--upload-source",
        choices=("url", "download"),
        default="url",
        help="url 让 QQ 拉取远程 URL；download 先本地下载再按 file_data 上传",
    )
    parser.add_argument(
        "--connect-timeout",
        type=_positive_float,
        default=DEFAULT_CONNECT_TIMEOUT_SECONDS,
        help="aiohttp 连接超时秒数",
    )
    parser.add_argument(
        "--read-timeout",
        type=_positive_float,
        default=DEFAULT_READ_TIMEOUT_SECONDS,
        help="aiohttp socket 读取超时秒数",
    )
    parser.add_argument(
        "--total-timeout",
        type=_positive_float,
        default=DEFAULT_TOTAL_TIMEOUT_SECONDS,
        help="aiohttp 单请求总超时秒数",
    )
    parser.add_argument(
        "--download-max-bytes",
        type=_positive_int,
        default=DEFAULT_DOWNLOAD_MAX_BYTES,
        help="upload-source=download 时允许读取的最大媒体字节数",
    )
    parser.add_argument(
        "--message-prefix",
        default="[rsshub media probe]",
        help="真实 send 模式发出的测试消息前缀",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.mode != "dry-run" and not args.app_id:
        parser.error("--app-id or QQ_OFFICIAL_APP_ID is required outside dry-run")

    try:
        report = asyncio.run(run_probe(args))
    except Exception as exc:
        report = {"ok": False, "error": str(exc)}
        print(
            json.dumps(
                redact_for_output(
                    report, secrets=(os.environ.get(args.secret_env, ""),)
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    secret = os.environ.get(args.secret_env, "")
    print(
        json.dumps(
            redact_for_output(report, secrets=(secret,)),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
