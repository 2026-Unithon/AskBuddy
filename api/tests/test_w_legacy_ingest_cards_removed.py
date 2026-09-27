"""레거시 /ingest/cards/* 공개 경로가 제거됐는지 확인한다.

이 경로들은 publish_cards 를 거치지 않고 공개 포인터·is_verified·card_embeddings 를
직접 바꿨다. 공개 경로는 /cards/{id}/approve(publish_cards) 하나만 남는다.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

# lifespan 을 돌리지 않는다(with 블록 없음). 라우팅 단계의 404/405 만 본다
client = TestClient(app)


@pytest.mark.parametrize("method,path", [
    ("POST", "/ingest/cards/1/approve"),
    ("POST", "/ingest/cards/1/unapprove"),
    ("PATCH", "/ingest/cards/1"),
    ("POST", "/ingest/cards/approve"),
])
def test_legacy_ingest_card_routes_are_gone(method, path):
    res = client.request(method, path, json={"card_ids": [1], "title": "t", "content": "c"})
    assert res.status_code in (404, 405)


def test_no_ingest_cards_route_in_openapi():
    # 이 FastAPI 버전은 include_router 를 묶음으로 두므로 OpenAPI 경로표로 확인한다
    paths = app.openapi()["paths"]
    assert "/ingest/review" in paths  # 조회용 GET 은 남는다
    assert not any(p.startswith("/ingest/cards") for p in paths)
