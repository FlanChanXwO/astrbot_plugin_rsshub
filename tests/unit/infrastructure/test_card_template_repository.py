from __future__ import annotations

import io
import socket
import stat
import zipfile
from pathlib import Path

from aiohttp import web
import pytest

from astrbot_plugin_rsshub.src.application.services.card_template_service import (
    CardTemplateDownloadService,
    CardTemplateInUseError,
    InsecureCardTemplateDownloadError,
    CardTemplateManagementService,
    UnsupportedCardTemplateUrlError,
)
from astrbot_plugin_rsshub.src.infrastructure.templates import (
    AiohttpCardTemplateArchiveDownloader,
    CardTemplateHttpStatusError,
    CardTemplateNetworkError,
    DatabaseCardTemplateReferenceLookup,
    CardTemplatePackageError,
    CardTemplatePackageRepository,
)
from astrbot_plugin_rsshub.src.infrastructure.templates import (
    repository as repository_module,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.database import (
    DatabaseManager,
)
from astrbot_plugin_rsshub.src.infrastructure.persistence.models import (
    BundleORM,
    FeedORM,
    SubORM,
    UserORM,
)


def _archive_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _archive_with_special_member(name: str, *, symlink: bool = False) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("metadata.yaml", _metadata_yaml())
        archive.writestr("template.html", "ok")
        member = zipfile.ZipInfo(name)
        if symlink:
            member.create_system = 3
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(member, "../../outside.txt" if symlink else "outside")
    return buffer.getvalue()


def _archive_with_duplicate_entry() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("metadata.yaml", _metadata_yaml())
        archive.writestr("template.html", "first")
        archive.writestr("template.html", "second")
    return buffer.getvalue()


def _metadata_yaml(
    template_id: str = "astrbot_plugin_rsshub_card_example",
    version: str = "1.2.3",
) -> str:
    return f"""
id: {template_id}
name: Example
version: {version}
author: Tester
description: Example template
repository: https://example.com/templates/example
targets:
  - feed
feed_patterns:
  - example\\.com
""".lstrip()


def test_install_archive_makes_valid_package_retrievable(tmp_path) -> None:
    repository = CardTemplatePackageRepository(tmp_path / "card_templates")

    installed = repository.install_archive(
        _archive_bytes(
            {
                "metadata.yaml": _metadata_yaml(),
                "template.html": "<h1>{{ feed.title }}</h1>",
                "partials/footer.html": "<footer>Footer</footer>",
                "assets/theme.css": "body { color: black; }",
            }
        )
    )

    loaded = repository.get("astrbot_plugin_rsshub_card_example")
    assert loaded == installed
    assert loaded is not None
    assert loaded.metadata.version == "1.2.3"
    assert loaded.root.joinpath("template.html").read_text() == (
        "<h1>{{ feed.title }}</h1>"
    )
    assert loaded.origin == "installed"


def test_install_archive_rejects_parent_path_traversal(tmp_path) -> None:
    repository = CardTemplatePackageRepository(tmp_path / "card_templates")
    archive = _archive_bytes(
        {
            "metadata.yaml": _metadata_yaml(),
            "template.html": "ok",
            "../outside.txt": "escaped",
        }
    )

    with pytest.raises(CardTemplatePackageError, match="路径"):
        repository.install_archive(archive)

    assert not (tmp_path / "outside.txt").exists()


@pytest.mark.parametrize(
    ("member_name", "symlink"),
    [
        ("/absolute.txt", False),
        ("\\absolute.txt", False),
        ("C:\\absolute.txt", False),
        ("assets/link.css", True),
    ],
)
def test_install_archive_rejects_absolute_paths_and_symlinks(
    tmp_path,
    member_name: str,
    symlink: bool,
) -> None:
    repository = CardTemplatePackageRepository(tmp_path / "card_templates")

    with pytest.raises(CardTemplatePackageError, match="路径|符号链接"):
        repository.install_archive(
            _archive_with_special_member(member_name, symlink=symlink)
        )


def test_install_archive_rejects_files_outside_fixed_package_structure(
    tmp_path,
) -> None:
    repository = CardTemplatePackageRepository(tmp_path / "card_templates")

    with pytest.raises(CardTemplatePackageError, match="包结构"):
        repository.install_archive(
            _archive_bytes(
                {
                    "metadata.yaml": _metadata_yaml(),
                    "template.html": "ok",
                    "scripts/setup.py": "raise SystemExit",
                }
            )
        )


def test_install_archive_rejects_ambiguous_duplicate_entries(tmp_path) -> None:
    repository = CardTemplatePackageRepository(tmp_path / "card_templates")

    with pytest.warns(UserWarning, match="Duplicate name"):
        archive = _archive_with_duplicate_entry()
    with pytest.raises(CardTemplatePackageError, match="重复"):
        repository.install_archive(archive)


@pytest.mark.parametrize(
    "files",
    [
        {"metadata.yaml": "id: [", "template.html": "ok"},
        {
            "metadata.yaml": _metadata_yaml().replace("example\\.com", "["),
            "template.html": "ok",
        },
        {"template.html": "ok"},
        {"metadata.yaml": _metadata_yaml()},
    ],
)
def test_install_archive_rejects_invalid_metadata_and_missing_entries(
    tmp_path,
    files: dict[str, str],
) -> None:
    repository = CardTemplatePackageRepository(tmp_path / "card_templates")

    with pytest.raises(CardTemplatePackageError, match="metadata.yaml|template.html"):
        repository.install_archive(_archive_bytes(files))

    assert repository.get("astrbot_plugin_rsshub_card_example") is None


def test_failed_overwrite_preserves_the_previous_package(
    tmp_path,
    monkeypatch,
) -> None:
    repository = CardTemplatePackageRepository(tmp_path / "card_templates")
    repository.install_archive(
        _archive_bytes(
            {
                "metadata.yaml": _metadata_yaml(version="1.0.0"),
                "template.html": "old",
            }
        )
    )
    real_replace = repository_module.os.replace

    def fail_new_package_replace(source, destination) -> None:
        if Path(source).name == "package":
            raise OSError("injected replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(repository_module.os, "replace", fail_new_package_replace)

    with pytest.raises(CardTemplatePackageError, match="覆盖"):
        repository.install_archive(
            _archive_bytes(
                {
                    "metadata.yaml": _metadata_yaml(version="2.0.0"),
                    "template.html": "new",
                }
            )
        )

    loaded = repository.get("astrbot_plugin_rsshub_card_example")
    assert loaded is not None
    assert loaded.metadata.version == "1.0.0"
    assert loaded.root.joinpath("template.html").read_text() == "old"


def test_successful_overwrite_replaces_same_id_package(tmp_path) -> None:
    repository = CardTemplatePackageRepository(tmp_path / "card_templates")
    repository.install_archive(
        _archive_bytes(
            {
                "metadata.yaml": _metadata_yaml(version="1.0.0"),
                "template.html": "old",
            }
        )
    )

    repository.install_archive(
        _archive_bytes(
            {
                "metadata.yaml": _metadata_yaml(version="2.0.0"),
                "template.html": "new",
            }
        )
    )

    loaded = repository.get("astrbot_plugin_rsshub_card_example")
    assert loaded is not None
    assert loaded.metadata.version == "2.0.0"
    assert loaded.root.joinpath("template.html").read_text() == "new"


def test_catalog_lists_builtin_and_installed_packages(tmp_path) -> None:
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    builtin.joinpath("metadata.yaml").write_text(
        _metadata_yaml("astrbot_plugin_rsshub_card_builtin")
    )
    builtin.joinpath("template.html").write_text("builtin")
    repository = CardTemplatePackageRepository(
        tmp_path / "card_templates",
        builtin_package_dirs=[builtin],
    )
    repository.install_archive(
        _archive_bytes(
            {
                "metadata.yaml": _metadata_yaml("astrbot_plugin_rsshub_card_installed"),
                "template.html": "installed",
            }
        )
    )

    packages = repository.list_packages()

    assert [(item.metadata.id, item.origin) for item in packages] == [
        ("astrbot_plugin_rsshub_card_builtin", "builtin"),
        ("astrbot_plugin_rsshub_card_installed", "installed"),
    ]
    assert repository.get("astrbot_plugin_rsshub_card_builtin") == packages[0]


def test_repository_rejects_template_ids_that_escape_storage(tmp_path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    outside.joinpath("metadata.yaml").write_text(_metadata_yaml())
    outside.joinpath("template.html").write_text("must remain")
    repository = CardTemplatePackageRepository(tmp_path / "card_templates")

    with pytest.raises(CardTemplatePackageError, match="模板 ID"):
        repository.get("../outside")
    with pytest.raises(CardTemplatePackageError, match="模板 ID"):
        repository.delete("../outside")

    assert outside.joinpath("template.html").read_text() == "must remain"


def test_repository_rejects_installed_package_directory_symlink(tmp_path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    outside.joinpath("metadata.yaml").write_text(_metadata_yaml())
    outside.joinpath("template.html").write_text("outside")
    storage = tmp_path / "card_templates"
    storage.mkdir()
    storage.joinpath("astrbot_plugin_rsshub_card_example").symlink_to(
        outside,
        target_is_directory=True,
    )
    repository = CardTemplatePackageRepository(storage)

    with pytest.raises(CardTemplatePackageError, match="符号链接"):
        repository.get("astrbot_plugin_rsshub_card_example")


@pytest.mark.asyncio
async def test_delete_rejects_template_with_active_owner_references(tmp_path) -> None:
    class ActiveReferenceLookup:
        async def is_template_in_use(self, template_id: str) -> bool:
            return template_id == "astrbot_plugin_rsshub_card_example"

    repository = CardTemplatePackageRepository(tmp_path / "card_templates")
    repository.install_archive(
        _archive_bytes(
            {
                "metadata.yaml": _metadata_yaml(),
                "template.html": "installed",
            }
        )
    )
    service = CardTemplateManagementService(repository, ActiveReferenceLookup())

    with pytest.raises(CardTemplateInUseError, match="正在被引用"):
        await service.delete_template("astrbot_plugin_rsshub_card_example")

    assert repository.get("astrbot_plugin_rsshub_card_example") is not None


@pytest.mark.asyncio
async def test_delete_removes_unreferenced_installed_template(tmp_path) -> None:
    class EmptyReferenceLookup:
        async def is_template_in_use(self, template_id: str) -> bool:
            return False

    repository = CardTemplatePackageRepository(tmp_path / "card_templates")
    repository.install_archive(
        _archive_bytes(
            {
                "metadata.yaml": _metadata_yaml(),
                "template.html": "installed",
            }
        )
    )
    service = CardTemplateManagementService(repository, EmptyReferenceLookup())

    assert await service.delete_template("astrbot_plugin_rsshub_card_example")
    assert repository.get("astrbot_plugin_rsshub_card_example") is None


@pytest.mark.asyncio
async def test_https_download_installs_archive_through_repository(tmp_path) -> None:
    archive = _archive_bytes(
        {
            "metadata.yaml": _metadata_yaml(),
            "template.html": "downloaded",
        }
    )

    class ArchiveDownloader:
        async def download(self, url: str) -> bytes:
            assert url == "https://example.com/example.zip"
            return archive

    repository = CardTemplatePackageRepository(tmp_path / "card_templates")
    service = CardTemplateDownloadService(repository, ArchiveDownloader())

    installed = await service.install_from_url(
        "https://example.com/example.zip",
        allow_insecure_http=False,
    )

    assert installed.metadata.id == "astrbot_plugin_rsshub_card_example"
    assert installed.root.joinpath("template.html").read_text() == "downloaded"


@pytest.mark.parametrize(
    ("url", "error_type"),
    [
        ("ftp://example.com/example.zip", UnsupportedCardTemplateUrlError),
        ("file:///tmp/example.zip", UnsupportedCardTemplateUrlError),
        ("http://example.com/example.zip", InsecureCardTemplateDownloadError),
    ],
)
@pytest.mark.asyncio
async def test_download_rejects_unsupported_or_unconfirmed_insecure_urls(
    tmp_path,
    url: str,
    error_type: type[Exception],
) -> None:
    class UnexpectedDownloader:
        async def download(self, requested_url: str) -> bytes:
            raise AssertionError(f"不应下载 {requested_url}")

    repository = CardTemplatePackageRepository(tmp_path / "card_templates")
    service = CardTemplateDownloadService(repository, UnexpectedDownloader())

    with pytest.raises(error_type):
        await service.install_from_url(url, allow_insecure_http=False)


@pytest.mark.asyncio
async def test_http_downloader_reports_status_errors() -> None:
    async def unavailable(_request: web.Request) -> web.Response:
        return web.Response(status=503, text="unavailable")

    app = web.Application()
    app.router.add_get("/template.zip", unavailable)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    downloader = AiohttpCardTemplateArchiveDownloader()
    try:
        with pytest.raises(CardTemplateHttpStatusError) as raised:
            await downloader.download(f"http://127.0.0.1:{port}/template.zip")
    finally:
        await runner.cleanup()

    assert raised.value.status == 503


@pytest.mark.asyncio
async def test_http_downloader_does_not_silently_follow_redirects() -> None:
    archive_requests = 0

    async def redirect(_request: web.Request) -> web.Response:
        raise web.HTTPFound("/archive.zip")

    async def archive(_request: web.Request) -> web.Response:
        nonlocal archive_requests
        archive_requests += 1
        return web.Response(body=b"archive")

    app = web.Application()
    app.router.add_get("/template.zip", redirect)
    app.router.add_get("/archive.zip", archive)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    downloader = AiohttpCardTemplateArchiveDownloader()
    try:
        with pytest.raises(CardTemplateHttpStatusError) as raised:
            await downloader.download(f"http://127.0.0.1:{port}/template.zip")
    finally:
        await runner.cleanup()

    assert raised.value.status == 302
    assert archive_requests == 0


@pytest.mark.asyncio
async def test_http_downloader_reports_network_errors() -> None:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    downloader = AiohttpCardTemplateArchiveDownloader()
    with pytest.raises(CardTemplateNetworkError) as raised:
        await downloader.download(f"http://127.0.0.1:{port}/template.zip")

    assert raised.value.code == "CARD_TEMPLATE_DOWNLOAD_NETWORK_ERROR"


@pytest.mark.asyncio
async def test_confirmed_http_download_installs_real_response(tmp_path) -> None:
    archive = _archive_bytes(
        {
            "metadata.yaml": _metadata_yaml(),
            "template.html": "downloaded over confirmed HTTP",
        }
    )

    async def download(_request: web.Request) -> web.Response:
        return web.Response(body=archive, content_type="application/zip")

    app = web.Application()
    app.router.add_get("/template.zip", download)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    repository = CardTemplatePackageRepository(tmp_path / "card_templates")
    service = CardTemplateDownloadService(
        repository,
        AiohttpCardTemplateArchiveDownloader(),
    )
    try:
        installed = await service.install_from_url(
            f"http://127.0.0.1:{port}/template.zip",
            allow_insecure_http=True,
        )
    finally:
        await runner.cleanup()

    assert installed.root.joinpath("template.html").read_text() == (
        "downloaded over confirmed HTTP"
    )


@pytest.mark.asyncio
async def test_database_reference_lookup_covers_subscriptions_and_bundles(
    tmp_path,
) -> None:
    database = DatabaseManager()
    await database.init(str(tmp_path / "template-references.db"))
    async with database.get_session() as session:
        session.add(UserORM(id="user-1"))
        session.add(FeedORM(id=1, link="https://example.com/feed", title="Feed"))
        await session.commit()
        session.add(
            SubORM(
                user_id="user-1",
                feed_id=1,
                template_id="astrbot_plugin_rsshub_card_subscription",
            )
        )
        session.add(
            BundleORM(
                user_id="user-1",
                name="Bundle",
                target_sessions=["test:Group:1"],
                interval=30,
                template_id="astrbot_plugin_rsshub_card_bundle",
            )
        )
        await session.commit()

    lookup = DatabaseCardTemplateReferenceLookup(database)
    assert await lookup.is_template_in_use("astrbot_plugin_rsshub_card_subscription")
    assert await lookup.is_template_in_use("astrbot_plugin_rsshub_card_bundle")
    assert not await lookup.is_template_in_use("astrbot_plugin_rsshub_card_unused")
    await database.close()
