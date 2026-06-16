from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_KB_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "scripts"
    / "generate_knowledgebase.py"
)


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_knowledgebase", _KB_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    not _KB_SCRIPT.exists(),
    reason="KB generator script lives in external repo; only present in CI envs that vendor it",
)
def test_route_knowledge_generator_writes_metadata(tmp_path, monkeypatch):
    module = _load_generator()
    routes_json = tmp_path / "routes.json"
    output_dir = tmp_path / "kb"
    routes_json.write_text(
        json.dumps(
            {
                "demo": {
                    "name": "Demo",
                    "url": "example.com",
                    "lang": "en",
                    "categories": ["test"],
                    "routes": {
                        "/demo/:id": {
                            "name": "Item",
                            "example": "/demo/1",
                            "parameters": {"id": "item id"},
                        }
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_knowledgebase.py",
            "--input",
            str(routes_json),
            "--output",
            str(output_dir),
            "--source-revision",
            "rev-1",
            "--source-repo",
            "https://example.test/rsshub",
        ],
    )

    assert module.main() == 0

    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    files = {item["path"]: item for item in metadata["files"]}

    assert metadata["version"] == "rev-1"
    assert metadata["source_repo"] == "https://example.test/rsshub"
    assert "index/namespaces.md" in files
    assert "index/demo.md" in files
    assert "docs/routes/demo/demo-id.md" in files
    route_content = (output_dir / "docs/routes/demo/demo-id.md").read_text(
        encoding="utf-8"
    )
    assert (
        files["docs/routes/demo/demo-id.md"]["sha256"]
        == hashlib.sha256(route_content.encode("utf-8")).hexdigest()
    )
