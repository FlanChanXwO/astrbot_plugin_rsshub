from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper import FFmpegTool


_PROBE_VIDEO_STREAM_INFO = FFmpegTool._probe_video_stream_info


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


@pytest.fixture(autouse=True)
def _disable_gif_observability_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """转码行为测试只关注 FFmpeg 参数；元数据探测在独立用例覆盖。"""

    async def no_stream_info(*_args, **_kwargs):
        return None

    monkeypatch.setattr(FFmpegTool, "_probe_video_stream_info", no_stream_info)


def _read_expire_ts(meta_path: Path) -> float:
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    return float(payload["expire_ts"])


def _write_expire_ts(meta_path: Path, expire_ts: float) -> None:
    meta_path.write_text(
        json.dumps({"expire_ts": expire_ts}, separators=(",", ":")),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_probe_video_stream_info_reads_only_requested_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"mp4")
    monkeypatch.setattr(FFmpegTool, "ensure_ffprobe_ready", lambda **_kwargs: "ffprobe")

    async def fake_exec(*args, **kwargs):
        assert args[0] == "ffprobe"
        assert "stream=width,height,r_frame_rate" in args
        assert kwargs["stderr"] is asyncio.subprocess.DEVNULL
        return _FakeProcess(
            returncode=0,
            stdout=(
                b'{"streams":[{"width":2160,"height":2880,'
                b'"r_frame_rate":"30000/1001"}]}'
            ),
        )

    monkeypatch.setattr(
        FFmpegTool, "_probe_video_stream_info", _PROBE_VIDEO_STREAM_INFO
    )
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    info = await FFmpegTool._probe_video_stream_info(source)

    assert info is not None
    assert (info.width, info.height) == (2160, 2880)
    assert info.fps == pytest.approx(29.970, abs=0.001)


@pytest.mark.asyncio
async def test_ffmpeg_runner_reads_error_tail_from_tempfile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_exec(*_args, **kwargs):
        kwargs["stderr"].write(b"old-error\n" + (b"x" * 600) + b"tail-error\n")
        return _FakeProcess(returncode=17)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    result = await FFmpegTool._run_ffmpeg(["ffmpeg"], timeout_seconds=60)

    assert result is not None
    assert result.returncode == 17
    assert result.stderr_tail.endswith("tail-error\n")
    assert len(result.stderr_tail) <= FFmpegTool._FFMPEG_ERROR_TAIL_LOG_CHARS


@pytest.mark.asyncio
async def test_ffmpeg_runner_timeout_kills_and_waits_for_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PendingProcess:
        returncode: int | None = None
        killed = False

        async def wait(self) -> None:
            return None

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

    process = PendingProcess()

    async def fake_exec(*_args, **_kwargs):
        return process

    async def fake_wait_for(awaitable, **_kwargs):
        awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    assert await FFmpegTool._run_ffmpeg(["ffmpeg"], timeout_seconds=60) is None
    assert process.killed is True


@pytest.mark.asyncio
async def test_gif_transcode_cancellation_kills_process_and_cleans_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class BlockingProcess:
        returncode: int | None = None

        def __init__(self) -> None:
            self.killed = False
            self.wait_started = asyncio.Event()
            self._finished = asyncio.Event()

        async def wait(self) -> None:
            self.wait_started.set()
            await self._finished.wait()

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9
            self._finished.set()

    source = tmp_path / "source.mp4"
    source.write_bytes(b"mp4")
    output_paths: list[Path] = []
    process = BlockingProcess()
    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **_kwargs: "ffmpeg")

    async def fake_exec(*args, **_kwargs):
        output_path = Path(args[-1])
        output_paths.append(output_path)
        output_path.write_bytes(b"partial gif")
        return process

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    task = asyncio.create_task(FFmpegTool.transcode_to_gif(source, cache_enabled=False))
    await process.wait_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed is True
    assert output_paths
    assert all(not path.exists() for path in output_paths)


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
@pytest.mark.parametrize(
    ("profile", "expected_filter_parts"),
    [
        ("compatibility", ("960", "fps=15", "palettegen=max_colors=128")),
        ("balanced", ("1280", "fps=20", "palettegen=max_colors=256")),
        ("quality", ("scale=iw:-1", "fps=30", "palettegen=max_colors=256")),
    ],
)
async def test_gif_transcode_profiles_build_expected_filters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    profile: str,
    expected_filter_parts: tuple[str, ...],
) -> None:
    """三档应在 palette 之前按各自尺寸、帧率与颜色数生成滤镜。"""
    source = tmp_path / "source.mp4"
    source.write_bytes(b"mp4")
    captured: dict[str, object] = {}

    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **kwargs: "ffmpeg")

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        Path(args[-1]).write_bytes(b"gif")
        return _FakeProcess(returncode=0)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    output = await FFmpegTool.transcode_to_gif(
        source,
        cache_enabled=False,
        profile=profile,
    )

    try:
        assert output is not None
        args = list(captured["args"])
        vf_expr = str(args[args.index("-vf") + 1])
        assert all(part in vf_expr for part in expected_filter_parts)
        if profile == "quality":
            assert vf_expr.startswith("fps=30,scale=iw:-1:flags=lanczos,")
        else:
            assert vf_expr.index("scale=") < vf_expr.index("fps=")
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
async def test_gif_transcode_cache_isolated_by_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"mp4")
    outputs: list[Path] = []
    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **_kwargs: "ffmpeg")
    monkeypatch.setattr(
        "astrbot_plugin_rsshub.src.infrastructure.utils.ffmpeg_helper.get_plugin_cache_dir",
        lambda _part: tmp_path / "gif",
    )

    async def fake_exec(*args, **_kwargs):
        output_path = Path(args[-1])
        outputs.append(output_path)
        output_path.write_bytes(f"gif-{len(outputs)}".encode())
        return _FakeProcess(returncode=0)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    compatibility = await FFmpegTool.transcode_to_gif(source, profile="compatibility")
    balanced = await FFmpegTool.transcode_to_gif(source, profile="balanced")
    compatibility_hit = await FFmpegTool.transcode_to_gif(
        source,
        profile="compatibility",
    )

    assert compatibility is not None
    assert balanced is not None
    assert compatibility != balanced
    assert compatibility_hit == compatibility
    assert outputs == [compatibility, balanced]


@pytest.mark.asyncio
async def test_compressed_gif_candidates_do_not_exceed_selected_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"mp4")
    filters: list[str] = []
    monkeypatch.setattr(FFmpegTool, "ensure_ffmpeg_ready", lambda **_kwargs: "ffmpeg")

    async def fake_exec(*args, **_kwargs):
        filters.append(str(args[args.index("-vf") + 1]))
        Path(args[-1]).write_bytes(b"too large")
        return _FakeProcess(returncode=0)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    result = await FFmpegTool.transcode_to_gif_under_limit(
        source,
        max_bytes=1,
        cache_enabled=False,
        profile="compatibility",
    )

    assert result is None
    assert len(filters) == 8
    assert all("palettegen=max_colors=128" in vf_expr for vf_expr in filters)
    assert all("fps=15" in vf_expr or "fps=7" in vf_expr for vf_expr in filters)
    assert all("fps=30" not in vf_expr for vf_expr in filters)
    assert all(
        any(f"{edge})" in vf_expr for edge in (720, 480, 336, 240))
        for vf_expr in filters
    )


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
