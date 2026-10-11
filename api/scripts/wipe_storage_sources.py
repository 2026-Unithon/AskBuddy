"""Storage `sources` 버킷의 매장 파일을 지운다. 기본은 dry-run(목록·개수·총 바이트만).

    python scripts/wipe_storage_sources.py --store-id 7            # dry-run
    python scripts/wipe_storage_sources.py --all-stores            # dry-run
    python scripts/wipe_storage_sources.py --store-id 7 --apply    # 실제 삭제

--apply 는 되돌릴 수 없다. 삭제 대상은 `{store_id}/` 접두사 객체뿐이다.
매장 목록은 DB `stores` 에서 읽는다. 지금 DB 의 `sources.file_url` 이 가리키는 파일은
(같은 매장 기준) 삭제 목록에서 뺀다 — 배포 뒤 새로 올라온 원본을 지우지 않기 위해서다.
DB 를 읽지 못한 매장은 아무것도 지우지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402

BATCH = 100


def object_path_of(file_url: str | None, *, bucket: str) -> str | None:
    """sources.file_url 을 버킷 안 객체 경로(`{store_id}/...`)로 바꾼다. 못 읽으면 None.

    file_url 은 `sources/7/voice/x.m4a`(버킷 접두) 또는 `.../storage/v1/object/[sign/]sources/7/...`
    URL 모양일 수 있다.
    """
    if not file_url:
        return None
    path = file_url
    marker = "/storage/v1/object/"
    if path.startswith(("http://", "https://")):
        if marker not in path:
            return None
        path = path.split(marker, 1)[1].split("?", 1)[0]
        for head in ("sign/", "public/", "authenticated/"):
            if path.startswith(head):
                path = path[len(head):]
                break
    path = path.lstrip("/")
    if path.startswith(f"{bucket}/"):
        path = path[len(bucket) + 1:]
    return path or None


def referenced_paths(file_urls: list[str | None], *, bucket: str) -> set[str]:
    return {p for p in (object_path_of(u, bucket=bucket) for u in file_urls) if p}


def plan_deletions(objects: list[dict[str, Any]], *, store_id: int,
                   keep: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """삭제할 경로. `{store_id}/` 로 시작하는 정상 경로만, 중복 없이 정렬해 돌려준다.

    list_store_objects 는 경로를 `path` 로 주고, 단위 테스트는 `name` 을 쓴다. 둘 다 받는다.
    다른 매장 접두사(70/ 같은 접두 겹침)·상위 경로(..)·빈 구간은 버린다.
    keep(지금 sources.file_url 이 가리키는 경로)은 지우지 않는다.
    """
    prefix = f"{store_id}/"
    out: set[str] = set()
    for o in objects:
        name = o.get("path") or o.get("name")
        if not isinstance(name, str) or not name.startswith(prefix):
            continue
        rest = name[len(prefix):]
        parts = rest.split("/")
        if not rest or any(p in ("", ".", "..") for p in parts):
            continue
        if name in keep:
            continue
        out.add(name)
    return sorted(out)


def _err(res: httpx.Response, what: str) -> RuntimeError:
    # 상태 코드와 본문 앞부분만. 헤더·키는 싣지 않는다
    return RuntimeError(f"{what} {res.status_code}: {res.text[:200]}")


async def list_objects_recursive(client: httpx.AsyncClient, *, base_url: str, bucket: str,
                                 headers: dict[str, str], prefix: str,
                                 _depth: int = 0) -> list[dict[str, Any]]:
    """prefix 아래 실제 객체를 폴더 안까지 내려가며 모은다. 목록 실패는 예외로 올린다.

    Supabase 목록 응답에서 폴더 항목은 id·metadata 가 없다. 그런 항목은 하위로 내려간다.
    """
    if _depth > 8:
        raise RuntimeError(f"목록 깊이 초과: {prefix}")
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        res = await client.post(
            f"{base_url}/storage/v1/object/list/{bucket}", headers=headers,
            json={"prefix": prefix, "limit": 100, "offset": offset})
        if res.status_code != 200:
            raise _err(res, f"목록 실패({prefix})")
        items = res.json() or []
        for item in items:
            name = item.get("name")
            if not name:
                continue
            path = f"{prefix}/{name}"
            if item.get("id") is None and not item.get("metadata"):
                out.extend(await list_objects_recursive(
                    client, base_url=base_url, bucket=bucket, headers=headers,
                    prefix=path, _depth=_depth + 1))
            else:
                size = (item.get("metadata") or {}).get("size")
                out.append({"path": path, "bytes": size})
        if len(items) < 100:
            break
        offset += 100
    return out


async def list_store_objects_strict(client: httpx.AsyncClient, store_id: int, *, base_url: str,
                                    bucket: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    """매장 접두사 전체를 재귀로 나열한다. 최상위 폴더가 아직 없으면(404 아닌 빈 목록) 빈 결과."""
    return await list_objects_recursive(
        client, base_url=base_url, bucket=bucket, headers=headers, prefix=str(store_id))


async def _delete_batches(paths: list[str], client: httpx.AsyncClient | None = None) -> None:
    s = get_settings()
    own = client is None
    client = client or httpx.AsyncClient(timeout=60)
    try:
        for i in range(0, len(paths), BATCH):
            res = await client.request(
                "DELETE", f"{s.supabase_url}/storage/v1/object/{s.storage_bucket}",
                headers={"Authorization": f"Bearer {s.supabase_service_key}"},
                json={"prefixes": paths[i:i + BATCH]})
            if res.status_code != 200:
                raise _err(res, "삭제 실패")
    finally:
        if own:
            await client.aclose()


async def _store_ids(args: argparse.Namespace, db) -> list[int]:
    if args.store_id is not None:
        return [args.store_id]
    # store-isolation-ok: 운영자가 --all-stores 로 고른 전체 매장 목록이다
    rows = await db.fetch("select store_id from stores order by store_id")
    return [r["store_id"] for r in rows]


async def store_file_urls(conn, store_id: int) -> list[str | None]:
    """이 매장 자료가 지금 가리키는 원본 경로(store_id 로 좁힌다)."""
    rows = await conn.fetch(
        "select file_url from sources where store_id = $1 and file_url is not null", store_id)
    return [r["file_url"] for r in rows]


async def _connect_db():
    import asyncpg
    return await asyncpg.connect(get_settings().supabase_db_url)


async def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--store-id", type=int)
    g.add_argument("--all-stores", action="store_true")
    ap.add_argument("--apply", action="store_true", help="실제로 지운다(기본은 dry-run)")
    args = ap.parse_args()

    if args.apply:
        print("경고: 되돌릴 수 없다. Storage 객체를 영구 삭제한다.", file=sys.stderr)

    s = get_settings()
    if not s.supabase_service_key:
        print("SUPABASE_SERVICE_KEY 가 없다", file=sys.stderr)
        return 2
    headers = {"Authorization": f"Bearer {s.supabase_service_key}"}
    failed = False
    try:
        db = await _connect_db()
    except Exception as e:
        # 지금 쓰이는 원본을 가려낼 수 없으면 아무것도 지우지 않는다
        print(f"DB 연결 실패 — 아무것도 지우지 않는다: {type(e).__name__}", file=sys.stderr)
        return 1
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            for sid in await _store_ids(args, db):
                try:
                    keep = referenced_paths(await store_file_urls(db, sid),
                                            bucket=s.storage_bucket)
                    objs = await list_store_objects_strict(
                        client, sid, base_url=s.supabase_url, bucket=s.storage_bucket,
                        headers=headers)
                    paths = plan_deletions(objs, store_id=sid, keep=keep)
                    kept = len(plan_deletions(objs, store_id=sid)) - len(paths)
                    planned = set(paths)
                    total = sum(int(o["bytes"]) for o in objs
                                if o.get("bytes") is not None and o.get("path") in planned)
                    print(f"store={sid} 객체 {len(paths)}개 {total}B kept={kept}"
                          f"(sources.file_url 이 가리키는 파일)")
                    if args.apply and paths:
                        await _delete_batches(paths, client)
                        print(f"store={sid} 삭제 완료 {len(paths)}개")
                except Exception as e:  # 오류는 매장 단위로 보고하고 계속한다
                    failed = True
                    print(f"store={sid} 실패: {type(e).__name__}: {str(e)[:300]}",
                          file=sys.stderr)
    finally:
        await db.close()
    if not args.apply:
        print("dry-run: 아무것도 지우지 않았다. 지우려면 --apply")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
