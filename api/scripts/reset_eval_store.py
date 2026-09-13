"""평가 매장의 자료·카드를 지운다. 추출을 다시 돌리기 위한 초기화다.

  python scripts/reset_eval_store.py --store store-a --dry-run
  python scripts/reset_eval_store.py --store store-a

**평가 매장(eval-*)에서만 동작한다.** demo-cafe 나 실제 매장에는 쓰지 않는다.
평가 실행 이력은 기본적으로 지우지 않는다 — 그건 영구 기록이다.

`--purge-runs` 는 그 예외다. 정답지가 바뀌어 이전 실행과 분모가 달라졌을 때만 쓴다.
분모가 다른 실행을 남겨두면 나중에 같은 축으로 비교하려다 틀린 결론을 낸다.
동결 트리거를 일시 해제하므로 명시적으로 요청할 때만 실행한다.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from app.config import get_settings  # noqa: E402

# FK 순서대로 지운다. 자식부터 부모로
STEPS = [
    ("facts",              "delete from facts where card_id in (select card_id from knowledge_cards where store_id=$1)"),
    ("card_evidence",      "delete from card_evidence where store_id=$1"),
    ("card_review_events", "delete from card_review_events where store_id=$1"),
    ("card_embeddings",    "delete from card_embeddings where store_id=$1"),
    ("카드 버전포인터 해제", "update knowledge_cards set draft_version_id=null, published_version_id=null where store_id=$1"),
    ("card_versions",      "delete from card_versions where store_id=$1"),
    ("knowledge_cards",    "delete from knowledge_cards where store_id=$1"),
    ("ingest_job_sources", "delete from ingest_job_sources where store_id=$1"),
    ("ingest_jobs",        "delete from ingest_jobs where store_id=$1"),
    ("source_video",       "delete from source_video where source_id in (select source_id from sources where store_id=$1)"),
    ("source_voice",       "delete from source_voice where source_id in (select source_id from sources where store_id=$1)"),
    ("source_kakao",       "delete from source_kakao where source_id in (select source_id from sources where store_id=$1)"),
    ("source_scan",        "delete from source_scan where source_id in (select source_id from sources where store_id=$1)"),
    ("source_frames",      "delete from source_frames where video_id in (select video_id from source_video where source_id in (select source_id from sources where store_id=$1))"),
    ("sources",            "delete from sources where store_id=$1"),
]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True, help="eval-a 또는 store-a 형식 둘 다 받는다")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-sources", action="store_true",
                    help="카드만 지우고 자료·전사문은 남긴다. 재업로드와 STT 를 건너뛰므로 "
                         "추출 변동만 따로 재거나 실험을 빠르게 반복할 때 쓴다")
    ap.add_argument("--purge-runs", action="store_true",
                    help="이 매장의 평가 실행 이력까지 지운다. 정답지가 바뀌어 "
                         "이전 실행과 분모가 달라졌을 때만 쓴다")
    args = ap.parse_args()

    slug = args.store.replace("store-", "eval-")
    if not slug.startswith("eval-"):
        print(f"평가 매장에서만 쓴다. eval-* 가 아니다: {slug}", file=sys.stderr)
        return 1

    conn = await asyncpg.connect(get_settings().supabase_db_url)
    try:
        store_id = await conn.fetchval("select store_id from stores where store_slug=$1", slug)
        if store_id is None:
            print(f"매장이 없다: {slug}", file=sys.stderr)
            return 1

        before = await conn.fetchrow(
            "select (select count(*) from sources where store_id=$1) as src, "
            "       (select count(*) from knowledge_cards where store_id=$1) as cards",
            store_id,
        )
        print(f"{slug} (store_id={store_id}) — 자료 {before['src']}건 · 카드 {before['cards']}장")
        if args.dry_run:
            print("dry-run. 지우지 않았다")
            return 0

        steps = STEPS
        if args.keep_sources:
            # 자료·전사문·프레임은 남긴다. 파이프라인이 기존 전사문을 재사용한다
            # 전사문은 source_video·source_voice 에 있다. 프레임은 매 실행 다시 뽑으므로
            # 남겨두면 중복만 쌓인다
            keep = {"source_video", "source_voice", "source_kakao", "source_scan",
                    "sources"}
            steps = [(n, q) for n, q in STEPS if n not in keep]
            print("  (--keep-sources: 자료·전사문 유지)")

        async with conn.transaction():
            for name, sql in steps:
                result = await conn.execute(sql, store_id)
                n = result.rsplit(" ", 1)[-1]
                if n not in ("0",):
                    print(f"  {name:<22} {n}")
        if args.purge_runs:
            async with conn.transaction():
                # 동결 트리거를 일시 해제한다. 예외적 작업이므로 범위를 최소로 둔다
                await conn.execute("alter table extraction_results disable trigger "
                                   "trg_extraction_results_append_only")
                await conn.execute("alter table extraction_runs disable trigger "
                                   "trg_extraction_runs_freeze")
                await conn.execute("alter table evaluation_results disable trigger "
                                   "trg_evaluation_results_append_only")
                await conn.execute("alter table evaluation_runs disable trigger "
                                   "trg_evaluation_runs_freeze")
                try:
                    for name, sql in [
                        ("extraction_results", "delete from extraction_results where store_id=$1"),
                        ("extraction_runs",    "delete from extraction_runs where store_id=$1"),
                        ("evaluation_results", "delete from evaluation_results where store_id=$1"),
                        ("evaluation_runs",    "delete from evaluation_runs where store_id=$1"),
                    ]:
                        n = (await conn.execute(sql, store_id)).rsplit(" ", 1)[-1]
                        if n != "0":
                            print(f"  {name:<22} {n}  (이력 삭제)")
                finally:
                    await conn.execute("alter table extraction_results enable trigger "
                                       "trg_extraction_results_append_only")
                    await conn.execute("alter table extraction_runs enable trigger "
                                       "trg_extraction_runs_freeze")
                    await conn.execute("alter table evaluation_results enable trigger "
                                       "trg_evaluation_results_append_only")
                    await conn.execute("alter table evaluation_runs enable trigger "
                                       "trg_evaluation_runs_freeze")
            print("초기화 완료. **평가 실행 이력도 지웠다** — 새 정답지로 처음부터 다시 잰다")
        else:
            print("초기화 완료. 평가 실행 이력은 그대로 남아 있다")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
