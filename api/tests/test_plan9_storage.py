"""계획 9C: Storage 경로 나누기와 묶음 삭제 요청."""
import asyncio

import httpx
import pytest

from app.ingest.preprocess import storage


def test_split_object_path():
    assert storage.split_object_path("sources/1/scan/a.pdf") == ("sources", "1/scan/a.pdf")


def test_split_object_path_rejects_bare_name():
    with pytest.raises(ValueError):
        storage.split_object_path("a.pdf")


def test_delete_objects_batches_by_100_and_skips_empty(monkeypatch):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        sent.append((request.method, request.url.path, json.loads(request.content)["prefixes"]))
        return httpx.Response(200, json=[])

    real = httpx.AsyncClient
    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(storage, "get_settings", lambda: type("S", (), {"supabase_url": "http://sb", "supabase_service_key": "k"})())
    asyncio.run(storage.delete_objects("sources", []))
    assert sent == []
    paths = [f"1/scan/{i}.pdf" for i in range(150)]
    asyncio.run(storage.delete_objects("sources", paths))
    assert [(m, p, len(x)) for m, p, x in sent] == [
        ("DELETE", "/storage/v1/object/sources", 100), ("DELETE", "/storage/v1/object/sources", 50)]


def test_delete_objects_raises_on_non_200(monkeypatch):
    real = httpx.AsyncClient
    monkeypatch.setattr(storage.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(500)), **kw))
    monkeypatch.setattr(storage, "get_settings", lambda: type("S", (), {"supabase_url": "http://sb", "supabase_service_key": "k"})())
    with pytest.raises(RuntimeError):
        asyncio.run(storage.delete_objects("sources", ["1/a.pdf"]))
