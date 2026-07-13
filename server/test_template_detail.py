"""Tests for GET /api/templates/{id} (run: pytest server/test_template_detail.py)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi.testclient import TestClient  # noqa: E402

import app as smith  # noqa: E402

client = TestClient(smith.app)

DEMO_ENTRY = {
    "id": "demo-genre",
    "name": "Demo Genre",
    "engine": "godot",
    "engineVersion": "4.6.1-stable",
    "description": "Fixture template for the detail endpoint.",
    "status": "validated",
    "skeleton": "genres/demo-genre/skeleton",
    "doc": "genres/demo-genre/TEMPLATE.md",
    "vendoredAddons": [{"name": "DemoKit", "license": "MIT"}],
    "systems": ["godotsmith:templates/save_system"],
    "assetPlanHints": ["Player spritesheet (~32x32 px)"],
}

NO_DOC_ENTRY = {
    "id": "no-doc",
    "name": "No Doc",
    "engine": "godot",
    "engineVersion": "4.6.1-stable",
    "description": "Entry whose doc file does not exist on disk.",
    "status": "draft",
    "skeleton": "genres/no-doc/skeleton",
    "doc": "genres/no-doc/TEMPLATE.md",
}

DOC_TEXT = "# Demo Genre Template\n\n## How to extend\n\nMake it yours.\n"


def _fixture_root(tmp_path: Path) -> Path:
    """Build a minimal godogen root: registry + one template dir with doc+skeleton."""
    root = tmp_path / "godogen"
    demo = root / "templates" / "genres" / "demo-genre"
    (demo / "skeleton").mkdir(parents=True)
    (demo / "TEMPLATE.md").write_text(DOC_TEXT, encoding="utf-8")
    (root / "templates" / "registry.json").write_text(
        json.dumps({"schemaVersion": 1, "templates": [DEMO_ENTRY, NO_DOC_ENTRY]}),
        encoding="utf-8",
    )
    return root


def _point_at(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(smith, "GODOGEN_ROOT", root)
    monkeypatch.setattr(smith, "TEMPLATE_REGISTRY", root / "templates" / "registry.json")


def test_detail_returns_full_entry_doc_and_skeleton_flag(tmp_path, monkeypatch):
    _point_at(monkeypatch, _fixture_root(tmp_path))
    r = client.get("/api/templates/demo-genre")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    data = body["data"]
    # Full registry entry, not the summary-field subset of GET /api/templates.
    assert data["template"] == DEMO_ENTRY
    assert data["template"]["vendoredAddons"][0]["name"] == "DemoKit"
    assert data["doc"] == DOC_TEXT
    assert data["docPath"] == "genres/demo-genre/TEMPLATE.md"
    assert data["skeletonPresent"] is True


def test_detail_missing_doc_is_null_not_error(tmp_path, monkeypatch):
    _point_at(monkeypatch, _fixture_root(tmp_path))
    r = client.get("/api/templates/no-doc")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["doc"] is None
    assert body["data"]["docPath"] == "genres/no-doc/TEMPLATE.md"
    assert body["data"]["skeletonPresent"] is False


def test_detail_unknown_template_404(tmp_path, monkeypatch):
    _point_at(monkeypatch, _fixture_root(tmp_path))
    r = client.get("/api/templates/nope")
    assert r.status_code == 404
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "not_found"
    assert "demo-genre" in body["error"]["message"]


def test_detail_missing_registry_503(tmp_path, monkeypatch):
    _point_at(monkeypatch, tmp_path / "nowhere")
    r = client.get("/api/templates/demo-genre")
    assert r.status_code == 503
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "not_configured"


def test_builtin_route_still_wins_over_dynamic_id(tmp_path, monkeypatch):
    """'builtin' must keep resolving to the IDE prompt-template route."""
    _point_at(monkeypatch, _fixture_root(tmp_path))
    r = client.get("/api/templates/builtin")
    assert r.status_code == 200
    body = r.json()
    # The builtin route returns GAME_TEMPLATES raw — no {ok, data} envelope,
    # and definitely not our not_found envelope.
    assert "ok" not in body
