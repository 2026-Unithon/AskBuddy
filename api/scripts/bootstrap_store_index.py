"""매장 활성 공개 색인 점검·준비. 점주 답변 worker 를 켜기 전에 돌린다.

  python scripts/bootstrap_store_index.py                 # 모든 매장 점검만 (비용 없음)
  python scripts/bootstrap_store_index.py --store-id 3    # 한 매장 점검만
  python scripts/bootstrap_store_index.py --apply         # 준비가 필요한 매장을 모두 재발행
  python scripts/bootstrap_store_index.py --store-id 3 --apply

승인 카드는 있는데 활성 색인이 없거나(MISSING) 임베딩 설정이 바뀐(OUTDATED) 매장을
현재 승인 카드 그대로 다시 발행해 R 색인을 만든다. `--apply` 는 임베딩 비용이 든다.
출처 없는 레거시 카드는 공개판에서 빠진다(경고 로그). 모두 빠지면 EMPTY_MANIFEST 다.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from app.deps import close_pool, get_pool, init_pool  # noqa: E402
from app.publish.bootstrap import (  # noqa: E402
    NEEDS_BOOTSTRAP,
    bootstrap_store_index,
    index_status,
    stores_needing_index,
)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store-id", type=int, help="한 매장만 본다")
    parser.add_argument("--apply", action="store_true", help="실제로 재발행한다(비용 발생)")
    parser.add_argument("--cost-phase", default="OPERATING",
                        choices=("REGISTRATION", "OPERATING"))
    args = parser.parse_args(argv)

    await init_pool()
    pool = get_pool()
    failed = 0
    try:
        if args.store_id is not None:
            async with pool.acquire() as conn:
                targets = [await index_status(conn, store_id=args.store_id)]
        else:
            targets = await stores_needing_index(pool)
        if not targets:
            print("색인 준비가 필요한 매장이 없다")
            return 0
        for status in targets:
            print(f"store={status.store_id} status={status.status} "
                  f"approved_cards={status.approved_cards} "
                  f"publication_revision={status.publication_revision}")
            if not args.apply or status.status not in NEEDS_BOOTSTRAP:
                continue
            _, result = await bootstrap_store_index(
                pool, store_id=status.store_id, cost_phase=args.cost_phase)
            ok = result is not None and result.status in ("PUBLISHED", "ALREADY_APPLIED")
            failed += 0 if ok else 1
            print(f"  → {result.status if result else 'SKIPPED'}"
                  f" snapshot={result.snapshot_id if result else None}"
                  f" code={result.error_code if result else None}")
        if not args.apply and any(s.status in NEEDS_BOOTSTRAP for s in targets):
            print("점검만 했다. 준비하려면 --apply 를 붙인다(임베딩 비용 발생)")
    finally:
        await close_pool()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
