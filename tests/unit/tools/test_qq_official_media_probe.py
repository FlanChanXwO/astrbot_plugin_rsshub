from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "qq_official_media_probe.py"
)


def _load_probe_module():
    spec = importlib.util.spec_from_file_location(
        "qq_official_media_probe", _SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _create_history_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE rsshub_push_history (
                id INTEGER PRIMARY KEY,
                entry_title VARCHAR(1024) NOT NULL,
                entry_guid VARCHAR(512),
                fail_reason VARCHAR(512),
                status VARCHAR(16),
                platform_name VARCHAR(64),
                target_session VARCHAR(255),
                raw_xml VARCHAR,
                media_urls JSON,
                updated_at DATETIME
            )
            """
        )
        conn.execute(
            """
            INSERT INTO rsshub_push_history (
                id, entry_title, entry_guid, fail_reason, status, platform_name,
                target_session, raw_xml, media_urls, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "失败媒体",
                "guid-1",
                "partial send: send_video: platform_send: invalid content",
                "failed",
                "qq_official",
                "阿罗娜:私聊:A861CA72455732D8228536CE248A089B",
                '<item><enclosure url="https://example.com/from-xml.mp4" type="video/mp4" /></item>',
                json.dumps(["https://example.com/from-json.jpg"]),
                "2026-06-17 22:40:30",
            ),
        )


def test_failed_history_samples_include_xml_media_and_context(tmp_path: Path):
    module = _load_probe_module()
    db_path = tmp_path / "rsshub.db"
    _create_history_db(db_path)

    cases = module.load_failed_media_cases(
        db_path,
        limit=5,
        fail_reason_like="invalid content",
    )

    assert len(cases) == 1
    assert cases[0].history_id == 1
    assert cases[0].openid == "A861CA72455732D8228536CE248A089B"
    assert cases[0].media_urls == (
        "https://example.com/from-json.jpg",
        "https://example.com/from-xml.mp4",
    )
    assert (
        cases[0].fail_reason
        == "partial send: send_video: platform_send: invalid content"
    )


def test_secret_values_are_redacted_from_json_report():
    module = _load_probe_module()
    report = module.redact_for_output(
        {
            "app_id": "1234567890",
            "client_secret": "DO_NOT_LEAK",
            "nested": {"authorization": "QQBot token-value"},
        },
        secrets=("DO_NOT_LEAK", "QQBot token-value"),
    )

    encoded = json.dumps(report, ensure_ascii=False)

    assert "DO_NOT_LEAK" not in encoded
    assert "token-value" not in encoded
    assert "***" in encoded


def test_iter_json_urls_accepts_list_and_tuple_values():
    module = _load_probe_module()

    urls = module._iter_json_urls(
        [
            "https://example.com/from-list.jpg",
            ("https://example.com/from-tuple.mp4",),
            {"nested": "https://example.com/from-dict.gif"},
        ]
    )

    assert urls == [
        "https://example.com/from-list.jpg",
        "https://example.com/from-tuple.mp4",
        "https://example.com/from-dict.gif",
    ]


def test_cli_dry_run_does_not_require_credentials(tmp_path: Path):
    db_path = tmp_path / "rsshub.db"
    _create_history_db(db_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT_PATH),
            "--db",
            str(db_path),
            "--mode",
            "dry-run",
            "--limit",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["mode"] == "dry-run"
    assert payload["cases"][0]["history_id"] == 1
    assert payload["results"] == []


def test_build_upload_payload_can_use_downloaded_file_data():
    module = _load_probe_module()

    payload = module.build_upload_payload(
        url="https://example.com/media.mp4",
        file_type=module.FILE_TYPE_VIDEO,
        openid="openid-1",
        group_openid=None,
        file_bytes=b"abc",
    )

    assert payload["openid"] == "openid-1"
    assert payload["file_type"] == module.FILE_TYPE_VIDEO
    assert payload["file_data"] == "YWJj"
    assert "url" not in payload


def test_infer_file_type_uses_nested_proxy_url_extension():
    module = _load_probe_module()

    file_type = module.infer_file_type(
        "https://proxy.atri.rodeo?url=https://example.com/media.jpg"
    )

    assert file_type == module.FILE_TYPE_IMAGE


class _FakeContent:
    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        for chunk in self._chunks:
            yield chunk


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
    ):
        self.status = status
        self.headers = headers or {}
        self.content = _FakeContent(chunks or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _FakeSession:
    def __init__(self, response: _FakeResponse):
        self._response = response

    def get(self, _url: str):
        return self._response


def test_download_bytes_rejects_content_length_over_limit():
    module = _load_probe_module()
    session = _FakeSession(
        _FakeResponse(headers={"Content-Length": "6"}, chunks=[b"abcdef"])
    )

    async def run():
        await module._download_bytes(
            session,
            "https://example.com/huge.bin",
            max_bytes=5,
        )

    try:
        asyncio.run(run())
    except RuntimeError as exc:
        assert "download exceeds limit" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_download_bytes_rejects_stream_that_exceeds_limit():
    module = _load_probe_module()
    session = _FakeSession(_FakeResponse(chunks=[b"abc", b"def"]))

    async def run():
        await module._download_bytes(
            session,
            "https://example.com/huge.bin",
            max_bytes=5,
        )

    try:
        asyncio.run(run())
    except RuntimeError as exc:
        assert "download exceeds limit" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
