from __future__ import annotations

from pathlib import Path

from astrbot_plugin_rsshub.src.infrastructure.templates import (
    CardTemplatePackageRepository,
    CardTemplateService,
    get_builtin_card_template_dirs,
)


def _feed_context() -> dict[str, object]:
    return {
        "source": {"type": "feed", "owner_id": 7},
        "feed": {
            "id": 3,
            "title": "Juya AI",
            "link": "https://rsshub.app/juya/ai",
        },
        "bundle": None,
        "feeds": [],
        "entries": [
            {
                "item_key": "entry-1",
                "feed_id": 3,
                "title": "After handler",
                "link": "https://example.com/1",
                "author": "Author 1",
                "published": "2026-08-24T08:00:00+00:00",
                "updated": None,
                "summary": "First transformed summary",
                "content_html": "<p>First transformed content</p>",
                "tags": ["AI"],
                "media_items": [],
            },
            {
                "item_key": "entry-2",
                "feed_id": 3,
                "title": "Second handler result",
                "link": "https://example.com/2",
                "author": "Author 2",
                "published": "2026-08-24T07:00:00+00:00",
                "updated": None,
                "summary": "Second transformed summary",
                "content_html": "<p>Second transformed content</p>",
                "tags": [],
                "media_items": [],
            },
        ],
        "document": {
            "text": "First transformed content\n\nSecond transformed content",
            "rss_xml": "",
        },
        "meta": {
            "batch_id": 11,
            "rendered_at": "2026-08-24T08:00:00+00:00",
        },
    }


def _bundle_context() -> dict[str, object]:
    context = _feed_context()
    context.update(
        {
            "source": {"type": "bundle", "owner_id": 21},
            "feed": None,
            "bundle": {"id": 21, "name": "AI sources"},
            "feeds": [
                {
                    "id": 3,
                    "title": "Source A",
                    "link": "https://example.com/a",
                    "position": 0,
                },
                {
                    "id": 4,
                    "title": "Source B",
                    "link": "https://example.com/b",
                    "position": 1,
                },
            ],
        }
    )
    context["entries"] = [
        {
            **entry,
            "feed_id": feed_id,
        }
        for feed_id, entry in [(3, context["entries"][0]), (4, context["entries"][1])]  # type: ignore[index]
    ]
    context["document"] = {
        "text": "Source A item\n\nSource B item",
        "rss_xml": '<rss version="2.0" />',
    }
    return context


def test_builtin_registry_exposes_feed_and_bundle_packages(tmp_path: Path) -> None:
    package_dirs = get_builtin_card_template_dirs()

    repository = CardTemplatePackageRepository(
        storage_dir=tmp_path / "templates",
        builtin_package_dirs=package_dirs,
    )

    packages = repository.list_packages()
    assert [package.metadata.id for package in packages] == [
        "astrbot_plugin_rsshub_card_bundle",
        "astrbot_plugin_rsshub_card_juya",
    ]
    assert all(package.origin == "builtin" for package in packages)


def test_builtin_metadata_declares_strict_targets_and_feed_matching(
    tmp_path: Path,
) -> None:
    repository = CardTemplatePackageRepository(
        storage_dir=tmp_path / "templates",
        builtin_package_dirs=get_builtin_card_template_dirs(),
    )
    juya = repository.get("astrbot_plugin_rsshub_card_juya")
    bundle = repository.get("astrbot_plugin_rsshub_card_bundle")

    assert juya is not None
    assert juya.metadata.targets == ["feed"]
    assert juya.metadata.matches_owner(
        owner_type="subscription",
        feed_urls=["https://rsshub.app/juya/ai"],
    )
    assert not juya.metadata.matches_owner(
        owner_type="subscription",
        feed_urls=["https://rsshub.app/other"],
    )

    assert bundle is not None
    assert bundle.metadata.targets == ["bundle"]
    assert bundle.metadata.feed_patterns == []
    assert bundle.metadata.matches_owner(
        owner_type="bundle",
        feed_urls=["https://example.com/a", "https://example.com/b"],
    )


def test_builtin_templates_render_handler_snapshot_for_multiple_entries_and_sources(
    tmp_path: Path,
) -> None:
    repository = CardTemplatePackageRepository(
        storage_dir=tmp_path / "templates",
        builtin_package_dirs=get_builtin_card_template_dirs(),
    )
    service = CardTemplateService()

    juya = repository.get("astrbot_plugin_rsshub_card_juya")
    bundle = repository.get("astrbot_plugin_rsshub_card_bundle")
    assert juya is not None
    assert bundle is not None

    juya_html = service.render(service.snapshot(juya), _feed_context())
    bundle_html = service.render(service.snapshot(bundle), _bundle_context())

    assert "After handler" in juya_html
    assert "Second handler result" in juya_html
    assert "Source A" in bundle_html
    assert "Source B" in bundle_html
    assert "After handler" in bundle_html
    assert "Second handler result" in bundle_html
    assert "{{" not in juya_html
    assert "{{" not in bundle_html


def test_builtin_packages_have_no_uncontrolled_root_resources(tmp_path: Path) -> None:
    repository = CardTemplatePackageRepository(
        storage_dir=tmp_path / "templates",
        builtin_package_dirs=get_builtin_card_template_dirs(),
    )

    for package in repository.list_packages():
        assert {path.name for path in package.root.iterdir()} <= {
            "metadata.yaml",
            "template.html",
            "partials",
            "assets",
        }
