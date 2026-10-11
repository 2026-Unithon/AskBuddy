"""Storage 정리 스크립트의 삭제 대상 계획 (순수 함수만 검증한다. 실제 Storage 는 건드리지 않는다)."""
import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / "scripts" / "wipe_storage_sources.py"
_spec = importlib.util.spec_from_file_location("wipe_storage_sources_test", _path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
plan_deletions = _mod.plan_deletions


def test_plan_only_own_store_prefix():
    objects = [{"name": "7/voice/a.m4a"}, {"name": "70/voice/b.m4a"}, {"name": "7/scan/c.pdf"},
               {"name": "../7/x"}, {"name": "8/kakao/d.txt"}]
    assert plan_deletions(objects, store_id=7) == ["7/scan/c.pdf", "7/voice/a.m4a"]


def test_plan_reads_path_key_of_list_store_objects():
    # list_store_objects 는 경로를 "path" 키로 돌려준다
    objects = [{"path": "7/frames/1/0001.jpg", "bytes": 10}, {"path": "9/frames/x.jpg", "bytes": 1}]
    assert plan_deletions(objects, store_id=7) == ["7/frames/1/0001.jpg"]


def test_plan_drops_traversal_and_empty_names():
    objects = [{"name": "7/../8/a"}, {"name": "7/"}, {"name": ""}, {}, {"name": "7//a"}]
    assert plan_deletions(objects, store_id=7) == []


def test_plan_dedupes():
    objects = [{"name": "7/a/b"}, {"name": "7/a/b"}]
    assert plan_deletions(objects, store_id=7) == ["7/a/b"]


class _FakeDb:
    """sources.file_url 조회만 흉내 낸다. 매장별 file_url 목록."""

    def __init__(self, by_store):
        self.by_store = by_store
        self.queries = []
        self.closed = False

    async def fetch(self, query, *args):
        self.queries.append((query, args))
        if "from sources" in query:
            assert "store_id = $1" in query
            return [{"file_url": u} for u in self.by_store.get(args[0], [])]
        if "from stores" in query:
            return [{"store_id": k} for k in sorted(self.by_store)]
        raise AssertionError(query)

    async def close(self):
        self.closed = True


def _fake_db_factory(by_store, holder=None):
    async def connect():
        db = _FakeDb(by_store)
        if holder is not None:
            holder.append(db)
        return db
    return connect


# ── 가짜 HTTP 계층 (실제 Storage 호출 없음) ──────────────────────────
import asyncio  # noqa: E402

import httpx  # noqa: E402

_H = {"Authorization": "Bearer x"}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _list(client, prefix="7"):
    return _mod.list_objects_recursive(client, base_url="http://t", bucket="b", headers=_H, prefix=prefix)


def test_list_recurses_into_folders():
    import json
    tree = {
        "7": [{"name": "frames", "id": None}, {"name": "voice", "id": None}],
        "7/frames": [{"name": "12", "id": None}],
        "7/frames/12": [{"name": "0001.jpg", "id": "a", "metadata": {"size": 5}}],
        "7/voice": [{"name": "a.m4a", "id": "b", "metadata": {"size": 7}}],
    }

    def handler(req):
        return httpx.Response(200, json=tree[json.loads(req.content)["prefix"]])

    async def run():
        async with _client(handler) as c:
            return await _list(c)

    objs = asyncio.run(run())
    assert sorted(o["path"] for o in objs) == ["7/frames/12/0001.jpg", "7/voice/a.m4a"]
    assert sum(o["bytes"] for o in objs) == 12


def test_list_error_raises_with_status():
    async def run():
        async with _client(lambda r: httpx.Response(401, text="bad key")) as c:
            return await _list(c)

    try:
        asyncio.run(run())
    except RuntimeError as e:
        assert "401" in str(e) and "bad key" in str(e)
    else:
        raise AssertionError("목록 실패가 예외로 올라오지 않았다")


def test_delete_error_message_has_status(monkeypatch):
    # CI 에는 .env 가 없어 supabase_url 이 비면 상대 URL 이 되어 httpx 가 다른 오류를 낸다
    class S:
        supabase_service_key = "k"; supabase_url = "http://t"; storage_bucket = "b"
    monkeypatch.setattr(_mod, "get_settings", lambda: S())

    async def run():
        async with _client(lambda r: httpx.Response(500, text="boom")) as c:
            await _mod._delete_batches(["7/a"], c)

    try:
        asyncio.run(run())
    except RuntimeError as e:
        assert "500" in str(e) and "boom" in str(e)
    else:
        raise AssertionError


def test_main_exits_nonzero_on_list_failure(monkeypatch, capsys):
    class S:
        supabase_service_key = "k"; supabase_url = "http://t"; storage_bucket = "b"
    monkeypatch.setattr(_mod, "get_settings", lambda: S())
    monkeypatch.setattr(_mod, "_connect_db", _fake_db_factory({}))
    real = httpx.AsyncClient
    monkeypatch.setattr(_mod.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(503, text="down"))))
    monkeypatch.setattr(_mod.sys, "argv", ["x", "--store-id", "7"])
    assert asyncio.run(_mod.main()) == 1
    assert "503" in capsys.readouterr().err


def test_object_path_of_handles_bucket_prefix_and_urls():
    f = _mod.object_path_of
    assert f("sources/7/voice/a.m4a", bucket="sources") == "7/voice/a.m4a"
    assert f("/7/voice/a.m4a", bucket="sources") == "7/voice/a.m4a"
    assert f("https://x.supabase.co/storage/v1/object/sign/sources/7/scan/b.pdf?token=t",
             bucket="sources") == "7/scan/b.pdf"
    assert f("https://x.supabase.co/other/7/a", bucket="sources") is None
    assert f(None, bucket="sources") is None


def test_plan_keeps_referenced_paths():
    objects = [{"path": "7/voice/old.m4a"}, {"path": "7/voice/new.m4a"}]
    keep = _mod.referenced_paths(["sources/7/voice/new.m4a"], bucket="sources")
    assert _mod.plan_deletions(objects, store_id=7, keep=keep) == ["7/voice/old.m4a"]


def test_main_apply_skips_files_still_referenced_by_sources(monkeypatch, capsys):
    # I3: 배포 뒤 새로 올라온 원본(sources.file_url 이 가리킴)은 --apply 에서도 지우지 않는다
    import json

    class S:
        supabase_service_key = "k"; supabase_url = "http://t"; storage_bucket = "sources"
    monkeypatch.setattr(_mod, "get_settings", lambda: S())
    dbs = []
    # 다른 매장(8)의 file_url 은 7 의 삭제 계획에 영향을 주지 않는다
    monkeypatch.setattr(_mod, "_connect_db", _fake_db_factory(
        {7: ["sources/7/voice/new.m4a"], 8: ["sources/7/voice/old.m4a"]}, dbs))
    deleted = []

    def handler(req):
        body = json.loads(req.content)
        if req.method == "DELETE":
            deleted.extend(body["prefixes"])
            return httpx.Response(200, json=[])
        listing = {"7": [{"name": "voice", "id": None}],
                   "7/voice": [{"name": "old.m4a", "id": "a", "metadata": {"size": 3}},
                               {"name": "new.m4a", "id": "b", "metadata": {"size": 4}}]}
        return httpx.Response(200, json=listing.get(body["prefix"], []))

    real = httpx.AsyncClient
    monkeypatch.setattr(_mod.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(_mod.sys, "argv", ["x", "--store-id", "7", "--apply"])
    assert asyncio.run(_mod.main()) == 0
    assert deleted == ["7/voice/old.m4a"]
    out = capsys.readouterr().out
    assert "kept=1" in out and "객체 1개 3B" in out
    assert dbs[0].closed
    assert all(args == (7,) for q, args in dbs[0].queries if "from sources" in q)


def test_main_deletes_nothing_when_db_unreachable(monkeypatch, capsys):
    class S:
        supabase_service_key = "k"; supabase_url = "http://t"; storage_bucket = "sources"
    monkeypatch.setattr(_mod, "get_settings", lambda: S())

    async def boom():
        raise OSError("refused")
    monkeypatch.setattr(_mod, "_connect_db", boom)
    called = []
    real = httpx.AsyncClient
    monkeypatch.setattr(_mod.httpx, "AsyncClient", lambda **kw: real(
        transport=httpx.MockTransport(lambda r: called.append(r) or httpx.Response(200, json=[]))))
    monkeypatch.setattr(_mod.sys, "argv", ["x", "--store-id", "7", "--apply"])
    assert asyncio.run(_mod.main()) == 1
    assert called == [] and "아무것도 지우지 않는다" in capsys.readouterr().err
