"""Phase A Task 3 — 자유 본문 PATCH 와 편집 플래그가 없다."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import config
from app.cards import schemas
from app.main import app


def test_draft_patch_route_is_gone():
    paths = {(r.path, m) for r in app.routes for m in getattr(r, "methods", set())}
    assert ("/cards/{card_id}/draft", "PATCH") not in paths
    spec = TestClient(app).get("/openapi.json").json()
    assert "/cards/{card_id}/draft" not in spec["paths"]


def test_fact_edit_flag_is_gone():
    assert "w_fact_card_edit_enabled" not in config.Settings.model_fields
    assert "fact_edit_enabled" not in schemas.CardDetail.model_fields
    assert not hasattr(schemas, "DraftUpdateRequest")
