from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper import FFmpegTool


class _FakeProcess:
    def __init__(
        self,
        *,
        returncode: int,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:
        return None

    async def wait(self) -> None:
        return None


def _read_expire_ts(meta_path: Path) -> float:
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    return float(payload["expire_ts"])


def _write_expire_ts(meta_path: Path, expire_ts: float) -> None:
    meta_path.write_text(
        json.dumps({"expire_ts": expire_ts}, separators=(",", ":")),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_has_valid_video_stream_accepts_positive_duration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    media = tmp_path / "video.mp4"
    media.write_bytes(b"mp4")

    monkeypatch.setattr(FFmpegTool, "ensure_ffprobe_ready", lambda **kwargs: "ffprobe")

    async def fake_exec(*args, **kwargs):
        return _FakeProcess(returncode=0, stdout=b"video\n12.345\n")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    assert await FFmpegTool.has_valid_video_stream(media) is True


@pytest.mark.asyncio
async def test_has_valid_video_stream_rejects_zero_duration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    media = tmp_path / "video.mp4"
    media.write_bytes(b"mp4")

    monkeypatch.setattr(FFmpegTool, "ensure_ffprobe_ready", lambda **kwargs: "ffprobe")

    async def fake_exec(*args, **kwargs):
        return _FakeProcess(returncode=0, stdout=b"video\n0.000000\n")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    assert await FFmpegTool.has_valid_video_stream(media) is False


@pytest.mark.asyncio
async def test_m3u8_download_rejects_invalid_ffmpeg_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "out.mp4"

    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **kwargs: "ffmpeg")

    async def fake_exec(*args, **kwargs):
        output.write_bytes(b"broken mp4")
        return _FakeProcess(returncode=0, stdout=b"", stderr=b"")

    async def fake_validate(*args, **kwargs):
        return False

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr(FFmpegTool, "has_valid_video_stream", fake_validate)

    assert (
        await FFmpegTool.download_m3u8_to_mp4(
            "https://example.com/video.m3u8",
            output,
        )
        is False
    )
    assert not output.exists()


@pytest.mark.asyncio
async def test_m3u8_download_passes_proxy_to_ffmpeg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "out.mp4"
    captured: dict[str, object] = {}

    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **kwargs: "ffmpeg")

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs.get("env")
        output.write_bytes(b"valid mp4")
        return _FakeProcess(returncode=0, stdout=b"", stderr=b"")

    async def fake_validate(*args, **kwargs):
        return True

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr(FFmpegTool, "has_valid_video_stream", fake_validate)

    assert (
        await FFmpegTool.download_m3u8_to_mp4(
            "https://example.com/video.m3u8",
            output,
            proxy="localhost:7890",
        )
        is True
    )

    args = list(captured["args"])
    assert args[args.index("-http_proxy") + 1] == "http://localhost:7890"
    assert args.index("-http_proxy") < args.index("-i")
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["HTTP_PROXY"] == "http://localhost:7890"
    assert env["HTTPS_PROXY"] == "http://localhost:7890"
    assert env["http_proxy"] == "http://localhost:7890"
    assert env["https_proxy"] == "http://localhost:7890"


@pytest.mark.asyncio
async def test_gif_transcode_cache_disabled_uses_temp_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"mp4")
    cache_dir_calls: list[str] = []
    exec_outputs: list[Path] = []

    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **kwargs: "ffmpeg")

    def fail_cache_dir(part: str):
        cache_dir_calls.append(part)
        raise AssertionError(f"cache disabled should not use cache/{part}")

    async def fake_exec(*args, **kwargs):
        output_path = Path(args[-1])
        exec_outputs.append(output_path)
        output_path.write_bytes(b"gif")
        return _FakeProcess(returncode=0)

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper.get_plugin_cache_dir",
        fail_cache_dir,
    )
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    output = await FFmpegTool.transcode_to_gif(source, cache_enabled=False)

    try:
        assert output == exec_outputs[0]
        assert output is not None
        assert output.exists()
        assert output.name.startswith("rsshub_gif_")
        assert cache_dir_calls == []
    finally:
        if output is not None:
            output.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_gif_transcode_cache_refreshes_expires_and_collects_old_entries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"mp4")
    cache_root = tmp_path / "gif"
    exec_outputs: list[Path] = []

    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **kwargs: "ffmpeg")
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper.get_plugin_cache_dir",
        lambda part: tmp_path / part,
    )

    async def fake_exec(*args, **kwargs):
        output_path = Path(args[-1])
        exec_outputs.append(output_path)
        output_path.write_bytes(f"gif-{len(exec_outputs)}".encode())
        return _FakeProcess(returncode=0)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    first = await FFmpegTool.transcode_to_gif(source, cache_ttl_seconds=100)
    assert first is not None
    meta_path = first.with_suffix(".meta")
    assert meta_path.exists()

    old_expire = time.time() + 1
    _write_expire_ts(meta_path, old_expire)
    hit = await FFmpegTool.transcode_to_gif(source, cache_ttl_seconds=100)

    assert hit == first
    assert exec_outputs == [first]
    assert _read_expire_ts(meta_path) > old_expire + 50

    old_gif = cache_root / "old.gif"
    old_meta = cache_root / "old.meta"
    old_gif.write_bytes(b"old")
    _write_expire_ts(old_meta, 1.0)
    _write_expire_ts(meta_path, 1.0)

    rerun = await FFmpegTool.transcode_to_gif(source, cache_ttl_seconds=100)

    assert rerun == first
    assert exec_outputs == [first, first]
    assert first.read_bytes() == b"gif-2"
    assert _read_expire_ts(meta_path) > time.time()
    assert not old_gif.exists()
    assert not old_meta.exists()


@pytest.mark.asyncio
async def test_gif_compress_cache_disabled_uses_temp_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"mp4")
    cache_dir_calls: list[str] = []
    exec_outputs: list[Path] = []

    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **kwargs: "ffmpeg")

    def fail_cache_dir(part: str):
        cache_dir_calls.append(part)
        raise AssertionError(f"cache disabled should not use cache/{part}")

    async def fake_exec(*args, **kwargs):
        output_path = Path(args[-1])
        exec_outputs.append(output_path)
        output_path.write_bytes(b"gif")
        return _FakeProcess(returncode=0)

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper.get_plugin_cache_dir",
        fail_cache_dir,
    )
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    output = await FFmpegTool.transcode_to_gif_under_limit(
        source,
        max_bytes=10,
        cache_enabled=False,
    )

    try:
        assert output == exec_outputs[0]
        assert output is not None
        assert output.exists()
        assert output.name.startswith("rsshub_gif_compressed_")
        assert cache_dir_calls == []
    finally:
        if output is not None:
            output.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_gif_compress_cache_refreshes_and_reruns_expired_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"mp4")
    exec_outputs: list[Path] = []

    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **kwargs: "ffmpeg")
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper.get_plugin_cache_dir",
        lambda part: tmp_path / part,
    )

    async def fake_exec(*args, **kwargs):
        output_path = Path(args[-1])
        exec_outputs.append(output_path)
        output_path.write_bytes(b"gif")
        return _FakeProcess(returncode=0)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    first = await FFmpegTool.transcode_to_gif_under_limit(
        source,
        max_bytes=100,
        cache_ttl_seconds=100,
    )
    assert first is not None
    meta_path = first.with_suffix(".meta")

    old_expire = time.time() + 1
    _write_expire_ts(meta_path, old_expire)
    hit = await FFmpegTool.transcode_to_gif_under_limit(
        source,
        max_bytes=100,
        cache_ttl_seconds=100,
    )

    assert hit == first
    assert exec_outputs == [first]
    assert _read_expire_ts(meta_path) > old_expire + 50

    _write_expire_ts(meta_path, 1.0)
    rerun = await FFmpegTool.transcode_to_gif_under_limit(
        source,
        max_bytes=100,
        cache_ttl_seconds=100,
    )

    assert rerun == first
    assert exec_outputs == [first, first]


@pytest.mark.asyncio
async def test_mp4_transcode_cache_disabled_uses_temp_output_without_cache_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.webm"
    source.write_bytes(b"webm")
    cache_dir_calls: list[str] = []
    exec_outputs: list[Path] = []

    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **kwargs: "ffmpeg")

    def fail_cache_dir(part: str):
        cache_dir_calls.append(part)
        raise AssertionError(f"cache disabled should not use cache/{part}")

    async def fake_exec(*args, **kwargs):
        output_path = Path(args[-1])
        exec_outputs.append(output_path)
        output_path.write_bytes(b"mp4")
        return _FakeProcess(returncode=0)

    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper.get_plugin_cache_dir",
        fail_cache_dir,
    )
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    output = await FFmpegTool.transcode_to_mp4(source, cache_enabled=False)

    try:
        assert output == exec_outputs[0]
        assert output is not None
        assert output.exists()
        assert output.name.startswith("rsshub_video_transcoded_")
        assert cache_dir_calls == []
    finally:
        if output is not None:
            output.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_mp4_transcode_cache_refreshes_and_reruns_expired_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.webm"
    source.write_bytes(b"webm")
    cache_root = tmp_path / "qq_video"
    exec_outputs: list[Path] = []

    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **kwargs: "ffmpeg")
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper.get_plugin_cache_dir",
        lambda part: tmp_path / part,
    )

    async def fake_exec(*args, **kwargs):
        output_path = Path(args[-1])
        exec_outputs.append(output_path)
        output_path.write_bytes(f"mp4-{len(exec_outputs)}".encode())
        return _FakeProcess(returncode=0)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    first = await FFmpegTool.transcode_to_mp4(source, cache_ttl_seconds=100)
    assert first is not None
    meta_path = first.with_suffix(".meta")

    old_expire = time.time() + 1
    _write_expire_ts(meta_path, old_expire)
    hit = await FFmpegTool.transcode_to_mp4(source, cache_ttl_seconds=100)

    assert hit == first
    assert exec_outputs == [first]
    assert _read_expire_ts(meta_path) > old_expire + 50

    old_mp4 = cache_root / "old.mp4"
    old_meta = cache_root / "old.meta"
    old_mp4.write_bytes(b"old")
    _write_expire_ts(old_meta, 1.0)
    _write_expire_ts(meta_path, 1.0)

    rerun = await FFmpegTool.transcode_to_mp4(source, cache_ttl_seconds=100)

    assert rerun == first
    assert exec_outputs == [first, first]
    assert first.read_bytes() == b"mp4-2"
    assert not old_mp4.exists()
    assert not old_meta.exists()


@pytest.mark.asyncio
async def test_mp4_transcode_cache_reruns_stale_entry_without_meta(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.webm"
    source.write_bytes(b"webm")
    exec_outputs: list[Path] = []

    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **kwargs: "ffmpeg")
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper.get_plugin_cache_dir",
        lambda part: tmp_path / part,
    )

    async def fake_exec(*args, **kwargs):
        output_path = Path(args[-1])
        exec_outputs.append(output_path)
        output_path.write_bytes(f"mp4-{len(exec_outputs)}".encode())
        return _FakeProcess(returncode=0)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    first = await FFmpegTool.transcode_to_mp4(source, cache_ttl_seconds=1)
    assert first is not None
    first.with_suffix(".meta").unlink()
    os.utime(first, (1, 1))

    second = await FFmpegTool.transcode_to_mp4(source, cache_ttl_seconds=1)

    assert second == first
    assert exec_outputs == [first, first]
    assert second.read_bytes() == b"mp4-2"
    assert second.with_suffix(".meta").exists()


def test_transcode_cache_gc_removes_stale_no_meta_skip_path(tmp_path: Path) -> None:
    output_path = tmp_path / "current.mp4"
    output_path.write_bytes(b"old")
    os.utime(output_path, (1, 1))

    removed = FFmpegTool._gc_transcode_cache(
        tmp_path,
        suffixes=(".mp4",),
        now_ts=100.0,
        cache_ttl_seconds=10,
        skip_paths={output_path},
    )

    assert removed == 1
    assert not output_path.exists()


def test_configure_bundler_clears_bundled_cache_when_switching_to_system() -> None:
    FFmpegTool._ffmpeg_source = "auto"
    FFmpegTool._ffmpeg_exe_cache = "/tmp/bundled-ffmpeg"
    FFmpegTool._ffmpeg_exe_cache_source = "bundled"
    FFmpegTool._ffprobe_exe_cache = "/tmp/bundled-ffprobe"
    FFmpegTool._ffprobe_exe_cache_source = "bundled"

    FFmpegTool.configure_bundler(ffmpeg_source="system")

    assert FFmpegTool._ffmpeg_source == "system"
    assert FFmpegTool._ffmpeg_exe_cache is None
    assert FFmpegTool._ffmpeg_exe_cache_source is None
    assert FFmpegTool._ffprobe_exe_cache is None
    assert FFmpegTool._ffprobe_exe_cache_source is None

    FFmpegTool.configure_bundler(ffmpeg_source="auto")
