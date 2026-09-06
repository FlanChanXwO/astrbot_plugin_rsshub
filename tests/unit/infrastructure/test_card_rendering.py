"""卡片模板渲染与持久化产物测试。"""

from pathlib import Path

import pytest
from astrbot_plugin_rsshub.src.domain.entities.card_rendering import CardRenderContext
from astrbot_plugin_rsshub.src.domain.entities.card_template import (
    CardTemplateMetadata,
)
from astrbot_plugin_rsshub.src.infrastructure.rendering.html_image_renderer import (
    AstrBotHtmlImageRenderer,
)
from astrbot_plugin_rsshub.src.infrastructure.templates.rendering import (
    CardTemplateRenderError,
    CardTemplateService,
)
from astrbot_plugin_rsshub.src.infrastructure.templates.repository import (
    CardTemplatePackage,
)
from pydantic import ValidationError


class RecordingT2I:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def render_custom_template(self, html: str, data: dict, **kwargs):
        self.calls.append({"html": html, "data": data, **kwargs})
        return self.result


def _context(**changes: object) -> dict[str, object]:
    context: dict[str, object] = {
        "source": {"type": "feed", "owner_id": 1},
        "feed": {"id": 1, "title": "News", "link": "https://example.com/feed"},
        "bundle": None,
        "feeds": [],
        "entries": [],
        "document": {"text": "", "rss_xml": ""},
        "meta": {"batch_id": 1, "rendered_at": "2026-08-24T00:00:00+00:00"},
    }
    context.update(changes)
    return context


def _package(tmp_path: Path, template: str) -> CardTemplatePackage:
    (tmp_path / "template.html").write_text(template, encoding="utf-8")
    metadata = CardTemplateMetadata(
        id="astrbot_plugin_rsshub_card_test",
        name="Test",
        version="1.0.0",
        author="Tester",
        description="Test template",
        repository="https://example.com/template",
        targets=["feed", "bundle"],
    )
    return CardTemplatePackage(metadata=metadata, root=tmp_path, origin="installed")


def test_card_template_service_escapes_context_values(tmp_path: Path) -> None:
    package = _package(tmp_path, "<article>{{ document.text }}</article>")
    service = CardTemplateService()

    snapshot = service.snapshot(package)
    html = service.render(
        snapshot,
        _context(document={"text": "<script>alert(1)</script>", "rss_xml": ""}),
    )

    assert html == "<article>&lt;script&gt;alert(1)&lt;/script&gt;</article>"


def test_card_template_service_reports_missing_context(tmp_path: Path) -> None:
    package = _package(tmp_path, "<h1>{{ feed.title }}</h1>{{ missing.value }}")
    service = CardTemplateService()

    with pytest.raises(CardTemplateRenderError, match="模板渲染失败"):
        service.render(service.snapshot(package), _context())


def test_snapshot_supports_macros_includes_filters_and_packaged_assets(
    tmp_path: Path,
) -> None:
    partials = tmp_path / "partials"
    assets = tmp_path / "assets"
    partials.mkdir()
    assets.mkdir()
    (partials / "entry.html").write_text(
        "{% macro title(value) %}<strong>{{ value|upper }}</strong>{% endmacro %}"
        "{{ title(entries[0].title) }}",
        encoding="utf-8",
    )
    (assets / "dot.svg").write_bytes(b"<svg></svg>")
    package = _package(
        tmp_path,
        '{% include "partials/entry.html" %}'
        "<img src=\"{{ asset('dot.svg') }}\">"
        "<small>{{ template.id }}</small>",
    )
    service = CardTemplateService()

    snapshot = service.snapshot(package)
    (tmp_path / "template.html").write_text("overwritten", encoding="utf-8")
    (partials / "entry.html").write_text("overwritten", encoding="utf-8")
    html = service.render(
        snapshot,
        _context(
            entries=[
                {
                    "item_key": "entry-1",
                    "feed_id": 1,
                    "title": "news",
                    "link": "https://example.com/entry",
                }
            ]
        ),
    )

    assert html.startswith('<strong>NEWS</strong><img src="data:image/svg+xml;base64,')
    assert html.endswith('"><small>astrbot_plugin_rsshub_card_test</small>')


@pytest.mark.parametrize("directory_name", ["assets", "partials"])
def test_snapshot_rejects_symlinked_package_directory_root(
    tmp_path: Path,
    directory_name: str,
) -> None:
    package_root = tmp_path / "package"
    package_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    (package_root / directory_name).symlink_to(outside, target_is_directory=True)
    package = _package(package_root, "ok")

    with pytest.raises(CardTemplateRenderError, match="符号链接"):
        CardTemplateService().snapshot(package)


def test_snapshot_rejects_dangling_package_directory_symlink(tmp_path: Path) -> None:
    package_root = tmp_path / "package"
    package_root.mkdir()
    (package_root / "assets").symlink_to(
        tmp_path / "missing",
        target_is_directory=True,
    )
    package = _package(package_root, "ok")

    with pytest.raises(CardTemplateRenderError, match="符号链接"):
        CardTemplateService().snapshot(package)


def test_card_template_service_rejects_host_objects(tmp_path: Path) -> None:
    package = _package(tmp_path, "{{ source.__class__ }}")
    service = CardTemplateService()

    with pytest.raises(CardTemplateRenderError, match="JSON-safe"):
        service.render(service.snapshot(package), {"source": object()})


def test_card_context_rejects_mixed_feed_and_bundle_shapes() -> None:
    with pytest.raises(ValidationError, match="Bundle 上下文"):
        CardRenderContext.model_validate(
            _context(
                source={"type": "bundle", "owner_id": 1},
                bundle={"id": 1, "name": "Daily"},
            )
        )


@pytest.mark.parametrize(
    ("entries", "rendered_at"),
    [
        (
            [{"item_key": "entry-1", "feed_id": 1, "published": "yesterday"}],
            "2026-08-24T00:00:00+00:00",
        ),
        ([], "not-an-iso-time"),
        ([], "2026-08-24T00:00:00"),
        (
            [{"item_key": "entry-1", "feed_id": 1, "published": 1787531400}],
            "2026-08-24T00:00:00+00:00",
        ),
    ],
)
def test_card_context_rejects_invalid_or_timezone_naive_iso_times(
    entries: list[dict[str, object]],
    rendered_at: str,
) -> None:
    with pytest.raises(ValidationError):
        CardRenderContext.model_validate(
            _context(entries=entries, meta={"batch_id": 1, "rendered_at": rendered_at})
        )


def test_card_context_serializes_optional_iso_times_for_templates() -> None:
    context = CardRenderContext.model_validate(
        _context(
            entries=[
                {
                    "item_key": "entry-1",
                    "feed_id": 1,
                    "published": "2026-08-24T08:30:00+08:00",
                    "updated": None,
                }
            ]
        )
    )

    serialized = context.model_dump(mode="json")

    assert serialized["entries"][0]["published"] == "2026-08-24T08:30:00+08:00"
    assert serialized["entries"][0]["updated"] is None
    assert serialized["meta"]["rendered_at"] == "2026-08-24T00:00:00Z"


@pytest.mark.asyncio
async def test_astrbot_image_renderer_passes_completed_html_to_t2i() -> None:
    t2i = RecordingT2I(b"png")

    result = await AstrBotHtmlImageRenderer(t2i=t2i).render("<h1>done</h1>")

    assert result == b"png"
    assert t2i.calls == [
        {
            "html": "<h1>done</h1>",
            "data": {},
            "return_url": False,
            "options": {"full_page": True, "type": "png", "scale": "css"},
        }
    ]
